from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from beartype import beartype
from ccxt.base.types import Market as CcxtMarket  # type: ignore[import-untyped]

from .exchange_id import ExchangeId
from .symbol import Symbol


@dataclass(frozen=True, init=False)
class Balance:
    """Represents a spot balance (holding) of an asset."""

    market: CcxtMarket
    exchange_id: ExchangeId
    symbol: Symbol
    size: Decimal
    current_price: Decimal
    notional_size: Decimal
    value: Decimal

    def __init__(
        self,
        market: CcxtMarket,
        exchange_id: ExchangeId,
        symbol: Symbol,
        size: Decimal,
        current_price: Decimal,
    ) -> None:
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "exchange_id", exchange_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "current_price", current_price)

        # Derived fields
        object.__setattr__(self, "notional_size", size)
        object.__setattr__(self, "value", size * current_price)

    @beartype
    def to_df_dict(self) -> dict[str, Any]:
        """Convert to a dictionary suitable for DataFrame creation."""
        return {
            "symbol": f"{self.market['symbol']}@{self.exchange_id.value}",
            "size": self.size,
            "price": self.current_price,
            "value": self.value,
        }
