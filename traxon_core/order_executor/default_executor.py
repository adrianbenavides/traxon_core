import asyncio
from decimal import Decimal
from typing import cast

from beartype import beartype

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import (
    DynamicSizeOrderBuilder,
    ExchangeId,
    OrderBuilder,
    OrderExecutionType,
)
from traxon_core.crypto.models.order import OrdersToExecute
from traxon_core.logs.notifiers import notifier
from traxon_core.logs.structlog import logger
from traxon_core.order_executor.base import OrderExecutor, OrderExecutorBase
from traxon_core.order_executor.config import ExecutorConfig
from traxon_core.order_executor.models import (
    ExecutionReport,
    OrderRequest,
    OrderStatus,
    OrderType,
)
from traxon_core.order_executor.rest import RestApiOrderExecutor
from traxon_core.order_executor.ws import WebSocketOrderExecutor


class DefaultOrderExecutor:
    @beartype
    def __init__(self, config: ExecutorConfig) -> None:
        self.config = config
        self.logger = logger.bind(component=self.__class__.__name__)

    @beartype
    def _to_order_request(self, order: OrderBuilder) -> OrderRequest:
        """Convert legacy OrderBuilder to new OrderRequest model."""
        if order.side is None:
            raise ValueError(f"Order for {order.market['symbol']} has no side")

        # Determine order type based on the execution type: maker -> limit, taker -> market
        order_type = OrderType.LIMIT if order.execution_type == OrderExecutionType.MAKER else OrderType.MARKET

        # Determine price for limit orders
        price = None
        if order_type == OrderType.LIMIT:
            if isinstance(order, DynamicSizeOrderBuilder):
                price = order.sizing_strategy.current_price
            else:
                # SizedOrderBuilder might not have a price set yet,
                # but it should have been determined by now or will be by the executor
                # when fetching the order book.
                pass

        return OrderRequest(
            symbol=str(order.market["symbol"]),
            side=order.side,
            order_type=order_type,
            amount=order.size() or Decimal(0.0),
            price=price,
            params={},  # TODO: OrderBuilder should provide the params dict
        )

    @beartype
    def _select_executor(self, exchange: Exchange) -> OrderExecutor:
        """Select appropriate executor for the exchange."""
        # Preference: WS > REST
        if exchange.has_ws_support():
            return WebSocketOrderExecutor(self.config)
        else:
            return RestApiOrderExecutor(self.config)

    @beartype
    async def _execute_order(self, exchange: Exchange, order: OrderBuilder) -> ExecutionReport | None:
        symbol = order.market["symbol"]
        log_prefix = OrderExecutorBase.log_prefix(exchange, symbol, order.side)

        # Some exchanges support setting the margin mode and leverage globally.
        if exchange.api.has.get("setMarginMode"):
            try:
                await exchange.api.set_margin_mode("cross", symbol)
            except Exception as e:
                self.logger.debug(f"{log_prefix} - failed to set margin mode: {e}")
        if exchange.api.has.get("setLeverage"):
            try:
                max_leverage = order.max_leverage()
                leverage = min(max_leverage, exchange.leverage) if max_leverage else exchange.leverage
                await exchange.api.set_leverage(leverage, symbol)
            except Exception as e:
                self.logger.debug(f"{log_prefix} - failed to set leverage: {e}")

        try:
            request = self._to_order_request(order)
            executor = self._select_executor(exchange)

            if request.order_type == OrderType.MARKET:
                report = await executor.execute_taker_order(exchange, request)
            else:
                report = await executor.execute_maker_order(exchange, request)

            if report is None:
                return None

            if report.status == OrderStatus.CLOSED:
                self.logger.info(f"{log_prefix} - order executed successfully")
                order.notify_filled()
            else:
                self.logger.warning(f"{log_prefix} - order not fully executed: {report.status}")

            return report

        except Exception as e:
            self.logger.warning(f"{log_prefix} - failed to execute order: {e}", exc_info=True)
            order.notify_failed()
            return None

    @beartype
    async def execute_orders(
        self, exchanges: list[Exchange], orders: OrdersToExecute
    ) -> list[ExecutionReport]:
        """Execute all orders in parallel across all symbols."""
        if not orders.updates and not orders.new:
            self.logger.info("no orders to execute")
            return []

        exchanges_by_id = {ExchangeId(exchange.id): exchange for exchange in exchanges}
        total_orders_len = orders.count()
        reports: list[ExecutionReport] = []

        # Process both updates and new orders
        all_orders: list[OrderBuilder] = []
        for order_list in orders.updates.values():
            all_orders.extend(order_list)
        for order_list in orders.new.values():
            all_orders.extend(order_list)

        # Create tasks for all orders
        tasks = []
        for order in all_orders:
            exchange = exchanges_by_id.get(order.exchange_id)
            if not exchange:
                self.logger.error(f"Exchange {order.exchange_id} not found for order")
                continue
            tasks.append(self._execute_order(exchange, order))

        # Execute all orders in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"critical error executing order task: {result}")
                continue

            if result is not None:
                reports.append(cast(ExecutionReport, result))

        filled_count = sum(1 for r in reports if r.status == OrderStatus.CLOSED)
        _log = f"filled {filled_count} out of {total_orders_len} orders"
        self.logger.info(_log)
        await notifier.notify(_log)

        return reports
