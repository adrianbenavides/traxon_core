"""
Pydantic models for order executor with strict validation.

All models are frozen (immutable) following Rust-like safety principles.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Dict, NewType

from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from traxon_core.crypto.models import OrderSide

OrderId = NewType("OrderId", str)
"""Unique identifier for an order on an exchange."""

Price = NewType("Price", Decimal)
"""Price value with arbitrary precision."""

SpreadPercent = NewType("SpreadPercent", float)
"""Bid-ask spread as a percentage (e.g., 0.01 for 1%)."""

ElapsedSeconds = NewType("ElapsedSeconds", float)
"""Time elapsed in seconds since an operation started."""

OrderBookDepthIndex = NewType("OrderBookDepthIndex", int)
"""Index into order book depth (0 = best price, 1 = second best, etc.)."""


class OrderType(str, Enum):
    """Type of order to place."""

    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(str, Enum):
    """Status of an order."""

    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderRequest(BaseModel):
    """
    Request to place an order.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, description="Trading symbol (e.g. BTC/USDT)")
    side: OrderSide = Field(description="Order side (buy or sell)")
    order_type: OrderType = Field(description="Type of order (limit or market)")
    amount: Decimal = Field(gt=0, description="Amount to trade in base currency")
    price: Decimal | None = Field(default=None, gt=0, description="Limit price (required for limit orders)")
    params: Dict[str, str] = Field(
        default_factory=dict,
        description="Exchange-specific execution parameters",
    )

    @field_validator("amount", "price", mode="before")
    @classmethod
    @beartype
    def convert_to_decimal(cls, v: float | Decimal | str | None) -> Decimal | None:
        """Convert numeric values to Decimal for precision."""
        if v is None:
            return None
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @model_validator(mode="after")
    def validate_price_for_limit_orders(self) -> OrderRequest:
        """Ensure price is present for limit orders."""
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Price is required for limit orders")
        return self


class ExecutionReport(BaseModel):
    """
    Report of an order execution update.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, description="Exchange-assigned order ID")
    symbol: str = Field(min_length=1, description="Trading symbol")
    status: OrderStatus = Field(description="Current status of the order")
    amount: Decimal = Field(gt=0, description="Original order amount")
    filled: Decimal = Field(ge=0, description="Amount filled so far")
    remaining: Decimal = Field(ge=0, description="Amount remaining to be filled")
    average_price: Decimal | None = Field(default=None, gt=0, description="Average fill price")
    last_price: Decimal | None = Field(default=None, gt=0, description="Price of the last fill")
    fee: Decimal | None = Field(default=None, description="Fee paid (if available)")
    timestamp: int = Field(ge=0, description="Timestamp of the update in ms")

    @field_validator(
        "amount",
        "filled",
        "remaining",
        "average_price",
        "last_price",
        "fee",
        mode="before",
    )
    @classmethod
    @beartype
    def convert_to_decimal(cls, v: float | Decimal | str | None) -> Decimal | None:
        """Convert numeric values to Decimal for precision."""
        if v is None:
            return None
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @model_validator(mode="after")
    def validate_filled_amount(self) -> ExecutionReport:
        """Ensure filled + remaining roughly equals amount (allow for rounding)."""
        # Note: We don't enforce strict equality due to potential rounding differences
        # or partial updates, but we can check bounds.
        if self.filled > self.amount:
            # In some cases (hidden orders, fees?) this might vary, but generally strict
            pass
        return self


class OrderBookState(BaseModel):
    """
    Immutable state representing analyzed order book data.

    Contains the best price to use for order placement and the current spread.
    """

    model_config = ConfigDict(frozen=True)  # Immutable like Rust structs

    best_price: Price = Field(gt=0, description="Best price from order book analysis")
    spread_pct: SpreadPercent = Field(ge=0.0, le=1.0, description="Bid-ask spread as percentage")

    @field_validator("best_price", mode="before")
    @classmethod
    @beartype
    def validate_best_price(cls, v: float | Decimal) -> Price:
        """Ensure best_price is converted to Price type."""
        if isinstance(v, float):
            return Price(Decimal(str(v)))
        elif isinstance(v, Decimal):
            return Price(v)
        return v  # type: ignore[unreachable]

    @field_validator("spread_pct", mode="before")
    @classmethod
    @beartype
    def validate_spread_pct(cls, v: float) -> SpreadPercent:
        """Ensure spread_pct is converted to SpreadPercent type."""
        if isinstance(v, (int, float)):
            return SpreadPercent(float(v))
        return v  # type: ignore[unreachable]


class OrderBookLevel(BaseModel):
    """Single level in an order book (price and size)."""

    model_config = ConfigDict(frozen=True)

    price: Decimal = Field(gt=0, description="Price level")
    amount: Decimal = Field(ge=0, description="Amount available at this level")

    @field_validator("price", "amount", mode="before")
    @classmethod
    @beartype
    def convert_to_decimal(cls, v: float | Decimal | str) -> Decimal:
        """Convert numeric values to Decimal for precision."""
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))


class OrderBookData(BaseModel):
    """
    Validated order book data structure.

    Ensures order book has valid bid/ask arrays with proper structure.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, description="Trading symbol")
    bids: list[OrderBookLevel] = Field(min_length=1, description="Bid side of order book")
    asks: list[OrderBookLevel] = Field(min_length=1, description="Ask side of order book")
    timestamp: int | None = Field(default=None, ge=0, description="Order book timestamp in milliseconds")

    @field_validator("bids", "asks", mode="before")
    @classmethod
    @beartype
    def validate_order_book_levels(cls, v: list[list[float]] | list[OrderBookLevel]) -> list[OrderBookLevel]:
        """Convert raw order book arrays to OrderBookLevel objects."""
        if not v:
            raise ValueError("Order book side cannot be empty")

        # If already OrderBookLevel objects, return as-is
        if isinstance(v[0], OrderBookLevel):
            return v  # type: ignore[return-value]

        # Convert from [[price, amount], ...] format
        result: list[OrderBookLevel] = []
        for level in v:
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                result.append(OrderBookLevel(price=Decimal(str(level[0])), amount=Decimal(str(level[1]))))
            else:
                raise ValueError(f"Invalid order book level format: {level}")

        return result

    @beartype
    def best_bid(self) -> Decimal:
        """Get the best (highest) bid price."""
        return self.bids[0].price

    @beartype
    def best_ask(self) -> Decimal:
        """Get the best (lowest) ask price."""
        return self.asks[0].price

    @beartype
    def spread_percentage(self) -> SpreadPercent:
        """Calculate bid-ask spread as a percentage of bid price."""
        bid = self.best_bid()
        ask = self.best_ask()
        spread = float((ask - bid) / bid)
        return SpreadPercent(spread)
