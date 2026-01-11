from __future__ import annotations

from decimal import Decimal
from enum import Enum

from beartype import beartype

from traxon_core.crypto.models.order.side import OrderSide


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
    def to_order_side(self) -> "OrderSide":
        from traxon_core.crypto.models.order.side import OrderSide

        if self == PositionSide.LONG:
            return OrderSide.BUY
        return OrderSide.SELL
