from __future__ import annotations

from abc import ABC
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.order import OrderRequest, OrderSide, OrderType, OrderValidationError
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.event_bus import OrderEvent, OrderEventBus, OrderState
from traxon_core.crypto.order_executor.exceptions import (
    OrderCreationError,
    OrderFetchError,
    OrderTimeoutError,
    OrderUpdateError,
)
from traxon_core.crypto.order_executor.models import (
    ElapsedSeconds,
    ExecutionReport,
    OrderBookDepthIndex,
    OrderBookState,
    OrderStatus,
    SpreadPercent,
)
from traxon_core.crypto.order_executor.reprice import RepricePolicy, build_reprice_policy
from traxon_core.crypto.utils import log_prefix as log_prefix_util
from traxon_core.logs.structlog import logger


@runtime_checkable
class OrderExecutor(Protocol):
    """
    Protocol defining the interface for order execution strategies.

    Implementations can use REST API, WebSockets, or other methods
    to execute orders on exchanges.
    """

    @beartype
    async def execute_maker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport | None:
        """
        Execute a maker order (limit order) attempting to get filled passively.

        Args:
            exchange: Exchange instance to execute order on
            request: Standardized order request

        Returns:
            Execution report detailing the fill or None if no fill occurred

        Raises:
            OrderExecutorError: If execution fails (e.g. timeout, rejection)
        """
        ...

    @beartype
    async def execute_taker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport | None:
        """
        Execute a taker order (market order) for immediate execution.

        Args:
            exchange: Exchange instance to execute order on
            request: Standardized order request

        Returns:
            Execution report detailing the fill or None if no fill occurred

        Raises:
            OrderExecutorError: If execution fails (e.g. timeout, rejection)
        """
        ...


class OrderExecutorBase(ABC):
    """
    Abstract base class for order executors providing common functionality.
    """

    config: ExecutorConfig
    execution: OrderExecutionStrategy
    max_spread_pct: SpreadPercent
    timeout_duration: timedelta
    event_bus: OrderEventBus | None
    reprice_policy: RepricePolicy

    @beartype
    def __init__(self, config: ExecutorConfig, event_bus: OrderEventBus | None = None) -> None:
        self.config = config
        self.execution = config.execution
        self.max_spread_pct = SpreadPercent(config.max_spread_pct)
        self.timeout_duration = config.timeout_duration
        self.event_bus = event_bus
        self.reprice_policy = build_reprice_policy(config)
        self.logger = logger.bind(component=self.__class__.__name__)

    @beartype
    def _build_execution_report(
        self,
        order_dict: dict[str, Any],
        exchange_id: str,
        submit_time: datetime,
    ) -> ExecutionReport:
        """Convert CCXT order dictionary to ExecutionReport with exchange_id and fill_latency_ms."""
        fill_latency_ms = int((datetime.now() - submit_time).total_seconds() * 1000)
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
            exchange_id=exchange_id,
            fill_latency_ms=max(0, fill_latency_ms),
        )

    @staticmethod
    @beartype
    def log_prefix(exchange: Exchange, symbol: str, side: OrderSide | None = None) -> str:
        return log_prefix_util(exchange, symbol, side)

    @beartype
    def validate_request(self, request: OrderRequest) -> None:
        """
        Validate the order request against executor configuration.
        Raises OrderValidationError if invalid.
        """
        if request.amount <= 0:
            raise OrderValidationError(request.symbol, f"Invalid order amount: {request.amount}")

        if request.order_type == OrderType.LIMIT and (request.price is None or request.price <= 0):
            raise OrderValidationError(request.symbol, f"Invalid limit price: {request.price}")

    @beartype
    def check_timeout(self, start_time: datetime, symbol: str, order_type: str = "execution") -> None:
        """
        Check if the execution has exceeded the timeout duration.
        Raises OrderTimeoutError if timed out.
        """
        if datetime.now() - start_time > self.timeout_duration:
            raise OrderTimeoutError(symbol, order_type, self.timeout_duration.total_seconds())

    @beartype
    def should_retry(self, error: Exception, attempt: int, max_retries: int = 3) -> bool:
        """
        Determine if an operation should be retried based on the error type and attempt count.
        """
        if attempt >= max_retries:
            return False

        retriable_errors = (OrderFetchError, OrderUpdateError, OrderCreationError)

        return isinstance(error, retriable_errors)

    @beartype
    def _best_price_index(self, elapsed_seconds: ElapsedSeconds) -> OrderBookDepthIndex:
        """Determine price index based on elapsed time and execution strategy."""
        if self.execution == OrderExecutionStrategy.FAST:
            return OrderBookDepthIndex(0)

        if elapsed_seconds < 10:
            return OrderBookDepthIndex(5)
        elif elapsed_seconds < 30:
            return OrderBookDepthIndex(4)
        elif elapsed_seconds < 60:
            return OrderBookDepthIndex(3)
        elif elapsed_seconds < 120:
            return OrderBookDepthIndex(2)
        elif elapsed_seconds < 180:
            return OrderBookDepthIndex(1)
        else:
            return OrderBookDepthIndex(0)

    @beartype
    def _analyze_order_book(
        self,
        order_book: dict[str, list[list[float]]],
        side: OrderSide,
        current_state: OrderBookState | None,
        elapsed_seconds: ElapsedSeconds,
        log_prefix: str,
    ) -> OrderBookState | None:
        """Process order book data and determine the best price."""
        if not order_book.get("asks") or not order_book.get("bids"):
            logger.debug(f"{log_prefix} order book is missing asks or bids")
            return None

        best_ask: float = float(order_book["asks"][0][0])
        best_bid: float = float(order_book["bids"][0][0])
        spread_pct: SpreadPercent = SpreadPercent((best_ask - best_bid) / best_bid)

        best_price_index: OrderBookDepthIndex = self._best_price_index(elapsed_seconds)
        current_best_price: float | None = float(current_state.best_price) if current_state else None

        if side == OrderSide.BUY:
            max_price: float = float(order_book["bids"][0][0])
            b_safe_index: int = min(best_price_index, len(order_book["bids"]) - 1)
            b_target_price: float = float(order_book["bids"][b_safe_index][0])

            b_should_update: bool = (
                current_best_price is None  # No price yet
                or b_target_price > current_best_price  # More competitive price
                or current_best_price > max_price  # Current price no longer valid
            )

            if b_should_update:
                self.logger.debug(
                    f"{log_prefix} - best price: {b_target_price} using index {b_safe_index}, "
                    f"seconds_elapsed {elapsed_seconds:.2f}"
                )
                return OrderBookState(best_price=b_target_price, spread_pct=spread_pct)

        else:  # SELL
            min_price: float = float(order_book["asks"][0][0])
            s_safe_index: int = min(best_price_index, len(order_book["asks"]) - 1)
            s_target_price: float = float(order_book["asks"][s_safe_index][0])

            s_should_update: bool = (
                current_best_price is None  # No price yet
                or s_target_price < current_best_price  # More competitive price
                or current_best_price < min_price  # Current price no longer valid
            )

            if s_should_update:
                self.logger.debug(
                    f"{log_prefix} - best price: {s_target_price} using index {s_safe_index}, "
                    f"seconds_elapsed {elapsed_seconds:.2f}"
                )
                return OrderBookState(best_price=s_target_price, spread_pct=spread_pct)

        return None

    def _emit(self, event: OrderEvent) -> None:
        """Emit event to bus if one is registered; silently skip otherwise."""
        if self.event_bus is not None:
            self.event_bus.emit(event)

    @beartype
    def _check_should_reprice(
        self,
        *,
        order_id: str,
        exchange_id: str,
        symbol: str,
        side: str,
        submit_time: datetime,
        old_price: Decimal,
        new_price: Decimal,
        elapsed_seconds: float,
    ) -> bool:
        """
        Consult the reprice policy and emit the appropriate event.

        Returns True if the cancel-and-replace should proceed (order_repriced emitted).
        Returns False if repricing is suppressed (order_reprice_suppressed DEBUG event emitted).
        """
        proceed = self.reprice_policy.should_reprice(old_price, new_price, elapsed_seconds)

        if proceed:
            self._emit(
                self._make_event(
                    order_id=order_id,
                    exchange_id=exchange_id,
                    symbol=symbol,
                    side=side,
                    state=OrderState.UPDATING_ORDER,
                    event_name="order_repriced",
                    submit_time=submit_time,
                    fill_price=new_price,
                    fill_qty=old_price,
                )
            )
        else:
            change_pct = abs(new_price - old_price) / old_price if old_price != Decimal("0") else Decimal("0")
            threshold_pct = self.config.min_reprice_threshold_pct
            self.logger.debug(
                "order_reprice_suppressed",
                order_id=order_id,
                symbol=symbol,
                change_pct=float(change_pct),
                threshold_pct=float(threshold_pct),
                old_price=float(old_price),
                new_price=float(new_price),
            )
            self._emit(
                self._make_event(
                    order_id=order_id,
                    exchange_id=exchange_id,
                    symbol=symbol,
                    side=side,
                    state=OrderState.MONITORING_ORDER,
                    event_name="order_reprice_suppressed",
                    submit_time=submit_time,
                    fill_price=new_price,
                    fill_qty=old_price,
                )
            )

        return proceed

    def _make_event(
        self,
        *,
        order_id: str,
        exchange_id: str,
        symbol: str,
        side: str,
        state: OrderState,
        event_name: str,
        submit_time: datetime,
        fill_price: Decimal | None = None,
        fill_qty: Decimal | None = None,
        latency_ms: int | None = None,
    ) -> OrderEvent:
        now_ms = int(datetime.now().timestamp() * 1000)
        computed_latency_ms = (
            latency_ms
            if latency_ms is not None
            else int((datetime.now() - submit_time).total_seconds() * 1000)
        )
        return OrderEvent(
            order_id=order_id,
            exchange_id=exchange_id,
            symbol=symbol,
            side=side,
            state=state,
            timestamp_ms=now_ms,
            event_name=event_name,
            latency_ms=computed_latency_ms,
            fill_price=fill_price,
            fill_qty=fill_qty,
        )

    @beartype
    async def execute_taker_fallback(
        self,
        exchange: Exchange,
        request: OrderRequest,
        reason: str,
    ) -> ExecutionReport | None:
        """
        Shared fallback: emit order_timeout_fallback event, place a REST market order,
        and return the ExecutionReport (or None if market order fails).

        Called from WS executor on OrderTimeoutError.
        """
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        exchange_id = str(exchange.api.id)
        submit_time = datetime.now()
        log_prefix_str = self.log_prefix(exchange, symbol_str, request.side)

        self._emit(
            self._make_event(
                order_id="unknown",
                exchange_id=exchange_id,
                symbol=symbol_str,
                side=side_ccxt,
                state=OrderState.TIMED_OUT,
                event_name="order_timeout_fallback",
                submit_time=submit_time,
            )
        )

        self.logger.info(f"{log_prefix_str} - timeout fallback to taker (reason={reason})")
        try:
            order_dict: dict[str, Any] = await exchange.api.create_market_order(
                symbol=symbol_str,
                side=side_ccxt,
                amount=float(request.amount),
                params=request.params,
            )
            return self._build_execution_report(order_dict, exchange_id, submit_time)
        except Exception as exc:
            self.logger.error(f"{log_prefix_str} - taker fallback failed: {exc}", exc_info=True)
            return None

    @beartype
    async def _cancel_pending_orders(
        self, exchange: Exchange, symbol: str, order_id: str | None = None
    ) -> None:
        """Cancel specific or all open orders for a symbol."""
        log_prefix: str = self.log_prefix(exchange, symbol)
        if order_id:
            try:
                await exchange.api.cancel_order(order_id, symbol)
            except Exception as e:
                self.logger.debug(f"{log_prefix} - failed to cancel order {order_id}: {e}")

        try:
            open_orders: list[dict[str, str]] = await exchange.api.fetch_open_orders(symbol)
            for open_order in open_orders:
                try:
                    await exchange.api.cancel_order(open_order["id"], symbol)
                except Exception as e:
                    self.logger.debug(f"{log_prefix} - failed to cancel open order: {e}")
        except Exception as e:
            self.logger.debug(f"{log_prefix} - failed to fetch open orders: {e}")
