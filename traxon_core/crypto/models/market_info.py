from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from traxon_core.crypto.models.symbol import Symbol


class MarketInfo(BaseModel):
    """
    Normalized market metadata from CCXT.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: Symbol
    type: str
    active: bool
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    min_cost: Optional[Decimal] = None
    max_leverage: Optional[int] = None
    contract_size: Decimal = Field(default=Decimal("1"))
    precision_amount: Optional[int] = None
    precision_price: Optional[int] = None

    @classmethod
    def from_ccxt(cls, market: dict[str, Any]) -> MarketInfo:
        """
        Parses and normalizes a CCXT market dictionary.
        """
        limits = market.get("limits", {})
        amount_limits = limits.get("amount", {})
        cost_limits = limits.get("cost", {})
        leverage_limits = limits.get("leverage", {})
        precision = market.get("precision", {})

        return cls(
            symbol=Symbol(market["symbol"]),
            type=market.get("type", "unknown"),
            active=market.get("active", True),
            min_amount=cls._to_decimal(amount_limits.get("min")),
            max_amount=cls._to_decimal(amount_limits.get("max")),
            min_cost=cls._to_decimal(cost_limits.get("min")),
            max_leverage=cls._to_int(leverage_limits.get("max")),
            contract_size=cls._to_decimal(market.get("contractSize"), default=Decimal("1")),
            precision_amount=cls._to_int(precision.get("amount")),
            precision_price=cls._to_int(precision.get("price")),
        )

    @staticmethod
    def _to_decimal(v: Any, default: Decimal | None = None) -> Decimal | None:
        if v is None:
            return default
        try:
            return Decimal(str(v))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _to_int(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None
