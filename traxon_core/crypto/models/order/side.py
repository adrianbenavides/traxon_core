from decimal import Decimal
from enum import Enum

from beartype import beartype
from ccxt.base.types import OrderSide as OrderSideCcxt  # type: ignore[import-untyped]


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @beartype
    def opposite(self) -> "OrderSide":
        return OrderSide.BUY if self == OrderSide.SELL else OrderSide.SELL

    @staticmethod
    @beartype
    def from_size(v: float | Decimal) -> "OrderSide":
        return OrderSide.BUY if v >= 0 else OrderSide.SELL

    @beartype
    def to_ccxt(self) -> OrderSideCcxt:
        return "buy" if self == OrderSide.BUY else "sell"
