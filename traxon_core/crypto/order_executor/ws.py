import asyncio
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict

from beartype import beartype

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.order import OrderRequest
from traxon_core.crypto.order_executor.base import OrderExecutorBase
from traxon_core.crypto.order_executor.config import ExecutorConfig
from traxon_core.crypto.order_executor.exceptions import (
    OrderCreationError,
    OrderExecutorError,
)
from traxon_core.crypto.order_executor.models import ElapsedSeconds, ExecutionReport, OrderStatus


class OrderState(Enum):
    INITIALIZING = "INITIALIZING"
    CREATING_ORDER = "CREATING_ORDER"
    MONITORING_ORDER = "MONITORING_ORDER"
    UPDATING_ORDER = "UPDATING_ORDER"
    WAIT_UNTIL_ORDER_CANCELLED = "WAIT_UNTIL_ORDER_CANCELLED"


class WebSocketOrderExecutor(OrderExecutorBase):
    """
    Order executor that uses WebSockets via ccxt.pro to monitor and execute orders more efficiently.
    Provides real-time updates on order book and order status without polling.
    """

    @beartype
    def __init__(self, config: ExecutorConfig) -> None:
        super().__init__(config)
        self.short_retry_interval_seconds: float = 0.1
        self.long_retry_interval_seconds: float = 1.0

    @beartype
    def _to_execution_report(self, order_dict: dict[str, Any]) -> ExecutionReport:
        """Convert CCXT order dictionary to ExecutionReport model."""
        return ExecutionReport(
            id=str(order_dict["id"]),
            symbol=str(order_dict["symbol"]),
            status=OrderStatus(order_dict["status"]),
            amount=Decimal(str(order_dict["amount"])),
            filled=Decimal(str(order_dict["filled"])),
            remaining=Decimal(str(order_dict["remaining"])),
            average_price=Decimal(str(order_dict["price"])) if order_dict.get("price") else None,
            last_price=Decimal(str(order_dict["lastTradePrice"]))
            if order_dict.get("lastTradePrice")
            else None,
            timestamp=int(order_dict["timestamp"]),
        )

    @beartype
    async def execute_maker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport:
        """
        Execute a maker order using WebSocket connections for real-time updates.
        """
        self.validate_request(request)
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        log_prefix = self.log_prefix(exchange, symbol_str, request.side)

        if not exchange.has_ws_support():
            self.logger.warning(f"{log_prefix} - WebSocket support is not available for this exchange.")
            raise OrderExecutorError(f"WebSocket not supported for {exchange.id}")

        start_time = datetime.now()
        order_id: str | None = None
        order_book_state = None
        current_state = OrderState.INITIALIZING

        # Clean up any existing orders
        await self._cancel_pending_orders(exchange, symbol_str)

        self.logger.info(f"{log_prefix} - starting WebSocket order execution with state machine")
        order_book_task = asyncio.create_task(exchange.api.watch_order_book(symbol_str))
        orders_task = asyncio.create_task(exchange.api.watch_orders(symbol_str))

        try:
            while True:
                self.check_timeout(start_time, symbol_str, "maker-ws")
                elapsed_seconds = ElapsedSeconds((datetime.now() - start_time).total_seconds())

                # Process order book updates
                if order_book_task.done():
                    try:
                        order_book = order_book_task.result()
                        order_book_task = asyncio.create_task(exchange.api.watch_order_book(symbol_str))

                        new_state = self._analyze_order_book(
                            order_book,
                            request.side,
                            order_book_state,
                            elapsed_seconds,
                            log_prefix,
                        )
                        if new_state:
                            order_book_state = new_state
                            # Check spread
                            if float(order_book_state.spread_pct) > float(self.max_spread_pct):
                                self.logger.debug(
                                    f"{log_prefix} - spread too high: {order_book_state.spread_pct:.2%}"
                                )
                                order_book_state = None
                            else:
                                if current_state == OrderState.INITIALIZING:
                                    current_state = OrderState.CREATING_ORDER
                                elif current_state == OrderState.MONITORING_ORDER:
                                    current_state = OrderState.UPDATING_ORDER

                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - error processing order book: {e}")
                        order_book_task = asyncio.create_task(exchange.api.watch_order_book(symbol_str))

                # Check for order updates via WebSocket
                if orders_task.done():
                    try:
                        orders = orders_task.result()
                        orders_task = asyncio.create_task(exchange.api.watch_orders(symbol_str))

                        for o in orders:
                            if o["id"] == order_id:
                                report = self._to_execution_report(o)
                                if report.status == OrderStatus.CLOSED:
                                    self.logger.info(f"{log_prefix} - order filled")
                                    return report
                                elif report.status in [OrderStatus.REJECTED, OrderStatus.CANCELED]:
                                    self.logger.warning(
                                        f"{log_prefix} - order failed with status: {report.status}"
                                    )
                                    order_id = None
                                    current_state = OrderState.WAIT_UNTIL_ORDER_CANCELLED
                                    break
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - error processing order updates: {e}")
                        orders_task = asyncio.create_task(exchange.api.watch_orders(symbol_str))

                if current_state == OrderState.CREATING_ORDER and order_book_state is not None:
                    self.logger.debug(
                        f"{log_prefix} - creating limit order at {order_book_state.best_price}, "
                        f"with size {request.amount:.6f}"
                    )
                    try:
                        params: Dict[str, Any] = {}
                        order_dict = await exchange.api.create_limit_order(
                            symbol=symbol_str,
                            side=side_ccxt,
                            amount=float(request.amount),
                            price=float(order_book_state.best_price),
                            params=params,
                        )
                        order_id = str(order_dict["id"])
                        self.logger.info(f"{log_prefix} - created limit order (id={order_id})")
                        current_state = OrderState.MONITORING_ORDER
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - failed to create limit order: {e}")
                        await asyncio.sleep(self.long_retry_interval_seconds)

                elif current_state == OrderState.UPDATING_ORDER and order_id and order_book_state:
                    try:
                        await self._cancel_pending_orders(exchange, symbol_str, order_id)
                        order_id = None
                        current_state = OrderState.WAIT_UNTIL_ORDER_CANCELLED
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - failed to update order (cancel): {e}")
                        current_state = OrderState.MONITORING_ORDER

                elif current_state == OrderState.WAIT_UNTIL_ORDER_CANCELLED:
                    if not order_id:
                        current_state = OrderState.CREATING_ORDER

                await asyncio.sleep(self.short_retry_interval_seconds)

        except Exception as e:
            self.logger.error(f"{log_prefix} - error executing maker order: {e}", exc_info=True)
            # Fallback to taker if possible, or just raise
            raise
        finally:
            tasks = [order_book_task, orders_task]
            for task in tasks:
                if not task.done():
                    task.cancel()
            if order_id:
                await self._cancel_pending_orders(exchange, symbol_str, order_id)

    @beartype
    async def execute_taker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport:
        """
        Execute a taker order (market order) using WebSocket connections for real-time updates.
        """
        self.validate_request(request)
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        log_prefix = self.log_prefix(exchange, symbol_str, request.side)

        if not exchange.has_ws_support():
            self.logger.warning(f"{log_prefix} - WebSocket support is not available for this exchange.")
            raise OrderExecutorError(f"WebSocket not supported for {exchange.id}")

        start_time = datetime.now()
        await self._cancel_pending_orders(exchange, symbol_str)

        self.logger.info(f"{log_prefix} - starting WebSocket taker order execution")
        orders_task = asyncio.create_task(exchange.api.watch_orders(symbol_str))

        try:
            params: Dict[str, Any] = {}
            order_dict = await exchange.api.create_market_order(
                symbol=symbol_str,
                side=side_ccxt,
                amount=float(request.amount),
                params=params,
            )
            order_id = str(order_dict["id"])

            while True:
                self.check_timeout(start_time, symbol_str, "taker-ws")

                if orders_task.done():
                    orders = orders_task.result()
                    orders_task = asyncio.create_task(exchange.api.watch_orders(symbol_str))
                    for o in orders:
                        if o["id"] == order_id:
                            report = self._to_execution_report(o)
                            if report.status == OrderStatus.CLOSED:
                                self.logger.info(f"{log_prefix} - taker order filled")
                                return report
                            elif report.status in [OrderStatus.REJECTED, OrderStatus.CANCELED]:
                                raise OrderCreationError(symbol_str, "market", f"Order was {report.status}")

                # Fallback check via REST every 5 seconds if WS is slow
                elapsed = (datetime.now() - start_time).total_seconds()
                if int(elapsed) % 5 == 0:
                    status_dict = await exchange.api.fetch_order(order_id, symbol_str)
                    report = self._to_execution_report(status_dict)
                    if report.status == OrderStatus.CLOSED:
                        return report

                await asyncio.sleep(self.short_retry_interval_seconds)

        except Exception as e:
            self.logger.error(f"{log_prefix} - unexpected error executing taker order: {e}")
            raise
        finally:
            if not orders_task.done():
                orders_task.cancel()
            await self._cancel_pending_orders(exchange, symbol_str, order_id=None)
