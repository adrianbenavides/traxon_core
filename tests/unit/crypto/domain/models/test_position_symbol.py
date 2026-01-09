from decimal import Decimal

import pytest

from traxon_core.crypto.domain.models.exchange_id import ExchangeId
from traxon_core.crypto.domain.models.position import Position, PositionSide, PositionType
from traxon_core.crypto.domain.models.symbol import Symbol


def test_position_has_symbol_field():
    market = {"symbol": "BTC/USDT", "id": "BTCUSDT"}
    symbol = Symbol("BTC/USDT")
    pos = Position(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        type=PositionType.SPOT,
        side=PositionSide.LONG,
        size=Decimal("1.0"),
        contract_size=Decimal("1.0"),
        current_price=Decimal("50000.0"),
        symbol=symbol,
    )
    assert pos.symbol == symbol


def test_position_from_spot_with_symbol():
    market = {"symbol": "BTC/USDT", "id": "BTCUSDT"}
    symbol = Symbol("BTC/USDT")
    pos = Position.from_spot(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        size=Decimal("1.5"),
        current_price=Decimal("50000.0"),
        symbol=symbol,
    )
    assert pos.symbol == symbol


def test_position_from_perp_with_symbol():
    market = {"symbol": "BTC/USDT:USDT", "id": "BTCUSDT", "contractSize": 0.1}
    symbol = Symbol("BTC/USDT:USDT")
    ccxt_pos = {
        "contracts": 10.0,
        "side": "long",
        "datetime": "2024-01-01T00:00:00Z",
    }
    pos = Position.from_perp(
        market=market,
        exchange_id=ExchangeId.BINANCE,
        current_price=Decimal("50000.0"),
        ccxt_position=ccxt_pos,
        symbol=symbol,
    )
    assert pos.symbol == symbol
