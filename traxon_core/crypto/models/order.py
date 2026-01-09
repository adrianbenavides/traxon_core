from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, cast

import polars as pl
from beartype import beartype
from ccxt.base.types import Market  # type: ignore[import-untyped]
from ccxt.base.types import OrderSide as OrderSideCcxt
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.symbol import BaseQuote
from traxon_core.logs.notifiers import notifier
from traxon_core.logs.structlog import logger


class OrderType(str, Enum):
    """Type of order to place."""

    LIMIT = "limit"
    MARKET = "market"


class OrderPairing:
    """Handles logic for paired orders via composition."""

    success_event: asyncio.Event | None
    failure_event: asyncio.Event | None

    @beartype
    def __init__(self) -> None:
        self.success_event = None
        self.failure_event = None

    @beartype
    def set_events(self, success_event: asyncio.Event, failure_event: asyncio.Event) -> None:
        self.success_event = success_event
        self.failure_event = failure_event

    @beartype
    def is_single(self) -> bool:
        """Check if this order is a single order (not paired)."""
        return self.success_event is None and self.failure_event is None

    @beartype
    def notify_filled(self) -> None:
        """Signal that this order has been filled."""
        if self.success_event:
            logger.info("paired order filled - notifying")
            self.success_event.set()

    @beartype
    def notify_failed(self) -> None:
        """Signal that this order has failed execution."""
        if self.failure_event:
            logger.info("paired order failed - notifying")
            self.failure_event.set()

    @beartype
    def is_pair_filled(self) -> bool:
        """Check if the paired order has been filled."""
        return self.success_event.is_set() if self.success_event else False

    @beartype
    def is_pair_failed(self) -> bool:
        """Check if the paired order has failed."""
        return self.failure_event.is_set() if self.failure_event else False

    @beartype
    async def wait_for_pair(self, timeout: timedelta | None = None) -> tuple[bool, bool]:
        """
        Wait for the paired order to be filled or failed.
        Returns: (success, failure) tuple of booleans
        """
        if not self.success_event and not self.failure_event:
            return False, False

        tasks: list[asyncio.Task[Any]] = []
        if self.success_event:
            tasks.append(asyncio.create_task(self.success_event.wait()))
        if self.failure_event:
            tasks.append(asyncio.create_task(self.failure_event.wait()))

        try:
            if timeout:
                done, pending = await asyncio.wait(
                    tasks,
                    timeout=timeout.total_seconds(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
            else:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
            return self.is_pair_filled(), self.is_pair_failed()
        except Exception as e:
            logger.error(f"error waiting for paired order: {e}")
            for task in tasks:
                if not task.done():
                    task.cancel()
            return False, False


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @beartype
    def opposite(self) -> OrderSide:
        return OrderSide.BUY if self == OrderSide.SELL else OrderSide.SELL

    @staticmethod
    @beartype
    def from_size(v: float | Decimal) -> OrderSide:
        return OrderSide.BUY if v >= 0 else OrderSide.SELL

    @beartype
    def to_ccxt(self) -> OrderSideCcxt:
        return "buy" if self == OrderSide.BUY else "sell"


class OrderExecutionType(str, Enum):
    TAKER = "taker"
    MAKER = "maker"


class OrderRequest(BaseModel):
    """
    Request to place an order.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str = Field(min_length=1, description="Trading symbol (e.g. BTC/USDT)")
    side: OrderSide = Field(description="Order side (buy or sell)")
    order_type: OrderType = Field(description="Type of order (limit or market)")
    amount: Decimal = Field(gt=0, description="Amount to trade in base currency")
    price: Decimal | None = Field(default=None, description="Limit price (required for limit orders)")
    execution_type: OrderExecutionType = Field(description="Execution type (taker or maker)")
    params: dict[str, str] = Field(
        default_factory=dict,
        description="Exchange-specific execution parameters",
    )
    exchange_id: ExchangeId = Field(description="Exchange identifier")
    pairing: OrderPairing = Field(default_factory=OrderPairing, description="Pairing logic")
    notes: str | None = Field(default=None, description="Internal notes")

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


class OrderValidationError(Exception):
    """Raised when order validation fails before execution."""

    def __init__(self, symbol: str, reason: str) -> None:
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"Order validation failed for {symbol}: {reason}")


class OrderSizingType(str, Enum):
    FULL = "full"
    DYNAMIC = "dynamic"


class OrderSizingStrategyType(str, Enum):
    FIXED = "fixed"
    INVERSE_VOLATILITY = "inverse_volatility"


class OrderSizingStrategy:
    @beartype
    def __init__(self, strategy_type: OrderSizingStrategyType, current_price: Decimal) -> None:
        self.strategy_type: OrderSizingStrategyType = strategy_type
        self.current_price: Decimal = current_price


class OrderSizingStrategyFixed(OrderSizingStrategy):
    @beartype
    def __init__(self, current_price: Decimal) -> None:
        super().__init__(OrderSizingStrategyType.FIXED, current_price)


class OrderSizingStrategyInverseVolatility(OrderSizingStrategy):
    @beartype
    def __init__(self, current_price: Decimal, carry_weight: Decimal, avg_volatility: Decimal) -> None:
        super().__init__(OrderSizingStrategyType.INVERSE_VOLATILITY, current_price)
        self.carry_weight: Decimal = carry_weight
        self.avg_volatility: Decimal = avg_volatility


class OrderBuilder(ABC):
    exchange_id: ExchangeId
    market: Market
    execution_type: OrderExecutionType
    notes: str | None
    side: OrderSide | None
    _value: Decimal | None
    pairing: OrderPairing

    @beartype
    def __init__(
        self,
        exchange_id: ExchangeId,
        market: Market,
        execution_type: OrderExecutionType,
        notes: str | None = None,
    ) -> None:
        self.exchange_id = exchange_id
        self.market = market
        self.execution_type = execution_type
        self.notes = notes
        self.side = None
        self._value = None
        self.pairing = OrderPairing()

    @abstractmethod
    @beartype
    def notional_size(self, current_price: Decimal | None = None) -> Decimal | None: ...

    @abstractmethod
    @beartype
    def size(self, current_price: Decimal | None = None) -> Decimal | None: ...

    @abstractmethod
    @beartype
    def value(self) -> Decimal | None: ...

    @beartype
    def set_value(self, value: Decimal) -> None:
        self._value = abs(value)

    @beartype
    def contract_size(self) -> Decimal:
        v: float | None = cast(float | None, self.market.get("contractSize", 1.0))
        if v is not None:
            return Decimal(str(v))
        else:
            return Decimal("1.0")

    @beartype
    def min_size(self) -> Decimal | None:
        """
        Returns the minimum size for the order, in base currency (BTC or ETH).
        """
        v: Any = self.market["limits"]["amount"]["min"]
        if v:
            return Decimal(str(v))
        else:
            return None

    @beartype
    def min_cost(self) -> Decimal | None:
        """
        Returns the minimum size for the order, in quote currency (USDT or USDC).
        """
        v: Any = self.market["limits"]["cost"]["min"]
        if v:
            return Decimal(str(v))
        else:
            return None

    @beartype
    def max_leverage(self) -> int | None:
        """
        Returns the maximum leverage for the order, if applicable.
        """
        v: Any = self.market.get("limits", {}).get("leverage", {}).get("max")
        if v is not None:
            return int(v)
        else:
            return None

    @abstractmethod
    @beartype
    def build(self, current_price: Decimal | None = None) -> OrderRequest:
        """
        Builds an OrderRequest from the builder.
        """
        ...

    @abstractmethod
    @beartype
    def validate(self) -> None:
        """
        Validates the order parameters and raises OrderValidationError if invalid.
        """
        ...

    @beartype
    def to_df_dict(self) -> dict[str, str | None]:
        data: dict[str, str | None] = {
            "symbol": f"{self.market['symbol']}@{self.exchange_id}",
            "side": self.side.value if self.side else None,
            "size": f"{self.size():.4f}" if self.size() is not None else None,
            "notional": f"{self.notional_size():.4f}" if self.notional_size() is not None else None,
        }
        return data


class SizedOrderBuilder(OrderBuilder):
    # The size of the order in symbol units.
    # For futures/swap, this is the notional value. For spot, it's the same as the size.
    _notional_size: Decimal | None = None
    # The actual order size, considering contract size for futures/swap.
    _size: Decimal | None = None

    @beartype
    def __init__(
        self,
        exchange_id: ExchangeId,
        market: Market,
        execution_type: OrderExecutionType,
        side: OrderSide,
        size: Decimal,
        notes: str | None = None,
    ) -> None:
        super().__init__(exchange_id, market, execution_type, notes)
        self.side = side
        self.set_size(size)

    @beartype
    def set_notional_size(self, notional_size: Decimal) -> None:
        self._notional_size = abs(notional_size)
        self._size = self._notional_size / self.contract_size()

    @beartype
    def notional_size(self, current_price: Decimal | None = None) -> Decimal | None:
        return self._notional_size

    @beartype
    def value(self) -> Decimal | None:
        if self._notional_size is None:
            return None
        return self._notional_size * self.contract_size()

    @beartype
    def set_size(self, size: Decimal) -> None:
        self._size = abs(size)
        self._notional_size = self._size * self.contract_size()

    @beartype
    def size(self, current_price: Decimal | None = None) -> Decimal | None:
        return self._size

    @beartype
    def build(self, current_price: Decimal | None = None) -> OrderRequest:
        """
        Builds an OrderRequest from the builder.
        """
        self.validate()
        order_type = OrderType.LIMIT if self.execution_type == OrderExecutionType.MAKER else OrderType.MARKET
        return OrderRequest(
            symbol=self.market["symbol"],
            side=self.side,
            order_type=order_type,
            amount=self.size(),
            price=current_price if order_type == OrderType.LIMIT else None,
            execution_type=self.execution_type,
            exchange_id=self.exchange_id,
            pairing=self.pairing,
            notes=self.notes,
        )

    @beartype
    def validate(self) -> None:
        """
        Validates the order parameters and raises OrderValidationError if invalid.
        """
        min_size = self.min_size()
        if min_size is not None and self._size is not None:
            if self._size < min_size:
                raise OrderValidationError(
                    self.market["symbol"],
                    f"minimum size not met (got {self._size:.4f}, min {min_size:.4f})",
                )

    @beartype
    def to_df_dict(self) -> dict[str, str | None]:
        data = super().to_df_dict()
        data["notes"] = self.notes
        return data


class DynamicSizeOrderBuilder(OrderBuilder):
    sizing_strategy: OrderSizingStrategy

    @beartype
    def __init__(
        self,
        exchange_id: ExchangeId,
        market: Market,
        side: OrderSide,
        execution_type: OrderExecutionType,
        sizing_strategy: OrderSizingStrategy,
        value: Decimal | None = None,
        notes: str | None = None,
    ) -> None:
        super().__init__(exchange_id, market, execution_type, notes)
        self.side = side
        self.sizing_strategy = sizing_strategy
        self._value = abs(value) if value is not None else None

    @beartype
    def value(self) -> Decimal | None:
        return self._value

    @beartype
    def notional_size(self, current_price: Decimal | None = None) -> Decimal | None:
        price: Decimal = current_price or self.sizing_strategy.current_price
        if self._value is None or price is None:
            return None
        return self._value / price

    @beartype
    def size(self, current_price: Decimal | None = None) -> Decimal | None:
        notional_size = self.notional_size(current_price)
        if notional_size is None:
            return None
        return notional_size / self.contract_size()

    @beartype
    def build(self, current_price: Decimal | None = None) -> OrderRequest:
        """
        Builds an OrderRequest from the builder.
        """
        self.validate()
        price = current_price or self.sizing_strategy.current_price
        order_type = OrderType.LIMIT if self.execution_type == OrderExecutionType.MAKER else OrderType.MARKET
        return OrderRequest(
            symbol=self.market["symbol"],
            side=self.side,
            order_type=order_type,
            amount=self.size(price),
            price=price if order_type == OrderType.LIMIT else None,
            execution_type=self.execution_type,
            exchange_id=self.exchange_id,
            pairing=self.pairing,
            notes=self.notes,
        )

    @beartype
    def validate(self) -> None:
        """
        Validates the order parameters and raises OrderValidationError if invalid.
        """
        # Example: min_cost = 5 USDT; current_price = 2.000 XRP/USDT
        # min_cost_size = min_cost / current_price = 2.5 XRP
        min_cost = self.min_cost()
        if min_cost is not None:
            min_cost_size = min_cost / self.sizing_strategy.current_price / self.contract_size()
            size = self.size(self.sizing_strategy.current_price)
            if size is not None and size < min_cost_size:
                raise OrderValidationError(
                    self.market["symbol"],
                    (
                        f"minimum cost size not met (got {size:.4f}, "
                        f"min size {min_cost_size:.4f}, min cost {min_cost:.4f}, "
                        f"current price {self.sizing_strategy.current_price:.4f})"
                    ),
                )

    @beartype
    def to_df_dict(self) -> dict[str, str | None]:
        data = super().to_df_dict()
        data["value"] = f"{self.value():.4f}" if self.value() else None
        data["notes"] = self.notes
        return data


class OrdersToExecute:
    """
    A list of orders to be executed.

    Processing flow:
    1. Validates OrderBuilder objects and converts them to OrderRequest objects.
    2. Prioritizes 'updates' (existing position adjustments) over 'new' orders.
    3. Deduplicates 'new' orders against 'updates' to avoid redundant operations.
    """

    updates: dict[BaseQuote, list[OrderRequest]]
    new: dict[BaseQuote, list[OrderRequest]]

    @beartype
    def __init__(
        self,
        updates: dict[BaseQuote, list[OrderBuilder]],
        new: dict[BaseQuote, list[OrderBuilder]],
    ) -> None:
        self.updates = self._process_orders(updates, "updates")
        self.new = self._process_orders(new, "new")
        self._deduplicate_new_orders()

    @beartype
    def count(self) -> int:
        return sum(len(orders) for orders in self.updates.values()) + sum(
            len(orders) for orders in self.new.values()
        )

    @beartype
    def _process_orders(
        self,
        orders_by_base_quote: dict[BaseQuote, list[OrderBuilder]],
        list_name: str,
    ) -> dict[BaseQuote, list[OrderRequest]]:
        """
        Validates builders and converts them to requests.
        If any order in a group (list) fails validation, the entire group is dropped.
        """
        valid_requests: dict[BaseQuote, list[OrderRequest]] = defaultdict(list)

        for base_quote, builders in orders_by_base_quote.items():
            requests: list[OrderRequest] = []
            group_valid = True
            failure_reasons: list[str] = []

            for builder in builders:
                try:
                    request = builder.build()
                    requests.append(request)
                except OrderValidationError as e:
                    group_valid = False
                    failure_reasons.append(str(e))
                except Exception as e:
                    group_valid = False
                    failure_reasons.append(f"Unexpected error: {e}")

            if group_valid:
                valid_requests[base_quote] = requests
            else:
                symbol_str = f"{base_quote.base}/{base_quote.quote}"
                reasons_str = "; ".join(failure_reasons)
                logger.warning(
                    f"{symbol_str} - removing from {list_name} orders due to validation errors: {reasons_str}"
                )

        return dict(valid_requests)

    @beartype
    def _deduplicate_new_orders(self) -> None:
        """
        Removes orders from 'new' that are duplicates of 'updates' or internal duplicates.
        """
        # Create a set of unique identifiers for orders in updates
        update_keys: set[str] = set()
        for requests in self.updates.values():
            for req in requests:
                # Key based on exchange, symbol, side, amount
                key = f"{req.exchange_id}:{req.symbol}:{req.side}:{req.amount}"
                update_keys.add(key)

        cleaned_new: dict[BaseQuote, list[OrderRequest]] = defaultdict(list)

        for base_quote, requests in self.new.items():
            seen_in_group: set[str] = set()
            filtered_requests: list[OrderRequest] = []

            for req in requests:
                key = f"{req.exchange_id}:{req.symbol}:{req.side}:{req.amount}"

                if key in update_keys:
                    logger.warning(
                        f"{req.symbol} - removing duplicate order from 'new' (already exists in 'updates')"
                    )
                    continue

                if key in seen_in_group:
                    logger.warning(f"{req.symbol} - removing duplicate order within 'new'")
                    continue

                seen_in_group.add(key)
                filtered_requests.append(req)

            if filtered_requests:
                cleaned_new[base_quote] = filtered_requests

        self.new = dict(cleaned_new)

    @beartype
    def is_empty(self) -> bool:
        return not self.updates and not self.new

    @beartype
    async def log_as_df(self, context: str) -> None:
        if self.updates or self.new:
            logger.info(context)
            await notifier.notify(context)

        # Helper to convert OrderRequest to dict for DataFrame
        def req_to_dict(req: OrderRequest) -> dict[str, Any]:
            return {
                "symbol": f"{req.symbol}@{req.exchange_id}",
                "side": req.side.value,
                "amount": f"{req.amount:.4f}",
                "type": req.execution_type.value,
                "notes": req.notes,
            }

        if self.updates:
            updates_df = pl.DataFrame(
                [req_to_dict(req) for reqs in self.updates.values() for req in reqs]
            ).sort("symbol")
            logger.info("update orders:", df=updates_df)
            await notifier.notify("update orders:")
            await notifier.notify(updates_df)

        if self.new:
            new_df = pl.DataFrame([req_to_dict(req) for reqs in self.new.values() for req in reqs]).sort(
                "symbol"
            )
            logger.info("new orders:", df=new_df)
            await notifier.notify("new orders:")
            await notifier.notify(new_df)
