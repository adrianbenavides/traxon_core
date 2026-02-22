from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
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
    min_reprice_threshold_pct: Decimal = Decimal("0.0")
    reprice_override_after_seconds: float = 0.0
    timeout_duration: timedelta = Field(default=timedelta(minutes=5))
    ws_staleness_window_s: float = Field(default=30.0, ge=0.0)
    max_ws_reconnect_attempts: int = Field(default=5, ge=0)
    max_concurrent_orders_per_exchange: int = Field(default=10, ge=1)
