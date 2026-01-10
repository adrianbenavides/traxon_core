from decimal import Decimal

from beartype import beartype

from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.market_info import MarketInfo

from .builder import OrderBuilder
from .exceptions import OrderValidationError
from .execution_type import OrderExecutionType
from .order_type import OrderType
from .request import OrderRequest
from .side import OrderSide


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
        market: MarketInfo,
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
    def build(self, current_price: Decimal | None = None) -> OrderRequest:
        """
        Builds an OrderRequest from the builder.
        """
        self.validate()
        order_type = OrderType.LIMIT if self.execution_type == OrderExecutionType.MAKER else OrderType.MARKET
        return OrderRequest(
            symbol=self.market.symbol.raw_symbol,
            side=self.side,
            order_type=order_type,
            amount=self.size(),
            price=current_price if order_type == OrderType.LIMIT else None,
            execution_type=self.execution_type,
            exchange_id=self.exchange_id,
            pairing=self.pairing,
            notes=self.notes,
        )

    @beartype
    def validate(self) -> None:
        """
        Validates the order parameters and raises OrderValidationError if invalid.
        """
        min_size = self.min_size()
        if min_size is not None and self._size is not None:
            if self._size < min_size:
                raise OrderValidationError(
                    self.market.symbol.raw_symbol,
                    f"minimum size not met (got {self._size:.4f}, min {min_size:.4f})",
                )
