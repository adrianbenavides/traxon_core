from unittest.mock import AsyncMock, MagicMock

import pytest

from traxon_core.crypto.data_fetchers.portfolio import PortfolioFetcher
from traxon_core.crypto.data_fetchers.prices import PriceFetcher
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import ExchangeId, Portfolio


@pytest.mark.asyncio
async def test_fetch_portfolios():
    price_fetcher = MagicMock(spec=PriceFetcher)
    fetcher = PortfolioFetcher(price_fetcher)

    exchange = MagicMock(spec=Exchange)
    exchange.id = ExchangeId.BYBIT
    portfolio = Portfolio(exchange_id=ExchangeId.BYBIT, balances=[], perps=[])
    exchange.fetch_portfolio = AsyncMock(return_value=portfolio)

    results = await fetcher.fetch_portfolios([exchange])

    assert results == [portfolio]
    exchange.fetch_portfolio.assert_called_once()


@pytest.mark.asyncio
async def test_log_portfolios():
    price_fetcher = MagicMock(spec=PriceFetcher)
    fetcher = PortfolioFetcher(price_fetcher)

    portfolio = Portfolio(exchange_id=ExchangeId.BYBIT, balances=[], perps=[])

    # Just verify it doesn't crash
    await fetcher.log_portfolios([portfolio])
