from datetime import datetime, timezone
from decimal import Decimal

import pytest

from traxon_core.crypto.domain.models.exchange_id import ExchangeId
from traxon_core.crypto.domain.models.position import Position, PositionSide
from traxon_core.crypto.domain.models.symbol import Symbol


def test_position_initialization_parsing():
    market = {"symbol": "BTC/USDT:USDT", "id": "BTCUSDT", "contractSize": 0.1}
    symbol = Symbol("BTC/USDT:USDT")
    ccxt_pos = {
        "contracts": 10.0,
        "side": "short",
        "datetime": "2024-01-01T00:00:00Z",
        "lastTradeDatetime": "2024-01-01T00:05:00Z",
    }

    pos = Position(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        symbol=symbol,
        current_price=Decimal("50000.0"),
        ccxt_position=ccxt_pos,
    )

    assert pos.symbol == symbol
    assert pos.size == Decimal("10.0")
    assert pos.contract_size == Decimal("0.1")
    assert pos.side == PositionSide.SHORT
    assert pos.created_at == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert pos.updated_at == datetime(2024, 1, 1, 0, 5, 0, tzinfo=timezone.utc)

    # Derived
    assert pos.notional_size == Decimal("1.0")  # 10 * 0.1
    assert pos.value == Decimal("50000.0")  # 1.0 * 50000


def test_position_to_df_dict():
    market = {"symbol": "BTC/USDT:USDT", "id": "BTCUSDT", "contractSize": 0.1}
    symbol = Symbol("BTC/USDT:USDT")
    ccxt_pos = {
        "contracts": 10.0,
        "side": "short",
        "datetime": "2024-01-01T00:00:00Z",
    }
    pos = Position(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        symbol=symbol,
        current_price=Decimal("50000.0"),
        ccxt_position=ccxt_pos,
    )

    df_dict = pos.to_df_dict()
    assert df_dict["symbol"] == "BTC/USDT:USDT@binance"
    assert "type" not in df_dict
    assert df_dict["side"] == "short"
    assert df_dict["size"] == Decimal("10.0")
    assert df_dict["price"] == Decimal("50000.0")
    assert df_dict["value"] == Decimal("50000.0")
    assert df_dict["created_at"] is not None
