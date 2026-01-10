from decimal import Decimal

from traxon_core.crypto.models.market_info import MarketInfo
from traxon_core.crypto.models.symbol import Symbol


def test_market_info_from_ccxt_spot():
    ccxt_market = {
        "symbol": "BTC/USDT",
        "type": "spot",
        "active": True,
        "limits": {
            "amount": {"min": 0.001, "max": 100},
            "cost": {"min": 10},
        },
        "precision": {
            "amount": 8,
            "price": 2,
        },
    }

    market_info = MarketInfo.from_ccxt(ccxt_market)

    assert market_info.symbol == Symbol("BTC/USDT")
    assert market_info.type == "spot"
    assert market_info.active is True
    assert market_info.min_amount == Decimal("0.001")
    assert market_info.max_amount == Decimal("100")
    assert market_info.min_cost == Decimal("10")
    assert market_info.contract_size == Decimal("1")
    assert market_info.precision_amount == 8
    assert market_info.precision_price == 2


def test_market_info_from_ccxt_swap():
    ccxt_market = {
        "symbol": "BTC/USDT:USDT",
        "type": "swap",
        "active": True,
        "contractSize": 0.001,
        "limits": {
            "amount": {"min": 1, "max": 10000},
            "leverage": {"max": 100},
        },
        "precision": {
            "amount": 0,
            "price": 1,
        },
    }

    market_info = MarketInfo.from_ccxt(ccxt_market)

    assert market_info.symbol == Symbol("BTC/USDT:USDT")
    assert market_info.type == "swap"
    assert market_info.contract_size == Decimal("0.001")
    assert market_info.max_leverage == 100
