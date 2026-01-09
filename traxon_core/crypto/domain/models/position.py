from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from beartype import beartype
from ccxt.base.types import Market as CcxtMarket  # type: ignore[import-untyped]
from ccxt.base.types import Position as CcxtPosition

from traxon_core.dates import to_datetime

from .exchange_id import ExchangeId
from .order import OrderSide
from .symbol import Symbol


class PositionType(str, Enum):
    SPOT = "spot"
    PERP = "perp"


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


@dataclass(frozen=True)
class Position:
    """Represents a trading position."""

    market: CcxtMarket
    exchange_id: ExchangeId
    symbol: Symbol
    type: PositionType
    side: PositionSide
    size: Decimal
    contract_size: Decimal
    current_price: Decimal
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    @beartype
    def from_spot(
        cls,
        market: CcxtMarket,
        exchange_id: ExchangeId,
        symbol: Symbol,
        size: Decimal,
        current_price: Decimal,
    ) -> "Position":
        """Create a spot Position instance."""
        return cls(
            market=market,
            exchange_id=exchange_id,
            symbol=symbol,
            type=PositionType.SPOT,
            side=PositionSide.LONG,
            size=size,
            contract_size=Decimal("1"),
            current_price=current_price,
        )

    @classmethod
    @beartype
    def from_perp(
        cls,
        market: CcxtMarket,
        exchange_id: ExchangeId,
        symbol: Symbol,
        current_price: Decimal,
        ccxt_position: CcxtPosition,
    ) -> "Position":
        """Create a perp Position instance from a CCXT position dictionary."""
        size = Decimal(str(ccxt_position.get("contracts", 0)))
        contract_size = Decimal(str(market.get("contractSize", 1)))
        side = PositionSide.LONG if ccxt_position.get("side") == "long" else PositionSide.SHORT

        return cls(
            market=market,
            exchange_id=exchange_id,
            symbol=symbol,
            type=PositionType.PERP,
            side=side,
            size=size,
            contract_size=contract_size,
            current_price=current_price,
            created_at=to_datetime(ccxt_position.get("datetime", None)),
            updated_at=to_datetime(ccxt_position.get("lastTradeDatetime", None)),
        )

    @beartype
    def notional_size(self) -> Decimal:
        return self.size * self.contract_size

    @beartype
    def value(self) -> Decimal:
        return self.notional_size() * self.current_price

    @beartype
    def to_df_dict(self) -> dict[str, Any]:
        return {
            "symbol": f"{self.market['symbol']}@{self.exchange_id.value}",
            "type": self.type.value,
            "side": self.side.value,
            "size": self.size,
            "price": self.current_price,
            "value": self.value(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
