"""
Custom exception hierarchy for order executor operations.

Provides structured error handling with specific exception types for different
failure modes in order execution.
"""

from __future__ import annotations

from decimal import Decimal


class OrderExecutorError(Exception):
    """Base exception for all order executor errors."""

    pass


class OrderBookError(OrderExecutorError):
    """Raised when order book data is invalid or unavailable."""

    def __init__(self, symbol: str, reason: str) -> None:
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"Order book error for {symbol}: {reason}")


class SpreadTooWideError(OrderExecutorError):
    """Raised when market spread exceeds configured maximum."""

    def __init__(self, symbol: str, spread_pct: float, max_spread_pct: float) -> None:
        self.symbol = symbol
        self.spread_pct = spread_pct
        self.max_spread_pct = max_spread_pct
        super().__init__(f"Spread too wide for {symbol}: {spread_pct:.2%} > {max_spread_pct:.2%}")


class OrderCreationError(OrderExecutorError):
    """Raised when order creation fails on exchange."""

    def __init__(self, symbol: str, order_type: str, reason: str) -> None:
        self.symbol = symbol
        self.order_type = order_type
        self.reason = reason
        super().__init__(f"Failed to create {order_type} order for {symbol}: {reason}")


class OrderUpdateError(OrderExecutorError):
    """Raised when order update/edit fails on exchange."""

    def __init__(self, symbol: str, order_id: str, reason: str) -> None:
        self.symbol = symbol
        self.order_id = order_id
        self.reason = reason
        super().__init__(f"Failed to update order {order_id} for {symbol}: {reason}")


class OrderCancellationError(OrderExecutorError):
    """Raised when order cancellation fails on exchange."""

    def __init__(self, symbol: str, order_id: str, reason: str) -> None:
        self.symbol = symbol
        self.order_id = order_id
        self.reason = reason
        super().__init__(f"Failed to cancel order {order_id} for {symbol}: {reason}")


class OrderFetchError(OrderExecutorError):
    """Raised when fetching order status fails."""

    def __init__(self, symbol: str, order_id: str, reason: str) -> None:
        self.symbol = symbol
        self.order_id = order_id
        self.reason = reason
        super().__init__(f"Failed to fetch order {order_id} for {symbol}: {reason}")


class OrderTimeoutError(OrderExecutorError):
    """Raised when order execution exceeds timeout duration."""

    def __init__(self, symbol: str, order_type: str, timeout_seconds: float) -> None:
        self.symbol = symbol
        self.order_type = order_type
        self.timeout_seconds = timeout_seconds
        super().__init__(f"{order_type} order for {symbol} timed out after {timeout_seconds}s")


class OrderSizeCalculationError(OrderExecutorError):
    """Raised when order size cannot be calculated."""

    def __init__(self, symbol: str, price: Decimal, reason: str) -> None:
        self.symbol = symbol
        self.price = price
        self.reason = reason
        super().__init__(f"Failed to calculate order size for {symbol} at price {price}: {reason}")


class WebSocketNotSupportedError(OrderExecutorError):
    """Raised when WebSocket execution is attempted on unsupported exchange."""

    def __init__(self, exchange_id: str, missing_features: list[str]) -> None:
        self.exchange_id = exchange_id
        self.missing_features = missing_features
        super().__init__(
            f"Exchange {exchange_id} does not support required WebSocket features: {', '.join(missing_features)}"
        )
