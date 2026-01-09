import asyncio
from decimal import Decimal

import pytest

from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.order import (
    OrderExecutionType,
    OrderSide,
    OrderValidationError,
    SizedOrderBuilder,
)


@pytest.fixture
def market_btc():
    return {
        "symbol": "BTC/USDT",
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
    }


def test_sized_order_builder_pairing_composition(market_btc):
    builder = SizedOrderBuilder(
        exchange_id=ExchangeId.BINANCE,
        market=market_btc,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )

    assert builder.pairing.is_single()

    success_event = asyncio.Event()
    failure_event = asyncio.Event()
    builder.pairing.set_events(success_event, failure_event)

    assert not builder.pairing.is_single()

    builder.pairing.notify_filled()
    assert builder.pairing.is_pair_filled()
    assert success_event.is_set()


def test_sized_order_builder_validate_exception(market_btc):
    builder = SizedOrderBuilder(
        exchange_id=ExchangeId.BINANCE,
        market=market_btc,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=Decimal("0.0001"),  # Below min 0.001
    )

    with pytest.raises(OrderValidationError) as excinfo:
        builder.validate()
    assert "minimum size not met" in str(excinfo.value)


def test_sized_order_builder_build(market_btc):
    from traxon_core.crypto.models.order import OrderRequest

    builder = SizedOrderBuilder(
        exchange_id=ExchangeId.BINANCE,
        market=market_btc,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
        notes="test note",
    )

    request = builder.build()
    assert isinstance(request, OrderRequest)
    assert request.exchange_id == ExchangeId.BINANCE
    assert request.symbol == "BTC/USDT"
    assert request.side == OrderSide.BUY
    assert request.amount == Decimal("0.1")
    assert request.execution_type == OrderExecutionType.TAKER
    assert request.notes == "test note"
