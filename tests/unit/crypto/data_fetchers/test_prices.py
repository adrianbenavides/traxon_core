from decimal import Decimal

import pytest

from traxon_core.crypto.domain.models import ExchangeId, Symbol
from traxon_core.crypto.domain.models.price import Prices


def test_prices_lookup():
    prices_data = {
        ExchangeId.BYBIT: {Symbol("BTC/USDT"): Decimal("50000"), Symbol("ETH/USDT"): Decimal("3000")},
        ExchangeId.HYPERLIQUID: {Symbol("BTC/USDT:USDT"): Decimal("50005")},
    }

    prices = Prices(results=prices_data, timestamp=123456789)

    # Test get()
    assert prices.get(ExchangeId.BYBIT, Symbol("BTC/USDT")) == Decimal("50000")
    assert prices.get(ExchangeId.HYPERLIQUID, Symbol("BTC/USDT:USDT")) == Decimal("50005")
    assert prices.get(ExchangeId.BYBIT, Symbol("XRP/USDT")) == Decimal(0)
    assert prices.get(ExchangeId.BINANCE, Symbol("BTC/USDT")) == Decimal(0)

    # Test get_by_exchange()
    assert prices.get_by_exchange(ExchangeId.BYBIT) == {
        Symbol("BTC/USDT"): Decimal("50000"),
        Symbol("ETH/USDT"): Decimal("3000"),
    }
    assert prices.get_by_exchange(ExchangeId.BINANCE) == {}


@pytest.mark.asyncio
async def test_price_fetcher_fetch_price():
    from unittest.mock import AsyncMock, MagicMock

    from traxon_core.crypto.data_fetchers.prices import PriceFetcher
    from traxon_core.crypto.exchanges.exchange import Exchange

    exchange = MagicMock(spec=Exchange)
    exchange.id = ExchangeId.BYBIT
    exchange.load_markets = AsyncMock(return_value={"BTC/USDT": {"symbol": "BTC/USDT"}})
    exchange.api = MagicMock()
    exchange.api.fetch_ticker = AsyncMock(return_value={"last": 50000.0, "timestamp": 123456789})

    fetcher = PriceFetcher()
    result = await fetcher.fetch_price(exchange, Symbol("BTC/USDT"))

    assert isinstance(result, Prices)
    assert result.get(ExchangeId.BYBIT, Symbol("BTC/USDT")) == Decimal("50000")
    assert result.timestamp == 123456789
