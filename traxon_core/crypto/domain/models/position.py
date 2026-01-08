from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from beartype import beartype
from ccxt.base.types import Market as CcxtMarket  # type: ignore[import-untyped]
from ccxt.base.types import Position as CcxtPosition

from .exchange_id import ExchangeId
from .order import OrderSide


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"

    @beartype
    def opposite(self) -> "PositionSide":
        return PositionSide.LONG if self == PositionSide.SHORT else PositionSide.SHORT

    @staticmethod
    @beartype
    def from_size(v: float | Decimal) -> "PositionSide":
        return PositionSide.LONG if v >= 0 else PositionSide.SHORT

    @beartype
    def to_order_side(self) -> OrderSide:
        if self == PositionSide.LONG:
            return OrderSide.BUY
        return OrderSide.SELL


@dataclass
class Position:
    """Represents a trading position."""

    market: CcxtMarket
    exchange_id: ExchangeId
    current_price: Decimal

    @beartype
    def side(self) -> PositionSide:
        raise NotImplementedError

    @beartype
    def size(self) -> Decimal:
        raise NotImplementedError

    @beartype
    def notional_size(self) -> Decimal:
        return self.size() * self.contract_size()

    @beartype
    def contract_size(self) -> Decimal:
        raise NotImplementedError

    @beartype
    def value(self) -> Decimal:
        return self.notional_size() * self.current_price

    @beartype
    def to_df_dict(self) -> dict[str, Any]:
        return {
            "symbol": f"{self.market['symbol']}@{self.exchange_id}",
            "price": self.current_price,
        }


@dataclass
class SpotPosition(Position):
    amount: Decimal

    @beartype
    def side(self) -> PositionSide:
        return PositionSide.LONG

    @beartype
    def size(self) -> Decimal:
        return self.amount

    @beartype
    def contract_size(self) -> Decimal:
        return Decimal("1")

    @beartype
    def to_df_dict(self) -> dict[str, Any]:
        return {
            **super().to_df_dict(),
            "side": self.side().value,
            "size": self.size(),
            "value": self.value(),
            "created_at": None,
            "updated_at": None,
        }


@dataclass
class PerpPosition(Position):
    inner: CcxtPosition

    @beartype
    def size(self) -> Decimal:
        return Decimal(str(self.inner.get("contracts", "0")))

    @beartype
    def contract_size(self) -> Decimal:
        return Decimal(str(self.inner.get("contractSize", "1")))

    @beartype
    def side(self) -> PositionSide:
        return PositionSide.LONG if self.inner["side"] == "long" else PositionSide.SHORT

    @beartype
    def to_df_dict(self) -> dict[str, Any]:
        return {
            **super().to_df_dict(),
            "side": self.side().value,
            "size": self.size(),
            "value": self.value(),
            "created_at": self.inner.get("datetime", None),
            "updated_at": self.inner.get("lastTradeDatetime", None),
        }
