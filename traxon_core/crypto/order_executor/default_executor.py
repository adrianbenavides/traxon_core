import asyncio

from beartype import beartype

from traxon_core.crypto.exchanges.config import ExchangeApiConnection
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import ExchangeId
from traxon_core.crypto.models.order import OrderRequest, OrdersToExecute, OrderType
from traxon_core.crypto.order_executor.base import OrderExecutor, OrderExecutorBase
from traxon_core.crypto.order_executor.config import ExecutorConfig
from traxon_core.crypto.order_executor.event_bus import OrderEventBus
from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus
from traxon_core.crypto.order_executor.rest import RestApiOrderExecutor
from traxon_core.crypto.order_executor.router import OrderRouter
from traxon_core.crypto.order_executor.ws import WebSocketOrderExecutor
from traxon_core.logs.notifiers import notifier
from traxon_core.logs.structlog import logger


class DefaultOrderExecutor:
    @beartype
    def __init__(self, config: ExecutorConfig) -> None:
        self.config = config
        self._event_bus: OrderEventBus | None = None
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

        if exchange.api.has.get("setMarginMode"):
            try:
                await exchange.api.set_margin_mode("cross", symbol)
            except Exception as e:
                self.logger.debug(f"{log_prefix} - failed to set margin mode: {e}")
        if exchange.api.has.get("setLeverage"):
            try:
                await exchange.api.set_leverage(exchange.leverage, symbol)
            except Exception as e:
                self.logger.debug(f"{log_prefix} - failed to set leverage: {e}")

        try:
            executor = self._select_executor(exchange)

            if order.order_type == OrderType.MARKET:
                report = await executor.execute_taker_order(exchange, order)
            else:
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

        router = OrderRouter(self.config, event_bus=self._event_bus)
        reports = await router.route_and_collect(
            exchanges,
            orders,
            execute_fn=self._execute_order,
        )

        filled_count = sum(1 for r in reports if r.status == OrderStatus.CLOSED)
        summary = f"filled {filled_count} out of {orders.count()} orders"
        self.logger.info(summary)
        await notifier.notify(summary)

        return reports
