from __future__ import annotations

from enum import Enum


class ExchangeId(str, Enum):
    """
    Enum representing supported exchanges.
    """

    KUCOINFUTURES = "kucoinfutures"
    BYBIT = "bybit"
    HYPERLIQUID = "hyperliquid"
    BINANCE = "binance"

    @classmethod
    def is_supported(cls, exchange_id: str) -> bool:
        """Check if an exchange ID corresponds to a supported exchange."""
        try:
            cls(exchange_id)
            return True
        except ValueError:
            return False
