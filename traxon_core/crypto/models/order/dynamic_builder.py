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
from .sizing import OrderSizingStrategy


class DynamicSizeOrderBuilder(OrderBuilder):
    sizing_strategy: OrderSizingStrategy

    @beartype
    def __init__(
        self,
        exchange_id: ExchangeId,
        market: MarketInfo,
        side: OrderSide,
        execution_type: OrderExecutionType,
        sizing_strategy: OrderSizingStrategy,
        value: Decimal | None = None,
        notes: str | None = None,
    ) -> None:
        super().__init__(exchange_id, market, execution_type, notes)
        self.side = side
        self.sizing_strategy = sizing_strategy
        self._value = abs(value) if value is not None else None

    @beartype
    def value(self) -> Decimal | None:
        return self._value

    @beartype
    def notional_size(self, current_price: Decimal | None = None) -> Decimal | None:
        price: Decimal = current_price or self.sizing_strategy.current_price
        if self._value is None or price is None:
            return None
        return self._value / price

    @beartype
    def size(self, current_price: Decimal | None = None) -> Decimal | None:
        notional_size = self.notional_size(current_price)
        if notional_size is None:
            return None
        return notional_size / self.contract_size()

    @beartype
    def build(self, current_price: Decimal | None = None) -> OrderRequest:
        """
        Builds an OrderRequest from the builder.
        """
        self.validate()
        price = current_price or self.sizing_strategy.current_price
        order_type = OrderType.LIMIT if self.execution_type == OrderExecutionType.MAKER else OrderType.MARKET
        return OrderRequest(
            symbol=self.market.symbol.raw_symbol,
            side=self.side,
            order_type=order_type,
            amount=self.size(price),
            price=price if order_type == OrderType.LIMIT else None,
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
        # Example: min_cost = 5 USDT; current_price = 2.000 XRP/USDT
        # min_cost_size = min_cost / current_price = 2.5 XRP
        min_cost = self.min_cost()
        if min_cost is not None:
            min_cost_size = min_cost / self.sizing_strategy.current_price / self.contract_size()
            size = self.size(self.sizing_strategy.current_price)
            if size is not None and size < min_cost_size:
                raise OrderValidationError(
                    self.market.symbol.raw_symbol,
                    (
                        f"minimum cost size not met (got {size:.4f}, "
                        f"min size {min_cost_size:.4f}, min cost {min_cost:.4f}, "
                        f"current price {self.sizing_strategy.current_price:.4f})"
                    ),
                )
