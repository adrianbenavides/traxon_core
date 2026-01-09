from __future__ import annotations

from enum import Enum

from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field


class OrderExecutionStrategy(str, Enum):
    BEST_PRICE = "best-price"  # Try to get a favorable price
    FAST = "fast"  # Aim for the closest price to the current market price


@beartype
class ExecutorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    execution: OrderExecutionStrategy
    max_spread_pct: float = Field(ge=0.0, le=1.0)
