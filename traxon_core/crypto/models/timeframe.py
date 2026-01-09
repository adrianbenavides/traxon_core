import math
from enum import Enum


class Timeframe(str, Enum):
    MINUTE = "1m"
    THREE_MINUTES = "3m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    HOUR = "1h"
    TWO_HOURS = "2h"
    FOUR_HOURS = "4h"
    SIX_HOURS = "6h"
    EIGHT_HOURS = "8h"
    TWELVE_HOURS = "12h"
    DAY = "1d"
    WEEK = "1w"
    MONTH = "1M"

    def __repr__(self) -> str:
        return self.value

    def to_hours(self) -> int:
        return math.floor(
            {
                Timeframe.MINUTE: 1 / 60,
                Timeframe.THREE_MINUTES: 3 / 60,
                Timeframe.FIVE_MINUTES: 5 / 60,
                Timeframe.FIFTEEN_MINUTES: 15 / 60,
                Timeframe.THIRTY_MINUTES: 30 / 60,
                Timeframe.HOUR: 1,
                Timeframe.TWO_HOURS: 2,
                Timeframe.FOUR_HOURS: 4,
                Timeframe.SIX_HOURS: 6,
                Timeframe.EIGHT_HOURS: 8,
                Timeframe.TWELVE_HOURS: 12,
                Timeframe.DAY: 24,
                Timeframe.WEEK: 24 * 7,
                Timeframe.MONTH: 24 * 30,
            }[self]
        )
