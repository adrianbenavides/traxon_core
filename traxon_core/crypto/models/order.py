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

from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.symbol import BaseQuote, Symbol
from traxon_core.logs.notifiers import notifier
from traxon_core.logs.structlog import logger


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
    success_event: asyncio.Event | None
    failure_event: asyncio.Event | None

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
        self.success_event = None
        self.failure_event = None

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
    def validate(self) -> str | None:
        """
        Validates the order parameters and returns an error message if any.
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

    # ==== Paired order methods

    @beartype
    def set_paired_events(self, success_event: asyncio.Event, failure_event: asyncio.Event) -> None:
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
            self.success_event.set()

    @beartype
    def notify_failed(self) -> None:
        """Signal that this order has failed execution."""
        if self.failure_event:
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
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            return False, False


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
    def validate(self) -> str | None:
        """
        Validates the order parameters and returns an error message if any.
        """
        min_size = self.min_size()
        if min_size is not None and self._size is not None:
            if self._size < min_size:
                return f"minimum size not met (got {self._size:.4f}, min {min_size:.4f})"
        return None

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
    def validate(self) -> str | None:
        """
        Validates the order parameters and returns an error message if any.
        """
        # Example: min_cost = 5 USDT; current_price = 2.000 XRP/USDT
        # min_cost_size = min_cost / current_price = 2.5 XRP
        min_cost = self.min_cost()
        if min_cost is not None:
            min_cost_size = min_cost / self.sizing_strategy.current_price / self.contract_size()
            size = self.size(self.sizing_strategy.current_price)
            if size is not None and size < min_cost_size:
                return (
                    f"minimum cost size not met (got {size:.4f}, "
                    f"min size {min_cost_size:.4f}, min cost {min_cost:.4f}, "
                    f"current price {self.sizing_strategy.current_price:.4f})"
                )
        return None

    @beartype
    def to_df_dict(self) -> dict[str, str | None]:
        data = super().to_df_dict()
        data["value"] = f"{self.value():.4f}" if self.value() else None
        data["notes"] = self.notes
        return data


class OrdersToExecute:
    """A list of orders to be executed. Updates will be handled first to free up capital for new orders."""

    updates: dict[BaseQuote, list[OrderBuilder]]
    new: dict[BaseQuote, list[OrderBuilder]]

    @beartype
    def __init__(
        self,
        updates: dict[BaseQuote, list[OrderBuilder]],
        new: dict[BaseQuote, list[OrderBuilder]],
    ) -> None:
        self.updates = updates
        self.new = new
        self.validate_orders()

    @beartype
    def count(self) -> int:
        return sum(len(orders) for orders in self.updates.values()) + sum(
            len(orders) for orders in self.new.values()
        )

    @staticmethod
    @beartype
    def _validate_min_size(order: OrderBuilder) -> bool:
        min_size = order.min_size()
        size = order.size()
        if min_size is not None and size is not None:
            if size < min_size:
                return False
        return True

    @staticmethod
    @beartype
    def _validate_min_cost(order: OrderBuilder) -> bool:
        if isinstance(order, DynamicSizeOrderBuilder):
            min_cost = order.min_cost()
            size = order.size()
            if min_cost is not None and size is not None:
                if size * order.sizing_strategy.current_price < min_cost:
                    return False
        return True

    @beartype
    def _validate_orders(
        self,
        orders_by_base_quote_symbol: dict[BaseQuote, list[OrderBuilder]],
        list_name: str = "orders",
    ) -> dict[BaseQuote, list[OrderBuilder]]:
        """
        Assumptions:
            - Funding rate orders comes in pairs, so we can group them by base/quote symbol
            - If one leg of the pair is invalid, both legs are removed
            - There can't be more than one order per base/quote symbol
        """
        base_quote_symbols_to_remove: dict[BaseQuote, list[str]] = defaultdict(list)

        for base_quote_symbol, orders in orders_by_base_quote_symbol.items():
            for order in orders:
                err_reason = order.validate()
                if err_reason:
                    base_quote_symbols_to_remove[base_quote_symbol].append(err_reason)

        valid_orders: dict[BaseQuote, list[OrderBuilder]] = defaultdict(list)
        for base_quote_symbol, orders in orders_by_base_quote_symbol.items():
            if base_quote_symbol in base_quote_symbols_to_remove:
                reasons = set(base_quote_symbols_to_remove[base_quote_symbol])
                reasons_str = ": " + ", ".join(reasons) if reasons else ""
                for order in orders:
                    symbol = Symbol.from_market(order.market)
                    logger.warning(f"{symbol} - removing from {list_name} orders{reasons_str}")
            else:
                valid_orders[base_quote_symbol] = orders

        return valid_orders

    @beartype
    def validate_orders(self) -> None:
        # First, validate orders individually using the existing method
        self.updates = self._validate_orders(self.updates, "updates")
        self.new = self._validate_orders(self.new, "new")

        # Remove duplicates between updates and new (prioritizing updates)
        duplicate_keys: set[str] = set()
        update_order_keys: set[str] = set()

        # Create a set of unique identifiers for orders in updates
        for _base_quote_symbol, orders in self.updates.items():
            for order in orders:
                # Create a unique key based on attributes that define unique orders
                key = f"{order.exchange_id}:{order.market}:{order.side}:{order.size()}"
                update_order_keys.add(key)

        # Remove any new orders that are duplicates of update orders
        cleaned_new: defaultdict[BaseQuote, list[OrderBuilder]] = defaultdict(list)
        for base_quote_symbol, orders in self.new.items():
            for order in orders:
                key = f"{order.exchange_id}:{order.market}:{order.side}:{order.size()}"
                if key in update_order_keys:
                    symbol = Symbol.from_market(order.market)
                    logger.warning(
                        f"{symbol} - removing duplicate order from 'new' (already exists in 'updates')"
                    )
                    duplicate_keys.add(key)
                else:
                    cleaned_new[base_quote_symbol].append(order)

        # Check for duplicates within the new orders
        seen_in_new: set[str] = set()
        for base_quote_symbol, orders in list(cleaned_new.items()):
            filtered_orders: list[OrderBuilder] = []
            for order in orders:
                key = f"{order.exchange_id}:{order.market}:{order.side}:{order.size()}"
                if key not in seen_in_new:
                    seen_in_new.add(key)
                    filtered_orders.append(order)
                else:
                    symbol = Symbol.from_market(order.market)
                    logger.warning(f"{symbol} - removing duplicate order within 'new'")

            if filtered_orders:
                cleaned_new[base_quote_symbol] = filtered_orders
            else:
                del cleaned_new[base_quote_symbol]

        self.new = dict(cleaned_new)

    @beartype
    def is_empty(self) -> bool:
        return not self.updates and not self.new

    @beartype
    async def log_as_df(self, context: str) -> None:
        if self.updates or self.new:
            logger.info(context)
            await notifier.notify(context)
        if self.updates:
            updates_df = pl.DataFrame(
                [order.to_df_dict() for orders in self.updates.values() for order in orders]
            ).sort("symbol")
            logger.info("update orders:", df=updates_df)
            await notifier.notify("new orders:")
            await notifier.notify(updates_df)
        if self.new:
            new_df = pl.DataFrame(
                [order.to_df_dict() for orders in self.new.values() for order in orders]
            ).sort("symbol")
            logger.info("new orders:", df=new_df)
            await notifier.notify("new orders:")
            await notifier.notify(new_df)
