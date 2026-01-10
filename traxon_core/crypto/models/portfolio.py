from dataclasses import dataclass

from beartype import beartype

from traxon_core.crypto.models.balance import Balance
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.position.position import Position


@beartype
@dataclass(frozen=True)
class Portfolio:
    """Represents a collection of spot balances and perp positions for a specific exchange."""

    exchange_id: ExchangeId
    balances: list[Balance]
    perps: list[Position]
