from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class Market(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: dict[str, Any]
    avg_volume: Decimal
    close_prices: list[Decimal]
