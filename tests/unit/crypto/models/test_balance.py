from dataclasses import FrozenInstanceError
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from ccxt.base.types import Market as CcxtMarket  # type: ignore[import-untyped]

from traxon_core.crypto.models.balance import Balance
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.symbol import Symbol


@pytest.fixture
def mock_market():
    return MagicMock(spec=dict)


def test_balance_initialization(mock_market):
    balance = Balance(
        market=mock_market,
        exchange_id=ExchangeId.BINANCE,
        symbol=Symbol("BTC/USDT"),
        size=Decimal("1.5"),
        current_price=Decimal("50000.00"),
    )

    assert balance.market == mock_market
    assert balance.exchange_id == ExchangeId.BINANCE
    assert balance.symbol == Symbol("BTC/USDT")
    assert balance.size == Decimal("1.5")
    assert balance.current_price == Decimal("50000.00")
    # Derived fields
    assert balance.notional_size == Decimal("1.5")
    assert balance.value == Decimal("75000.00")


def test_balance_frozen_immutability(mock_market):
    balance = Balance(
        market=mock_market,
        exchange_id=ExchangeId.BINANCE,
        symbol=Symbol("BTC/USDT"),
        size=Decimal("1.0"),
        current_price=Decimal("100.0"),
    )
    with pytest.raises(FrozenInstanceError):
        balance.size = Decimal("2.0")  # type: ignore[misc]


def test_balance_to_df_dict(mock_market):
    mock_market.__getitem__.side_effect = lambda k: "BTC/USDT" if k == "symbol" else None

    balance = Balance(
        market=mock_market,
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
