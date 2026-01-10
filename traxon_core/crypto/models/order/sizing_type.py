from enum import Enum


class OrderSizingType(str, Enum):
    FULL = "full"
    DYNAMIC = "dynamic"


class OrderSizingStrategyType(str, Enum):
    FIXED = "fixed"
    INVERSE_VOLATILITY = "inverse_volatility"
