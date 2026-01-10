from abc import ABC, abstractmethod
from decimal import Decimal

from beartype import beartype

from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.market_info import MarketInfo

from .execution_type import OrderExecutionType
from .pairing import OrderPairing
from .request import OrderRequest
from .side import OrderSide


class OrderBuilder(ABC):
    exchange_id: ExchangeId
    market: MarketInfo
    execution_type: OrderExecutionType
    notes: str | None
    side: OrderSide | None
    _value: Decimal | None
    pairing: OrderPairing

    @beartype
    def __init__(
        self,
        exchange_id: ExchangeId,
        market: MarketInfo,
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
        return self.market.contract_size

    @beartype
    def min_size(self) -> Decimal | None:
        """
        Returns the minimum size for the order, in base currency (BTC or ETH).
        """
        return self.market.min_amount

    @beartype
    def min_cost(self) -> Decimal | None:
        """
        Returns the minimum size for the order, in quote currency (USDT or USDC).
        """
        return self.market.min_cost

    @beartype
    def max_leverage(self) -> int | None:
        """
        Returns the maximum leverage for the order, if applicable.
        """
        return self.market.max_leverage

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
            "symbol": f"{self.market.symbol.raw_symbol}@{self.exchange_id}",
            "side": self.side.value if self.side else None,
            "size": f"{self.size():.4f}" if self.size() is not None else None,
            "notional": f"{self.notional_size():.4f}" if self.notional_size() is not None else None,
        }
        return data
