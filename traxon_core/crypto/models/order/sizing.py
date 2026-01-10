from decimal import Decimal

from beartype import beartype

from .sizing_type import OrderSizingStrategyType


class OrderSizingStrategy:
    @beartype
    def __init__(self, strategy_type: OrderSizingStrategyType, current_price: Decimal) -> None:
        self.strategy_type: OrderSizingStrategyType = strategy_type
        self.current_price: Decimal = current_price


class OrderSizingStrategyFixed(OrderSizingStrategy):
    @beartype
    def __init__(self, current_price: Decimal) -> None:
        super().__init__(OrderSizingStrategyType.FIXED, current_price)


class OrderSizingStrategyInverseVolatility(OrderSizingStrategy):
    @beartype
    def __init__(self, current_price: Decimal, carry_weight: Decimal, avg_volatility: Decimal) -> None:
        super().__init__(OrderSizingStrategyType.INVERSE_VOLATILITY, current_price)
        self.carry_weight: Decimal = carry_weight
        self.avg_volatility: Decimal = avg_volatility
