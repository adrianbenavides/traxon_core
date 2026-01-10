from enum import Enum


class OrderExecutionType(str, Enum):
    TAKER = "taker"
    MAKER = "maker"
