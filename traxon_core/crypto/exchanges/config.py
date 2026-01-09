from __future__ import annotations

from enum import Enum

from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field


class ExchangeApiConnection(str, Enum):
    REST = "rest"
    WEBSOCKET = "websocket"


@beartype
class ExchangeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    exchange_id: str = Field(min_length=1, max_length=32)
    api_connection: ExchangeApiConnection = ExchangeApiConnection.REST
    spot_quote_symbol: str
    leverage: int
    spot: bool
    perp: bool
    credentials: dict[str, str]  # key-value pairs of needed credentials (keys might vary per exchange)
