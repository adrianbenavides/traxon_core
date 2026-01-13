from decimal import Decimal

from traxon_core.crypto.models.balance import Balance
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.market_info import MarketInfo
from traxon_core.crypto.models.portfolio import Portfolio
from traxon_core.crypto.models.position.position import Position
from traxon_core.crypto.models.symbol import Symbol


def test_portfolio_initialization():
    ccxt_market_btc = {
        "symbol": "BTC/USDT",
        "type": "spot",
        "active": True,
        "limits": {"amount": {"min": 0.001}},
        "precision": {"amount": 8, "price": 2},
    }
    market_btc = MarketInfo.from_ccxt(ccxt_market_btc)

    ccxt_market_eth = {
        "symbol": "ETH/USDT:USDT",
        "type": "swap",
        "active": True,
        "contractSize": 1,
        "limits": {"amount": {"min": 0.01}},
        "precision": {"amount": 3, "price": 2},
    }
    market_eth = MarketInfo.from_ccxt(ccxt_market_eth)

    balance = Balance(
        market=market_btc,
        exchange_id=ExchangeId.BYBIT,
        symbol=Symbol("BTC/USDT"),
        size=Decimal("1.0"),
        current_price=Decimal("50000"),
    )

    ccxt_pos = {
        "contracts": "0.5",
        "side": "long",
        "symbol": "ETH/USDT:USDT",
        "datetime": "2024-01-01T00:00:00Z",
    }
    position = Position(
        market=market_eth,
        exchange_id=ExchangeId.BYBIT,
        symbol=Symbol("ETH/USDT:USDT"),
        current_price=Decimal("3000"),
        ccxt_position=ccxt_pos,
    )

    portfolio = Portfolio(exchange_id=ExchangeId.BYBIT, balances=[balance], perps=[position])

    assert portfolio.exchange_id == ExchangeId.BYBIT
    assert portfolio.balances == [balance]
    assert portfolio.perps == [position]
