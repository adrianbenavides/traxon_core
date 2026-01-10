from enum import Enum


class OrderType(str, Enum):
    """Type of order to place."""

    LIMIT = "limit"
    MARKET = "market"
