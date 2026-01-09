"""
Order execution module with strict type safety and runtime validation.

Provides order executors for cryptocurrency exchanges with:
- REST API-based execution (polling)
- WebSocket-based execution (real-time)
- Generic executor that selects appropriate strategy

All components follow Rust-like safety principles with immutable models,
strict typing, and comprehensive error handling.
"""

from traxon_core.order_executor.base import OrderExecutor, OrderExecutorBase
from traxon_core.order_executor.default_executor import DefaultOrderExecutor
from traxon_core.order_executor.exceptions import (
    OrderBookError,
    OrderCancellationError,
    OrderCreationError,
    OrderExecutorError,
    OrderFetchError,
    OrderSizeCalculationError,
    OrderTimeoutError,
    OrderUpdateError,
    SpreadTooWideError,
    WebSocketNotSupportedError,
)
from traxon_core.order_executor.models import (
    ElapsedSeconds,
    ExecutionReport,
    OrderBookData,
    OrderBookDepthIndex,
    OrderBookLevel,
    OrderBookState,
    OrderId,
    OrderStatus,
    Price,
    SpreadPercent,
)
from traxon_core.order_executor.rest import RestApiOrderExecutor
from traxon_core.order_executor.ws import WebSocketOrderExecutor

__all__ = [
    # Base classes
    "OrderExecutorBase",
    "OrderExecutor",
    # Concrete implementations
    "RestApiOrderExecutor",
    "WebSocketOrderExecutor",
    "DefaultOrderExecutor",
    # Models
    "OrderBookState",
    "OrderBookData",
    "OrderBookLevel",
    "ExecutionReport",
    "OrderStatus",
    # Types
    "OrderId",
    "Price",
    "SpreadPercent",
    "ElapsedSeconds",
    "OrderBookDepthIndex",
    # Exceptions
    "OrderExecutorError",
    "OrderBookError",
    "SpreadTooWideError",
    "OrderCreationError",
    "OrderUpdateError",
    "OrderCancellationError",
    "OrderFetchError",
    "OrderTimeoutError",
    "OrderSizeCalculationError",
    "WebSocketNotSupportedError",
]
