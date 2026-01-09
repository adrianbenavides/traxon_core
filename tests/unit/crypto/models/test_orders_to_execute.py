from decimal import Decimal

import pytest

from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.order import (
    OrderBuilder,
    OrderExecutionType,
    OrderRequest,
    OrderSide,
    OrdersToExecute,
    SizedOrderBuilder,
)
from traxon_core.crypto.models.symbol import BaseQuote


@pytest.fixture
def market_btc():
    return {
        "symbol": "BTC/USDT",
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
    }


def test_orders_to_execute_builds_requests(market_btc):
    builder = SizedOrderBuilder(
        exchange_id=ExchangeId.BINANCE,
        market=market_btc,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )

    updates: dict[BaseQuote, list[OrderBuilder]] = {BaseQuote("BTC", "USDT"): [builder]}
    ote = OrdersToExecute(updates=updates, new={})

    assert len(ote.updates[BaseQuote("BTC", "USDT")]) == 1
    req = ote.updates[BaseQuote("BTC", "USDT")][0]
    assert isinstance(req, OrderRequest)
    assert req.amount == Decimal("0.1")


def test_orders_to_execute_filters_invalid(market_btc):
    valid_builder = SizedOrderBuilder(
        exchange_id=ExchangeId.BINANCE,
        market=market_btc,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )

    invalid_builder = SizedOrderBuilder(
        exchange_id=ExchangeId.BINANCE,
        market=market_btc,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=Decimal("0.0001"),  # Too small
    )

    # Removes ALL orders for a symbol if ANY are invalid
    updates: dict[BaseQuote, list[OrderBuilder]] = {
        BaseQuote("BTC", "USDT"): [valid_builder, invalid_builder]
    }
    ote = OrdersToExecute(updates=updates, new={})
    assert BaseQuote("BTC", "USDT") not in ote.updates
