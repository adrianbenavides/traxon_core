from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from traxon_core.crypto.data_fetchers.market import MarketFetcher
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import ExchangeId, Market, Symbol


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.load = AsyncMock(return_value=None)
    cache.save = AsyncMock()
    cache.delete = AsyncMock()
    cache.exists = MagicMock(return_value=False)
    return cache


@pytest.fixture
def mock_exchange():
    exchange = MagicMock(spec=Exchange)
    exchange.id = ExchangeId.BYBIT
    exchange.load_markets = AsyncMock(
        return_value={
            Symbol("BTC/USDT"): {"symbol": "BTC/USDT", "active": True},
            Symbol("ETH/USDT"): {"symbol": "ETH/USDT", "active": True},
        }
    )
    exchange.api = MagicMock()
    # Mock fetch_ohlcv: [timestamp, open, high, low, close, volume]
    # We need at least 20 days of data for avg_volume calculation
    ohlcv_data = [[i * 86400000, 100, 110, 90, 105, 10] for i in range(30)]
    exchange.api.fetch_ohlcv = AsyncMock(return_value=ohlcv_data)
    return exchange


@pytest.mark.asyncio
async def test_fetch_market_cache_miss(mock_cache, mock_exchange):
    fetcher = MarketFetcher(cache=mock_cache)
    exchange_id, markets = await fetcher._fetch_market(mock_exchange)

    assert exchange_id == ExchangeId.BYBIT
    assert len(markets) == 2
    assert isinstance(markets[0], Market)
    assert mock_cache.save.call_count == 2
    mock_exchange.api.fetch_ohlcv.assert_called()


@pytest.mark.asyncio
async def test_fetch_market_cache_hit(mock_cache, mock_exchange):
    market_obj = Market(
        inner={"symbol": "BTC/USDT", "active": True},
        avg_volume=Decimal("1000"),
        close_prices=[Decimal("100"), Decimal("101")],
    )
    mock_cache.load.return_value = market_obj

    fetcher = MarketFetcher(cache=mock_cache)
    exchange_id, markets = await fetcher._fetch_market(mock_exchange)

    assert exchange_id == ExchangeId.BYBIT
    assert len(markets) == 2
    assert markets[0] == market_obj
    mock_exchange.api.fetch_ohlcv.assert_not_called()


@pytest.mark.asyncio
async def test_get_markets_by_exchange(mock_cache, mock_exchange):
    fetcher = MarketFetcher(cache=mock_cache)
    results = await fetcher.get_markets_by_exchange([mock_exchange])

    assert ExchangeId.BYBIT in results
    assert len(results[ExchangeId.BYBIT]) == 2
