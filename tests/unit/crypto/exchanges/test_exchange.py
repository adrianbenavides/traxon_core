import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ccxt.async_support import Exchange as CcxtExchange  # type: ignore[import-untyped]
from ccxt.base.types import Market as CcxtMarket  # type: ignore[import-untyped]
from ccxt.base.types import OpenInterest

from traxon_core.crypto.domain.models.account import AccountEquity
from traxon_core.crypto.domain.models.balance import Balance
from traxon_core.crypto.domain.models.exchange_id import ExchangeId
from traxon_core.crypto.domain.models.position import Position, PositionSide
from traxon_core.crypto.domain.models.symbol import Symbol
from traxon_core.crypto.exchanges.api_patch import BaseExchangeApiPatch
from traxon_core.crypto.exchanges.api_patch.bybit import BybitExchangeApiPatches
from traxon_core.crypto.exchanges.api_patch.hyperliquid import HyperliquidExchangeApiPatches
from traxon_core.crypto.exchanges.api_patch.kucoin import KucoinExchangeApiPatches
from traxon_core.crypto.exchanges.api_patch.paradex import ParadexExchangeApiPatches
from traxon_core.crypto.exchanges.api_patch.woofipro import WoofiProExchangeApiPatches
from traxon_core.crypto.exchanges.config import ExchangeConfig
from traxon_core.crypto.exchanges.exchange import Exchange, ExchangeFactory


@pytest.fixture
def mock_ccxt_exchange():
    api = MagicMock(spec=CcxtExchange)
    api.id = "binance"
    api.load_markets = AsyncMock(
        return_value={
            "BTC/USDT": {
                "symbol": "BTC/USDT",
                "id": "BTCUSDT",
                "type": "spot",
                "limits": {"amount": {"min": 0.001}, "cost": {"min": 5.0}},
            },
            "ETH/USDT": {
                "symbol": "ETH/USDT",
                "id": "ETHUSDT",
                "type": "spot",
                "limits": {"amount": {"min": 0.01}, "cost": {"min": 5.0}},
            },
            "BTC/USDT:USDT": {
                "symbol": "BTC/USDT:USDT",
                "id": "BTCUSDT_PERP",
                "type": "swap",
                "contractSize": 0.001,
                "limits": {"amount": {"min": 1}, "cost": {"min": 5.0}},
            },
            "ETH/USDT:USDT": {
                "symbol": "ETH/USDT:USDT",
                "id": "ETHUSDT_PERP",
                "type": "swap",
                "contractSize": 0.01,
                "limits": {"amount": {"min": 1}, "cost": {"min": 5.0}},
            },
        }
    )
    api.markets = api.load_markets.return_value
    api.milliseconds = MagicMock(return_value=1704067200000)
    api.iso8601 = MagicMock(side_effect=lambda x: "2024-01-01T00:00:00Z")
    api.has = {"fetchOpenInterest": True}
    api.fetch_balance = AsyncMock()
    api.fetch_tickers = AsyncMock()
    api.fetch_positions = AsyncMock()
    api.fetch_position = AsyncMock()
    api.fetch_ticker = AsyncMock()
    api.fetchPosition = api.fetch_position
    api.fetchPositions = api.fetch_positions
    api.close = AsyncMock()
    return api


@pytest.fixture
def mock_api_patch():
    patch = MagicMock()
    patch.filter_markets.side_effect = lambda x: {Symbol(k): v for k, v in x.items()}
    patch.filter_spot_balances.side_effect = lambda x: {Symbol("BTC/USDT"): Decimal("1.0")}
    return patch


@pytest.fixture
def exchange_config():
    return ExchangeConfig(
        exchange_id="binance",
        spot_quote_symbol="USDT",
        leverage=1,
        spot=True,
        perp=True,
        credentials={"apiKey": "test", "secret": "test"},
    )


@pytest.fixture
def exchange(mock_ccxt_exchange, mock_api_patch, exchange_config):
    return Exchange(mock_ccxt_exchange, mock_api_patch, exchange_config)


@pytest.mark.asyncio
async def test_exchange_id(exchange):
    assert exchange.id == ExchangeId.BINANCE


@pytest.mark.asyncio
async def test_fetch_balances(exchange, mock_ccxt_exchange):
    mock_ccxt_exchange.fetch_balance.return_value = {"total": {"BTC": 1.0}}
    mock_ccxt_exchange.fetch_tickers.return_value = {"BTC/USDT": {"last": 50000.0}}

    balances = await exchange.fetch_balances()
    assert len(balances) == 1
    bal = balances[0]
    assert isinstance(bal, Balance)
    assert bal.symbol == Symbol("BTC/USDT")
    assert bal.size == Decimal("1.0")
    assert bal.value == Decimal("50000.0")


@pytest.mark.asyncio
async def test_fetch_positions(exchange, mock_ccxt_exchange):
    ccxt_pos = {
        "symbol": "BTC/USDT:USDT",
        "contracts": 1000.0,
        "side": "long",
        "datetime": "2024-01-01T00:00:00Z",
    }
    mock_ccxt_exchange.fetch_positions.return_value = [ccxt_pos]
    mock_ccxt_exchange.fetch_ticker.return_value = {"last": 50000.0}
    exchange.api_patch.fetch_last_order_timestamp = AsyncMock(return_value=1704067200000)

    positions = await exchange.fetch_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert isinstance(pos, Position)
    assert pos.symbol == Symbol("BTC/USDT:USDT")
    assert pos.size == Decimal("1000.0")
    assert pos.notional_size == Decimal("1.0")


@pytest.mark.asyncio
async def test_exchange_close(exchange, mock_ccxt_exchange):
    await Exchange.close([exchange])
    mock_ccxt_exchange.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_available_equity_integrated(exchange, mock_ccxt_exchange):
    mock_ccxt_exchange.fetch_balance.return_value = {"total": {"USDT": 1000.0}}
    exchange.api_patch.extract_account_equity = MagicMock(
        return_value=AccountEquity(
            perps_equity=Decimal("1000.0"),
            spot_equity=Decimal("1000.0"),
            total_equity=Decimal("1000.0"),
            available_balance=Decimal("1000.0"),
            maintenance_margin=Decimal("0"),
            maintenance_margin_pct=Decimal("0"),
        )
    )

    equity = await exchange.fetch_available_equity_for_trading()
    assert equity == Decimal("1000.0")


@pytest.mark.asyncio
async def test_load_markets_retry(exchange, mock_ccxt_exchange):
    mock_ccxt_exchange.load_markets = AsyncMock(
        side_effect=[Exception("Fail"), Exception("Fail"), {"BTC/USDT": {}}]
    )
    with patch("asyncio.sleep", AsyncMock()):
        markets = await exchange.load_markets()
    assert mock_ccxt_exchange.load_markets.call_count == 3


@pytest.mark.asyncio
async def test_load_markets_filtered(exchange, mock_ccxt_exchange):
    mock_ccxt_exchange.load_markets.return_value = {"BTC/USDT": {"symbol": "BTC/USDT"}}
    exchange.api_patch.filter_markets = MagicMock(return_value={Symbol("BTC/USDT"): {"symbol": "BTC/USDT"}})

    markets = await exchange.load_markets()
    assert len(markets) == 1
    assert Symbol("BTC/USDT") in markets


def test_exchange_id_supported():
    assert ExchangeId.is_supported("binance")
    assert not ExchangeId.is_supported("invalid")


def test_base_api_patch_filter_markets(mock_ccxt_exchange, exchange_config):
    patch = BaseExchangeApiPatch(mock_ccxt_exchange, exchange_config)
    markets = {
        "BTC/USDT": {"symbol": "BTC/USDT", "type": "spot"},
        "ETH/BTC": {"symbol": "ETH/BTC", "type": "spot"},
        "BTC/USDT:USDT": {"symbol": "BTC/USDT:USDT", "type": "swap"},
    }
    filtered = patch.filter_markets(markets)
    assert Symbol("BTC/USDT") in filtered
    assert Symbol("ETH/BTC") not in filtered
    assert Symbol("BTC/USDT:USDT") in filtered


def test_base_api_patch_filter_spot_balances(mock_ccxt_exchange, exchange_config):
    patch = BaseExchangeApiPatch(mock_ccxt_exchange, exchange_config)
    balances = {"total": {"BTC": 1.0, "USDT": 100.0, "DUST": 0.000001}}
    filtered = patch.filter_spot_balances(balances)
    assert Symbol("BTC/USDT") in filtered
    assert Symbol("USDT/USDT") not in filtered
    assert Symbol("DUST/USDT") not in filtered


@pytest.mark.asyncio
async def test_base_api_patch_fetch_open_interest(mock_ccxt_exchange, exchange_config):
    patch = BaseExchangeApiPatch(mock_ccxt_exchange, exchange_config)
    mock_ccxt_exchange.has = {"fetchOpenInterest": True}
    mock_ccxt_exchange.fetch_open_interest = AsyncMock(
        return_value={
            "symbol": "BTC/USDT:USDT",
            "openInterestValue": 1000.0,
        }
    )

    oi = await patch.fetch_open_interest(Symbol("BTC/USDT:USDT"))
    assert oi is not None
    assert oi["openInterestValue"] == Decimal("1000.0")

    mock_ccxt_exchange.has = {"fetchOpenInterest": False}
    oi_none = await patch.fetch_open_interest(Symbol("BTC/USDT:USDT"))
    assert oi_none is not None
    assert oi_none["openInterestValue"] == Decimal(0)


def test_bybit_api_patch(mock_ccxt_exchange, exchange_config):
    patch = BybitExchangeApiPatches(mock_ccxt_exchange, exchange_config)
    balances = {
        "info": {
            "result": {
                "list": [
                    {
                        "totalEquity": "1000.0",
                        "totalMarginBalance": "900.0",
                        "totalMaintenanceMargin": "100.0",
                    }
                ]
            }
        }
    }
    equity = patch.extract_account_equity(balances)
    assert equity.total_equity == Decimal("1000.0")
    assert equity.available_balance == Decimal("900.0")


def test_hyperliquid_api_patch(mock_ccxt_exchange, exchange_config):
    patch = HyperliquidExchangeApiPatches(mock_ccxt_exchange, exchange_config)
    balances = {"info": {"marginSummary": {"accountValue": "1000.0"}}}
    equity = patch.extract_account_equity(balances)
    assert equity.perps_equity == Decimal("1000.0")


def test_kucoin_api_patch(mock_ccxt_exchange, exchange_config):
    patch = KucoinExchangeApiPatches(mock_ccxt_exchange, exchange_config)
    balances = {
        "USDT": {"total": 1000.0},
        "info": {"data": {"availableBalance": 900.0, "marginBalance": 950.0, "riskRatio": 0.1}},
    }
    equity = patch.extract_account_equity(balances)
    assert equity.total_equity == Decimal("1000.0")


def test_paradex_api_patch(mock_ccxt_exchange, exchange_config):
    patch = ParadexExchangeApiPatches(mock_ccxt_exchange, exchange_config)
    balances = {"total": {"USDC": 1000.0}}
    with pytest.raises(NotImplementedError):
        patch.extract_account_equity(balances)


def test_woofipro_api_patch(mock_ccxt_exchange, exchange_config):
    patch = WoofiProExchangeApiPatches(mock_ccxt_exchange, exchange_config)
    balances = {"total": {"USDC": 1000.0}}
    with pytest.raises(NotImplementedError):
        patch.extract_account_equity(balances)


@pytest.mark.asyncio
async def test_fetch_balances_filtering(exchange, mock_ccxt_exchange):
    mock_ccxt_exchange.fetch_balance.return_value = {"total": {"BTC": 1.0, "ETH": 0.0001, "SOL": 10.0}}
    mock_ccxt_exchange.fetch_tickers.return_value = {
        "BTC/USDT": {"last": 50000.0},
        "ETH/USDT": {"last": 2000.0},
    }
    # Override side_effect for this test
    exchange.api_patch.filter_spot_balances.side_effect = None
    exchange.api_patch.filter_spot_balances.return_value = {
        Symbol("BTC/USDT"): Decimal("1.0"),
        Symbol("ETH/USDT"): Decimal("0.0001"),
        Symbol("SOL/USDT"): Decimal("10.0"),
    }

    balances = await exchange.fetch_balances()
    symbols = [b.symbol for b in balances]
    assert Symbol("BTC/USDT") in symbols
    # ETH filtered by min cost (0.0001 * 2000 = 0.2 < 5.0)
    assert Symbol("ETH/USDT") not in symbols
    # SOL filtered because no ticker
    assert Symbol("SOL/USDT") not in symbols


@pytest.mark.asyncio
async def test_fetch_positions_filtered(exchange, mock_ccxt_exchange):
    ccxt_pos = [
        {"symbol": "BTC/USDT:USDT", "contracts": 1000.0, "side": "long", "datetime": "2024-01-01T00:00:00Z"},
        {"symbol": "ETH/USDT:USDT", "contracts": 10.0, "side": "long", "datetime": "2024-01-01T00:00:00Z"},
    ]
    mock_ccxt_exchange.fetch_positions.return_value = [ccxt_pos[0], ccxt_pos[1]]
    mock_ccxt_exchange.fetch_ticker.return_value = {"last": 50000.0}
    exchange.api_patch.fetch_last_order_timestamp = AsyncMock(return_value=None)

    positions = await exchange.fetch_positions(symbols=[Symbol("ETH/USDT:USDT")])
    assert len(positions) == 1
    assert positions[0].symbol == Symbol("ETH/USDT:USDT")


@pytest.mark.asyncio
async def test_fetch_portfolio(exchange, mock_ccxt_exchange):
    # Mock balances
    mock_ccxt_exchange.fetch_balance.return_value = {"total": {"BTC": 1.0}}
    mock_ccxt_exchange.fetch_tickers.return_value = {"BTC/USDT": {"last": 50000.0}}

    # Mock positions
    ccxt_pos = {
        "symbol": "BTC/USDT:USDT",
        "contracts": 1000.0,
        "side": "long",
        "datetime": "2024-01-01T00:00:00Z",
    }
    mock_ccxt_exchange.fetch_positions.return_value = [ccxt_pos]
    mock_ccxt_exchange.fetch_ticker.return_value = {"last": 50000.0}
    exchange.api_patch.fetch_last_order_timestamp = AsyncMock(return_value=None)

    from traxon_core.crypto.domain.models.portfolio import Portfolio

    portfolio = await exchange.fetch_portfolio()

    assert isinstance(portfolio, Portfolio)
    assert portfolio.exchange_id == ExchangeId.BINANCE
    assert len(portfolio.balances) == 1
    assert len(portfolio.perps) == 1
    assert portfolio.balances[0].symbol == Symbol("BTC/USDT")
    assert portfolio.perps[0].symbol == Symbol("BTC/USDT:USDT")


@pytest.mark.asyncio
async def test_exchange_factory_from_config(exchange_config):
    mock_api = MagicMock(spec=CcxtExchange)
    mock_api.id = "binance"
    mock_api.load_markets = AsyncMock()
    mock_api.check_required_credentials = MagicMock()
    mock_api.fetchPosition = AsyncMock()
    mock_api.fetchPositions = AsyncMock()

    with patch("ccxt.pro.binance", return_value=mock_api):
        exchanges = await ExchangeFactory.from_config(demo=False, exchanges_config=[exchange_config])
        assert len(exchanges) == 1
        assert exchanges[0].id == ExchangeId.BINANCE


@pytest.mark.asyncio
async def test_exchange_factory_from_config_retry(exchange_config):
    mock_api = MagicMock(spec=CcxtExchange)
    mock_api.id = "binance"
    mock_api.load_markets = AsyncMock()
    mock_api.load_markets.side_effect = [Exception("Fail"), {}]
    mock_api.check_required_credentials = MagicMock()
    mock_api.fetchPosition = AsyncMock()
    mock_api.fetchPositions = AsyncMock()

    with patch("ccxt.pro.binance", return_value=mock_api):
        with patch("asyncio.sleep", AsyncMock()):
            exchanges = await ExchangeFactory.from_config(demo=False, exchanges_config=[exchange_config])
            assert len(exchanges) == 1
            assert mock_api.load_markets.call_count == 2


@pytest.mark.asyncio
async def test_exchange_factory_invalid_exchange():
    config = ExchangeConfig(
        exchange_id="invalid", spot_quote_symbol="USDT", leverage=1, spot=True, perp=True, credentials={}
    )
    with pytest.raises(AttributeError):
        await ExchangeFactory.from_config(demo=False, exchanges_config=[config])


@pytest.mark.asyncio
async def test_fetch_balances_no_symbols(exchange, mock_ccxt_exchange):
    mock_ccxt_exchange.fetch_balance.return_value = {}
    exchange.api_patch.filter_spot_balances.side_effect = None
    exchange.api_patch.filter_spot_balances.return_value = {}

    balances = await exchange.fetch_balances()
    assert len(balances) == 0
