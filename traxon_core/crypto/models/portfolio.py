from __future__ import annotations

from dataclasses import dataclass

import pandera.polars as pa
from beartype import beartype
from pandera.typing.polars import Series

from traxon_core.crypto.models.balance import Balance
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.instrument import InstrumentType
from traxon_core.crypto.models.position.position import Position


class PortfolioSchema(pa.DataFrameModel):
    class Config:
        strict = True
        coerce = False

    symbol: Series[str]
    side: Series[str]
    price: Series[float]
    size: Series[float]
    notional_size: Series[float]
    value: Series[float]
    instrument: Series[str] = pa.Field(isin=InstrumentType)


@beartype
@dataclass(frozen=True)
class Portfolio:
    """Represents a collection of spot balances and perp positions for a specific exchange."""

    exchange_id: ExchangeId
    balances: list[Balance]
    perps: list[Position]
