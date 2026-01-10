import asyncio
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict

from beartype import beartype

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.order import OrderRequest, OrderType
from traxon_core.crypto.order_executor.base import OrderExecutorBase
from traxon_core.crypto.order_executor.config import ExecutorConfig
from traxon_core.crypto.order_executor.exceptions import (
    OrderCreationError,
    OrderExecutorError,
)
from traxon_core.crypto.order_executor.models import (
    ElapsedSeconds,
    ExecutionReport,
    OrderBookState,
    OrderStatus,
)


class OrderState(str, Enum):
    CREATE_ORDER = "CREATE_ORDER"
    MONITORING_ORDER = "MONITORING_ORDER"
    UPDATING_ORDER = "UPDATING_ORDER"
    WAIT_UNTIL_ORDER_CANCELLED = "WAIT_UNTIL_ORDER_CANCELLED"


class RestApiOrderExecutor(OrderExecutorBase):
    """
    Order executor that uses REST API calls to place and monitor orders.
    Provides polling-based approach for exchanges that don't support WebSockets
    or as a fallback option.
    """

    @beartype
    def __init__(self, config: ExecutorConfig) -> None:
        super().__init__(config)
        self.retry_interval_seconds: float = 1.0

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
    async def _fetch_order_book_update(
        self,
        exchange: Exchange,
        symbol: str,
        request: OrderRequest,
        current_state: OrderBookState | None,
        elapsed_seconds: ElapsedSeconds,
    ) -> OrderBookState | None:
        log_prefix = self.log_prefix(exchange, symbol, request.side)

        try:
            order_book: dict[str, list[list[float]]] = await exchange.api.fetch_order_book(symbol)
        except Exception as e:
            self.logger.warning(f"{log_prefix} - error processing order book: {e}")
            return None
        return self._analyze_order_book(order_book, request.side, current_state, elapsed_seconds, log_prefix)

    @beartype
    async def execute_maker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport | None:
        """
        Execute a maker order using REST API calls.

        Tries to fill the order passively with a post-only limit order at the best price.
        After the timeout, places a market order.
        """
        self.validate_request(request)
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        log_prefix = self.log_prefix(exchange, symbol_str, request.side)

        start_time = datetime.now()
        order_id: str | None = None
        order_book_state: OrderBookState | None = None
        current_state: OrderState = OrderState.CREATE_ORDER

        # Clean up any existing orders
        await self._cancel_pending_orders(exchange, symbol_str)
        self.logger.info(f"{log_prefix} - starting REST API maker order execution")

        try:
            while True:
                self.check_timeout(start_time, symbol_str, "maker")
                elapsed_seconds = ElapsedSeconds((datetime.now() - start_time).total_seconds())

                if current_state == OrderState.CREATE_ORDER:
                    new_state = await self._fetch_order_book_update(
                        exchange, symbol_str, request, order_book_state, elapsed_seconds
                    )
                    if not new_state:
                        await asyncio.sleep(self.retry_interval_seconds)
                        continue

                    order_book_state = new_state

                    # Check spread
                    if order_book_state.spread_pct > self.max_spread_pct:
                        self.logger.debug(
                            f"{log_prefix} - spread too high: {order_book_state.spread_pct:.2%}"
                        )
                        await asyncio.sleep(self.retry_interval_seconds)
                        continue

                    self.logger.debug(
                        f"{log_prefix} - creating limit order at {order_book_state.best_price}, "
                        f"with size {request.amount:.6f}"
                    )
                    try:
                        # Prepare params
                        params: Dict[str, Any] = {}
                        order_status_dict = await exchange.api.create_limit_order(
                            symbol=symbol_str,
                            side=side_ccxt,
                            amount=float(request.amount),
                            price=float(order_book_state.best_price),
                            params=params,
                        )
                        order_id = order_status_dict["id"]
                        self.logger.info(f"{log_prefix} - created limit order (id={order_id})")
                        current_state = OrderState.MONITORING_ORDER
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - failed to create limit order: {e}")
                        await asyncio.sleep(self.retry_interval_seconds)

                elif current_state == OrderState.MONITORING_ORDER and order_id:
                    try:
                        order_status_dict = await exchange.api.fetch_order(order_id, symbol_str)
                        report = self._to_execution_report(order_status_dict)

                        if report.status == OrderStatus.CLOSED:
                            self.logger.info(f"{log_prefix} - order filled")
                            return report
                        elif report.status in [OrderStatus.REJECTED, OrderStatus.CANCELED]:
                            self.logger.warning(f"{log_prefix} - order failed with status: {report.status}")
                            order_id = None
                            current_state = OrderState.CREATE_ORDER
                            continue

                        # Check if price update is needed
                        new_state = await self._fetch_order_book_update(
                            exchange, symbol_str, request, order_book_state, elapsed_seconds
                        )
                        if new_state:
                            order_book_state = new_state
                            current_state = OrderState.UPDATING_ORDER

                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - failed to fetch order status: {e}")
                        await asyncio.sleep(self.retry_interval_seconds)

                elif current_state == OrderState.UPDATING_ORDER and order_id and order_book_state:
                    try:
                        # For simplicity in this first refactor, we cancel and replace
                        # Later we can add back editOrder support check if it's important
                        await self._cancel_pending_orders(exchange, symbol_str, order_id)
                        order_id = None
                        current_state = OrderState.WAIT_UNTIL_ORDER_CANCELLED
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - failed to initiate update (cancel): {e}")
                        current_state = OrderState.MONITORING_ORDER

                elif current_state == OrderState.WAIT_UNTIL_ORDER_CANCELLED:
                    # We already cancelled in UPDATING_ORDER, just wait a bit and go back to CREATE
                    await asyncio.sleep(self.retry_interval_seconds)
                    current_state = OrderState.CREATE_ORDER

                await asyncio.sleep(self.retry_interval_seconds)

        except OrderExecutorError:
            # Re-raise managed executor errors
            raise
        except Exception as e:
            # Fallback for unexpected errors
            self.logger.info(f"{log_prefix} - maker execution interrupted, switching to market order: {e}")
            await self._cancel_pending_orders(exchange, symbol_str, order_id=order_id)
            # Transition to taker request
            taker_request = request.model_copy(update={"order_type": OrderType.MARKET})
            return await self.execute_taker_order(exchange, taker_request)
        finally:
            await self._cancel_pending_orders(exchange, symbol_str, order_id=order_id)

    @beartype
    async def execute_taker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport:
        """
        Execute a taker order (market order) using REST API calls.
        """
        self.validate_request(request)
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        log_prefix = self.log_prefix(exchange, symbol_str, request.side)

        start_time = datetime.now()
        await self._cancel_pending_orders(exchange, symbol_str)
        self.logger.info(f"{log_prefix} - starting REST API taker order execution")

        attempt = 0
        max_attempts = 3

        while attempt < max_attempts:
            self.check_timeout(start_time, symbol_str, "taker")
            try:
                params: Dict[str, Any] = {}
                order_dict = await exchange.api.create_market_order(
                    symbol=symbol_str,
                    side=side_ccxt,
                    amount=float(request.amount),
                    params=params,
                )

                # Market orders might not be filled immediately on some exchanges?
                # Usually they are. Let's poll until closed.
                order_id = str(order_dict["id"])

                while True:
                    self.check_timeout(start_time, symbol_str, "taker-poll")
                    status_dict = await exchange.api.fetch_order(order_id, symbol_str)
                    report = self._to_execution_report(status_dict)

                    if report.status == OrderStatus.CLOSED:
                        self.logger.info(f"{log_prefix} - taker order filled")
                        return report
                    elif report.status in [OrderStatus.REJECTED, OrderStatus.CANCELED]:
                        raise OrderCreationError(symbol_str, "market", f"Order was {report.status}")

                    await asyncio.sleep(self.retry_interval_seconds)

            except Exception as e:
                attempt += 1
                self.logger.warning(f"{log_prefix} - taker attempt {attempt} failed: {e}")
                if attempt >= max_attempts:
                    raise OrderCreationError(symbol_str, "market", str(e))
                await asyncio.sleep(self.retry_interval_seconds * attempt)

        raise OrderExecutorError(
            f"Failed to execute taker order for {symbol_str} after {max_attempts} attempts"
        )
