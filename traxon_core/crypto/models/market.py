from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from traxon_core.crypto.models.market_info import MarketInfo


class Market(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    info: MarketInfo
    avg_volume: Decimal
    close_prices: list[Decimal]
