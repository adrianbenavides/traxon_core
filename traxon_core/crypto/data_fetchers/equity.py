from decimal import Decimal

from beartype import beartype

from traxon_core.crypto.data_fetchers.base import BaseFetcher
from traxon_core.crypto.domain.models import AccountEquity, ExchangeId
from traxon_core.crypto.exchanges.exchange import Exchange


class EquityFetcher(BaseFetcher):
    """Handles fetching account equity data from exchanges."""

    def __init__(self) -> None:
        super().__init__()

    @beartype
    async def fetch_equities_for_trading(self, exchanges: list[Exchange]) -> dict[ExchangeId, Decimal]:
        self.log_fetch_start(f"trading equities for {len(exchanges)} exchanges")

        equities = {}
        for exchange in exchanges:
            equity = await exchange.fetch_available_equity_for_trading()
            equities[exchange.id] = equity

        self.log_fetch_end(f"trading equities for {len(exchanges)} exchanges", count=len(exchanges))
        return equities

    @beartype
    async def fetch_accounts_equity(self, exchanges: list[Exchange]) -> dict[ExchangeId, AccountEquity]:
        self.log_fetch_start(f"accounts equity for {len(exchanges)} exchanges")

        equities = {}
        for exchange in exchanges:
            account_equity = await exchange.fetch_account_equity()
            equities[exchange.id] = account_equity

        self.log_fetch_end(f"accounts equity for {len(exchanges)} exchanges", count=len(exchanges))
        return equities
