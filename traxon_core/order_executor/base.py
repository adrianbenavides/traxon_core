from __future__ import annotations

from abc import ABC
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from beartype import beartype

from traxon_core.crypto.domain.models import (
    OrderSide,
)
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.logs.structlog import logger
from traxon_core.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.order_executor.exceptions import (
    OrderCreationError,
    OrderFetchError,
    OrderTimeoutError,
    OrderUpdateError,
    OrderValidationError,
)
from traxon_core.order_executor.models import (
    ElapsedSeconds,
    ExecutionReport,
    OrderBookDepthIndex,
    OrderBookState,
    OrderRequest,
    OrderType,
    SpreadPercent,
)


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

    @beartype
    def __init__(self, config: ExecutorConfig) -> None:
        self.config = config
        self.execution = config.execution
        self.max_spread_pct = SpreadPercent(config.max_spread_pct)
        self.timeout_duration = timedelta(minutes=5)
        self.logger = logger.bind(component=self.__class__.__name__)

    @staticmethod
    @beartype
    def log_prefix(exchange: Exchange, symbol: str, side: OrderSide | None = None) -> str:
        exchange_id: str = exchange.id
        prefix: str = f"{symbol}@{exchange_id}"
        if side:
            prefix += f"_{side.to_ccxt()}"
        return prefix

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

        # Errors that are transient and worth retrying
        retriable_errors = (
            OrderFetchError,
            OrderUpdateError,
            OrderCreationError,
            # Add more specific network/exchange errors here if needed
        )

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
                # Don't raise - cancellation failures are often non-critical

        try:
            open_orders: list[dict[str, str]] = await exchange.api.fetch_open_orders(symbol)
            for open_order in open_orders:
                try:
                    await exchange.api.cancel_order(open_order["id"], symbol)
                except Exception as e:
                    self.logger.debug(f"{log_prefix} - failed to cancel open order: {e}")
                    # Don't raise - cancellation failures are often non-critical
        except Exception as e:
            self.logger.debug(f"{log_prefix} - failed to fetch open orders: {e}")
            # Don't raise - fetching open orders failure is non-critical
