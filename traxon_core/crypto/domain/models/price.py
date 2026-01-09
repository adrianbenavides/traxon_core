from __future__ import annotations

from decimal import Decimal
from typing import Dict

from pydantic import BaseModel, ConfigDict, Field

from traxon_core.crypto.domain.models import ExchangeId, Symbol


class Prices(BaseModel):
    """Aggregated price results across multiple exchanges."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    results: Dict[ExchangeId, Dict[Symbol, Decimal]]
    timestamp: int = Field(description="Fetch timestamp in milliseconds")

    def get(self, exchange_id: ExchangeId, symbol: Symbol) -> Decimal:
        """Get the price for a specific exchange and symbol. Returns 0 if not found."""
        return self.results.get(exchange_id, {}).get(symbol, Decimal(0))

    def get_by_exchange(self, exchange_id: ExchangeId) -> Dict[Symbol, Decimal]:
        """Get all prices for a specific exchange. Returns empty dict if not found."""
        return self.results.get(exchange_id, {})
