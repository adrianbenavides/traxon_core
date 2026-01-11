import asyncio
from typing import cast

from beartype import beartype

from traxon_core.crypto.exchanges.config import ExchangeApiConnection
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import ExchangeId
from traxon_core.crypto.models.order import OrderRequest, OrdersToExecute, OrderType
from traxon_core.crypto.order_executor.base import OrderExecutor, OrderExecutorBase
from traxon_core.crypto.order_executor.config import ExecutorConfig
from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus
from traxon_core.crypto.order_executor.rest import RestApiOrderExecutor
from traxon_core.crypto.order_executor.ws import WebSocketOrderExecutor
from traxon_core.logs.notifiers import notifier
from traxon_core.logs.structlog import logger


class DefaultOrderExecutor:
    @beartype
    def __init__(self, config: ExecutorConfig) -> None:
        self.config = config
        self.logger = logger.bind(component=self.__class__.__name__)

    @beartype
    def _select_executor(self, exchange: Exchange) -> OrderExecutor:
        if exchange.api_connection == ExchangeApiConnection.WEBSOCKET.value and exchange.has_ws_support():
            return WebSocketOrderExecutor(self.config)
        else:
            return RestApiOrderExecutor(self.config)

    @beartype
    async def _execute_order(self, exchange: Exchange, order: OrderRequest) -> ExecutionReport | None:
        symbol = order.symbol
        log_prefix = OrderExecutorBase.log_prefix(exchange, symbol, order.side)

        # Some exchanges support setting the margin mode and leverage globally.
        if exchange.api.has.get("setMarginMode"):
            try:
                await exchange.api.set_margin_mode("cross", symbol)
            except Exception as e:
                self.logger.debug(f"{log_prefix} - failed to set margin mode: {e}")
        if exchange.api.has.get("setLeverage"):
            try:
                # TODO: Leverage should probably be part of OrderRequest if we want it to be per-order
                #   and default to exchange.leverage if not specified.
                await exchange.api.set_leverage(exchange.leverage, symbol)
            except Exception as e:
                self.logger.debug(f"{log_prefix} - failed to set leverage: {e}")

        try:
            executor = self._select_executor(exchange)

            if order.order_type == OrderType.MARKET:
                report = await executor.execute_taker_order(exchange, order)
            else:
                # TODO: handle orders with prices crossing the spread -> should place the order and return
                report = await executor.execute_maker_order(exchange, order)

            if report is None:
                return None

            if report.status == OrderStatus.CLOSED:
                self.logger.info(f"{log_prefix} - order executed successfully")
                order.pairing.notify_filled()
            else:
                self.logger.warning(f"{log_prefix} - order not fully executed: {report.status}")

            return report

        except Exception as e:
            self.logger.warning(f"{log_prefix} - failed to execute order: {e}", exc_info=True)
            order.pairing.notify_failed()
            return None

    @beartype
    async def execute_orders(
        self, exchanges: list[Exchange], orders: OrdersToExecute
    ) -> list[ExecutionReport]:
        """Execute all orders in parallel across all symbols."""
        if orders.is_empty():
            self.logger.info("no orders to execute")
            return []

        exchanges_by_id = {ExchangeId(exchange.id): exchange for exchange in exchanges}
        total_orders_len = orders.count()
        reports: list[ExecutionReport] = []

        # Process both updates and new orders
        all_order_requests: list[OrderRequest] = []
        for req_list in orders.updates.values():
            all_order_requests.extend(req_list)
        for req_list in orders.new.values():
            all_order_requests.extend(req_list)

        # Create tasks for all orders
        tasks = []
        for order in all_order_requests:
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
