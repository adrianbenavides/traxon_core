from decimal import Decimal

from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field, field_validator

from traxon_core.crypto.models.exchange_id import ExchangeId

from .execution_type import OrderExecutionType
from .order_type import OrderType
from .pairing import OrderPairing
from .side import OrderSide


class OrderRequest(BaseModel):
    """
    Request to place an order.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str = Field(min_length=1, description="Trading symbol (e.g. BTC/USDT)")
    side: OrderSide = Field(description="Order side (buy or sell)")
    order_type: OrderType = Field(description="Type of order (limit or market)")
    amount: Decimal = Field(gt=0, description="Amount to trade in base currency")
    price: Decimal | None = Field(
        default=None,
        description="Current price."
        "Used in maker limit orders with prices crossing the spread."
        "Otherwise, price is set automatically to the market price "
        "for market orders and limit orders within the spread.",
    )
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
