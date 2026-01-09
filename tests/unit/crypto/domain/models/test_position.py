from datetime import datetime
from decimal import Decimal

import pytest

from traxon_core.crypto.domain.models.exchange_id import ExchangeId
from traxon_core.crypto.domain.models.position import Position, PositionSide, PositionType
from traxon_core.crypto.domain.models.symbol import Symbol


def test_position_type_enum():
    assert PositionType.SPOT.value == "spot"
    assert PositionType.PERP.value == "perp"


def test_unified_position_initialization():
    market = {"symbol": "BTC/USDT", "id": "BTCUSDT"}
    symbol = Symbol("BTC/USDT")
    pos = Position(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        symbol=symbol,
        type=PositionType.SPOT,
        side=PositionSide.LONG,
        size=Decimal("1.0"),
        contract_size=Decimal("1.0"),
        current_price=Decimal("50000.0"),
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
    )
    assert pos.type == PositionType.SPOT
    assert pos.size == Decimal("1.0")
    assert pos.current_price == Decimal("50000.0")
    assert pos.notional_size() == Decimal("1.0")
    assert pos.value() == Decimal("50000.0")
    assert pos.symbol == symbol


def test_perp_position_calculations():
    market = {"symbol": "BTC/USDT:USDT", "id": "BTCUSDT"}
    symbol = Symbol("BTC/USDT:USDT")
    pos = Position(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        symbol=symbol,
        type=PositionType.PERP,
        side=PositionSide.SHORT,
        size=Decimal("10"),
        contract_size=Decimal("0.1"),
        current_price=Decimal("50000.0"),
    )
    assert pos.notional_size() == Decimal("1.0")
    assert pos.value() == Decimal("50000.0")


def test_position_to_df_dict():
    market = {"symbol": "BTC/USDT", "id": "BTCUSDT"}
    symbol = Symbol("BTC/USDT")
    pos = Position(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        symbol=symbol,
        type=PositionType.SPOT,
        side=PositionSide.LONG,
        size=Decimal("1.0"),
        contract_size=Decimal("1.0"),
        current_price=Decimal("50000.0"),
    )
    df_dict = pos.to_df_dict()
    assert df_dict["symbol"] == "BTC/USDT@binance"
    assert df_dict["type"] == "spot"
    assert df_dict["side"] == "long"
    assert df_dict["size"] == Decimal("1.0")
    assert df_dict["price"] == Decimal("50000.0")
    assert df_dict["value"] == Decimal("50000.0")
    assert "created_at" in df_dict
    assert "updated_at" in df_dict


def test_position_from_spot():
    market = {"symbol": "BTC/USDT", "id": "BTCUSDT"}
    symbol = Symbol("BTC/USDT")
    pos = Position.from_spot(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        symbol=symbol,
        size=Decimal("1.5"),
        current_price=Decimal("50000.0"),
    )
    assert pos.type == PositionType.SPOT
    assert pos.size == Decimal("1.5")
    assert pos.contract_size == Decimal("1.0")
    assert pos.side == PositionSide.LONG
    assert pos.symbol == symbol


def test_position_from_perp():
    market = {"symbol": "BTC/USDT:USDT", "id": "BTCUSDT", "contractSize": 0.1}
    symbol = Symbol("BTC/USDT:USDT")
    ccxt_pos = {
        "contracts": 10.0,
        "side": "long",
        "datetime": "2024-01-01T00:00:00Z",
        "lastTradeDatetime": "2024-01-01T00:05:00Z",
    }
    pos = Position.from_perp(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        symbol=symbol,
        current_price=Decimal("50000.0"),
        ccxt_position=ccxt_pos,
    )
    assert pos.type == PositionType.PERP
    assert pos.size == Decimal("10")
    assert pos.contract_size == Decimal("0.1")
    assert pos.side == PositionSide.LONG
    assert pos.created_at is not None
    assert pos.symbol == symbol
