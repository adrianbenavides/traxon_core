"""
Step definitions for RestOrderExecutor acceptance tests.

Exercises RestOrderExecutor through the public driving port:
  DefaultOrderExecutor.execute_orders()

Covers adaptive polling intervals and params propagation.
The CCXT REST API is mocked via AsyncMock.
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import AsyncMock, call

import pytest
from pytest_bdd import given, parsers, then, when

from traxon_core.crypto.models import ExchangeId, OrderSide
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor

from .conftest import build_maker_order, build_taker_order, make_orders_to_execute

# ---------------------------------------------------------------------------
# Adaptive polling steps
# ---------------------------------------------------------------------------


@given("a maker order is placed on a REST exchange and monitored")
def maker_order_placed_rest(context, market_btc, mock_bybit_rest):
    """Set up a REST maker order with a mock that initially returns OPEN then CLOSED."""
    submit_ms = int(time.time() * 1000)

    open_order = {
        "id": "ord-rest-001",
        "symbol": "BTC/USDT",
        "status": "open",
        "amount": 0.1,
        "filled": 0.0,
        "remaining": 0.1,
        "average": None,
        "price": 43200.00,
        "fee": None,
        "timestamp": submit_ms,
        "info": {},
    }
    closed_order = {
        **open_order,
        "status": "closed",
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "fee": {"cost": 0.001, "currency": "USDT"},
        "timestamp": submit_ms + 500,
    }

    # First two fetch_order calls return open; third returns closed
    mock_bybit_rest.api.fetch_order = AsyncMock(side_effect=[open_order, open_order, closed_order])
    mock_bybit_rest.api.create_limit_order = AsyncMock(return_value=open_order)

    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["exchange"] = mock_bybit_rest
    context["submit_ms"] = submit_ms


@pytest.mark.skip(reason="pending implementation: RestOrderExecutor adaptive polling")
@when("the order is monitored in the first 10 seconds after placement")
async def order_monitored_first_10s(context, config_best_price):
    """Drive monitoring and capture fetch_order call timing."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports


@then("the REST executor polls at 200 millisecond intervals during the high-probability window")
def rest_polls_at_200ms(context):
    """
    Assert that fetch_order was called multiple times within the first 10 seconds.

    Full timing precision is not asserted here — that belongs in a unit test.
    This acceptance test verifies the polling happened frequently enough.
    """
    api = context["exchange"].api
    fetch_count = api.fetch_order.call_count
    assert fetch_count >= 2, f"Expected multiple fetch_order calls in first 10s, got {fetch_count}"


@then("the polling interval increases to 1 second after the high-probability window ends")
def polling_interval_increases(context):
    """
    Assert that after 10 seconds the polling frequency drops.

    This is validated structurally: the implementation is required by AC from US-03/REST.
    Full timing assertion lives in unit tests with time mocking.
    """
    # Observable outcome: the order still fills successfully with slower polling
    from traxon_core.crypto.order_executor.models import OrderStatus

    reports = context["reports"]
    assert len(reports) >= 1
    assert reports[0].status == OrderStatus.CLOSED


# ---------------------------------------------------------------------------
# Params propagation steps
# ---------------------------------------------------------------------------


@given(parsers.parse("Alejandro's order request includes exchange-specific params {params_repr}"))
def order_request_with_params(context, params_repr, market_btc):
    """Set up an order with extra params that must reach the exchange API."""
    import json

    try:
        params = json.loads(params_repr.replace("'", '"'))
    except (json.JSONDecodeError, ValueError):
        params = {"postOnly": True}

    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    # Inject params into the OrderRequest once it is built
    # Note: OrderRequest.params is the existing field — set via builder when implemented
    context["builders"] = [builder]
    context["expected_params"] = params


@given("the order is submitted on bybit via REST")
def order_submitted_via_rest(context, mock_bybit_rest):
    """Register the mock bybit REST exchange."""
    context["exchange"] = mock_bybit_rest


@pytest.mark.skip(reason="pending implementation: OrderRequest params propagation fix")
@when("the order is created on the exchange")
async def order_created_on_exchange(context, config_best_price):
    """Drive execution and capture what was passed to create_limit_order."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["create_calls"] = context["exchange"].api.create_limit_order.call_args_list


@then(parsers.parse("create_limit_order receives the params {params_repr}"))
def create_limit_order_receives_params(context, params_repr):
    """Assert the expected params were passed through to the exchange API (AC-X-08)."""
    import json

    try:
        expected_params = json.loads(params_repr.replace("'", '"'))
    except (json.JSONDecodeError, ValueError):
        expected_params = context.get("expected_params", {})

    create_calls = context.get("create_calls", [])
    assert len(create_calls) >= 1, "create_limit_order was not called"

    # Check that at least one call included the expected params
    params_found = False
    for call_args in create_calls:
        all_args = list(call_args.args) + list(call_args.kwargs.values())
        if any(expected_params == arg for arg in all_args):
            params_found = True
            break
        # Also check if params are included as a keyword argument
        if "params" in call_args.kwargs:
            call_params = call_args.kwargs["params"]
            if all(call_params.get(k) == v for k, v in expected_params.items()):
                params_found = True
                break

    assert params_found, (
        f"Expected params {expected_params} to be passed to create_limit_order. Actual calls: {create_calls}"
    )


@then("the params are not silently dropped")
def params_not_silently_dropped(context):
    """Alias for the params propagation check — ensures the field was not ignored."""
    # Already asserted in the previous step.
    pass


# ---------------------------------------------------------------------------
# Taker order steps (REST path)
# ---------------------------------------------------------------------------


@given(parsers.parse("a {symbol} taker order is submitted on bybit via REST"))
def taker_order_submitted_rest(context, symbol, market_btc, mock_bybit_rest):
    """Set up a REST taker order."""
    builder = build_taker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["exchange"] = mock_bybit_rest


@pytest.mark.skip(reason="pending implementation: RestOrderExecutor taker order")
@when("the taker order completes")
async def taker_order_completes(context, config_fast):
    """Drive a REST taker order through to completion."""
    executor = DefaultOrderExecutor(config_fast)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports


@then("the taker execution report shows the order filled immediately")
def taker_report_filled_immediately(context):
    """Assert the taker order returned a closed report."""
    from traxon_core.crypto.order_executor.models import OrderStatus

    reports = context["reports"]
    assert len(reports) >= 1
    assert reports[0].status == OrderStatus.CLOSED
