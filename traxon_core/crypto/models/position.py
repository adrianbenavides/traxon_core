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


@dataclass(frozen=True, init=False)
class Position:
    """Represents a perpetual trading position."""

    market: CcxtMarket
    exchange_id: ExchangeId
    symbol: Symbol
    side: PositionSide
    size: Decimal
    contract_size: Decimal
    current_price: Decimal
    created_at: datetime | None
    updated_at: datetime | None
    notional_size: Decimal
    value: Decimal

    def __init__(
        self,
        market: CcxtMarket,
        exchange_id: ExchangeId,
        symbol: Symbol,
        current_price: Decimal,
        ccxt_position: CcxtPosition,
    ) -> None:
        """Initialize Position from CCXT data."""
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "exchange_id", exchange_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "current_price", current_price)

        # Parse CCXT position
        size = Decimal(str(ccxt_position.get("contracts", 0)))
        contract_size = Decimal(str(market.get("contractSize", 1)))
        side = PositionSide.LONG if ccxt_position.get("side") == "long" else PositionSide.SHORT
        created_at = to_datetime(ccxt_position.get("datetime", None))
        updated_at = to_datetime(ccxt_position.get("lastTradeDatetime", None))

        object.__setattr__(self, "size", size)
        object.__setattr__(self, "contract_size", contract_size)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)

        # Derived fields
        notional_size = size * contract_size
        object.__setattr__(self, "notional_size", notional_size)
        object.__setattr__(self, "value", notional_size * current_price)

    @beartype
    def to_df_dict(self) -> dict[str, Any]:
        return {
            "symbol": f"{self.market['symbol']}@{self.exchange_id.value}",
            "side": self.side.value,
            "size": self.size,
            "price": self.current_price,
            "value": self.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
