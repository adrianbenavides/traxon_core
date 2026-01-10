from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from traxon_core.crypto.models.balance import Balance
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.market_info import MarketInfo
from traxon_core.crypto.models.symbol import Symbol


@pytest.fixture
def btc_market():
    ccxt_market = {
        "symbol": "BTC/USDT",
        "type": "spot",
        "active": True,
        "limits": {"amount": {"min": 0.001}},
        "precision": {"amount": 8, "price": 2},
    }
    return MarketInfo.from_ccxt(ccxt_market)


def test_balance_initialization(btc_market):
    balance = Balance(
        market=btc_market,
        exchange_id=ExchangeId.BINANCE,
        symbol=Symbol("BTC/USDT"),
        size=Decimal("1.5"),
        current_price=Decimal("50000.00"),
    )

    assert balance.market == btc_market
    assert balance.exchange_id == ExchangeId.BINANCE
    assert balance.symbol == Symbol("BTC/USDT")
    assert balance.size == Decimal("1.5")
    assert balance.current_price == Decimal("50000.00")
    # Derived fields
    assert balance.notional_size == Decimal("1.5")
    assert balance.value == Decimal("75000.00")


def test_balance_frozen_immutability(btc_market):
    balance = Balance(
        market=btc_market,
        exchange_id=ExchangeId.BINANCE,
        symbol=Symbol("BTC/USDT"),
        size=Decimal("1.0"),
        current_price=Decimal("100.0"),
    )
    with pytest.raises(FrozenInstanceError):
        balance.size = Decimal("2.0")  # type: ignore[misc]


def test_balance_to_df_dict(btc_market):
    balance = Balance(
        market=btc_market,
        exchange_id=ExchangeId.BINANCE,
        symbol=Symbol("BTC/USDT"),
        size=Decimal("2.0"),
        current_price=Decimal("30000.00"),
    )

    df_dict = balance.to_df_dict()
    assert df_dict["symbol"] == "BTC/USDT@binance"
    assert df_dict["size"] == Decimal("2.0")
    assert df_dict["price"] == Decimal("30000.00")
    assert df_dict["value"] == Decimal("60000.00")
