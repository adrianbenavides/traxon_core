import polars as pl
from beartype import beartype

from traxon_core.crypto.data_fetchers.base import BaseFetcher
from traxon_core.crypto.data_fetchers.prices import PriceFetcher
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import (
    Portfolio,
)
from traxon_core.logs.notifiers import notifier


class PortfolioFetcher(BaseFetcher):
    """Handles fetching and organizing portfolio data (spot and perps)."""

    @beartype
    def __init__(self, price_fetcher: PriceFetcher) -> None:
        super().__init__()
        self.price_fetcher = price_fetcher

    @beartype
    async def fetch_portfolios(self, exchanges: list[Exchange]) -> list[Portfolio]:
        self.log_fetch_start(f"portfolios from {len(exchanges)} exchanges")

        portfolios: list[Portfolio] = []
        for exchange in exchanges:
            portfolio = await exchange.fetch_portfolio()
            portfolios.append(portfolio)

        self.log_fetch_end(f"portfolios from {len(exchanges)} exchanges", count=len(portfolios))

        return portfolios

    @beartype
    async def log_portfolios(
        self,
        portfolios: list[Portfolio],
        log_details: bool = True,
        log_value: bool = True,
    ) -> None:
        if not portfolios:
            return

        all_balances = [b for p in portfolios for b in p.balances]
        all_perps = [pos for p in portfolios for pos in p.perps]

        if log_details:
            if all_balances:
                balances_df = pl.DataFrame([b.to_df_dict() for b in all_balances]).sort("symbol")
                _log = "current spot balances:"
                self.logger.info(_log, df=balances_df)
                await notifier.notify(_log)
                await notifier.notify(balances_df)

            if all_perps:
                perps_df = pl.DataFrame([pos.to_df_dict() for pos in all_perps]).sort("symbol")
                _log = "current perp positions:"
                self.logger.info(_log, df=perps_df)
                await notifier.notify(_log)
                await notifier.notify(perps_df)

        if log_value:
            total_value = sum(b.value for b in all_balances) + sum(pos.value for pos in all_perps)
            _log = f"total portfolio value: {total_value:.2f}"
            self.logger.info(_log)
            await notifier.notify(_log)

            for p in portfolios:
                exchange_value = sum(b.value for b in p.balances) + sum(pos.value for pos in p.perps)
                _log = f"- {p.exchange_id}: {exchange_value:.2f}"
                self.logger.info(_log)
                await notifier.notify(_log)
