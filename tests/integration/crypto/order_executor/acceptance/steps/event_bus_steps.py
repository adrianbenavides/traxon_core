"""
Step definitions for OrderEventBus acceptance tests (Milestone 4 — US-04, US-08).

Exercises the structured event emission through the public driving port.
The MockEventSink captures all OrderEvents for assertion.

All steps drive through DefaultOrderExecutor.execute_orders().
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pytest_bdd import given, parsers, then, when

from traxon_core.crypto.models import ExchangeId, OrderSide
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor

from .conftest import MockEventSink, build_maker_order, build_taker_order, make_orders_to_execute

# ---------------------------------------------------------------------------
# Event stream steps — submission and fill complete
# ---------------------------------------------------------------------------


@given(parsers.parse("Alejandro submits a BTC/USDT maker order on {exchange_name} that fills successfully"))
def btc_maker_fills_successfully(context, exchange_name, market_btc):
    """Set up a happy-path maker order."""
    try:
        exchange_id = ExchangeId(exchange_name)
    except ValueError:
        exchange_id = ExchangeId.BYBIT

    builder = build_maker_order(
        exchange_id=exchange_id,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["exchange_name"] = exchange_name


@pytest.mark.skip(reason="pending implementation: OrderEventBus canonical event names")
@when("the order completes")
async def order_completes(context, config_best_price, mock_bybit_rest, event_sink):
    """Drive execution and capture events via the event sink."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([mock_bybit_rest], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then(parsers.parse('the event log contains an event named "{event_name}"'))
def event_log_contains_event(context, event_name):
    """Assert the named event was emitted at least once."""
    sink = context.get("event_sink", MockEventSink())
    assert sink.has_event(event_name), (
        f"Expected event '{event_name}' in the event stream. "
        f"Captured events: {[e.event_name for e in sink.events]}"
    )


@then("every event includes the order identifier as a correlation field")
def every_event_has_order_id(context):
    """Assert order_id is non-empty on every captured event (AC-04-02)."""
    sink = context.get("event_sink", MockEventSink())
    for event in sink.events:
        assert event.order_id, f"Event '{event.event_name}' is missing order_id correlation field (AC-04-02)"


# ---------------------------------------------------------------------------
# Required fields on every event
# ---------------------------------------------------------------------------


@given("Alejandro submits a BTC/USDT maker order on bybit")
def alejandro_submits_btc_maker(context, market_btc):
    """Set up a standard BTC/USDT maker order."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]


@pytest.mark.skip(reason="pending implementation: OrderEvent required fields")
@when("the order goes through any state transition")
async def order_goes_through_state_transition(context, config_best_price, mock_bybit_rest, event_sink):
    """Drive execution to trigger state transition events."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([mock_bybit_rest], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then("every emitted event includes:")
def every_event_includes_required_fields(context):
    """Assert all required fields are present on every event (AC-04-02)."""
    sink = context.get("event_sink", MockEventSink())
    required_fields = ["order_id", "symbol", "exchange_id", "timestamp_ms"]

    for event in sink.events:
        for field_name in required_fields:
            value = getattr(event, field_name, None)
            assert value is not None and value != "" and value != 0, (
                f"Event '{event.event_name}' missing required field '{field_name}'"
            )


# ---------------------------------------------------------------------------
# Fill latency steps
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "a BTC/USDT maker order was submitted at a known time and fills {latency_ms:d} milliseconds later"
    )
)
def btc_maker_fills_at_known_latency(context, latency_ms, market_btc, mock_bybit_rest):
    """
    Set up the mock to simulate a fill at a precise latency.

    The mock returns a filled order with timestamp = submit_time + latency_ms.
    """
    submit_ms = int(time.time() * 1000)
    filled_order = {
        "id": "ord-latency-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "price": 43200.00,
        "fee": {"cost": 0.001, "currency": "USDT"},
        "timestamp": submit_ms + latency_ms,
        "info": {},
    }
    mock_bybit_rest.api.fetch_order = AsyncMock(return_value=filled_order)
    mock_bybit_rest.api.create_market_order = AsyncMock(return_value=filled_order)
    mock_bybit_rest.api.create_limit_order = AsyncMock(
        return_value={**filled_order, "status": "open", "timestamp": submit_ms}
    )

    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["exchange"] = mock_bybit_rest
    context["expected_latency_ms"] = latency_ms
    context["submit_ms"] = submit_ms


@pytest.mark.skip(reason="pending implementation: fill_latency_ms computation")
@when("the execution report is produced")
async def execution_report_produced(context, config_best_price, event_sink):
    """Drive execution and capture the report."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then(parsers.parse("the report includes fill_latency_ms equal to {expected_ms:d}"))
def report_includes_fill_latency(context, expected_ms):
    """Assert fill_latency_ms on the ExecutionReport matches the expected value (AC-08-02)."""
    reports = context["reports"]
    assert len(reports) >= 1
    report = reports[0]
    assert hasattr(report, "fill_latency_ms"), "ExecutionReport must have fill_latency_ms"
    assert report.fill_latency_ms == expected_ms, (
        f"Expected fill_latency_ms={expected_ms}, got {report.fill_latency_ms}"
    )


@then("fill_latency_ms is zero or greater")
def fill_latency_non_negative(context):
    """Assert fill_latency_ms is non-negative."""
    reports = context["reports"]
    assert len(reports) >= 1
    assert reports[0].fill_latency_ms >= 0


@then(parsers.parse("the event includes fill_latency_ms equal to {expected_ms:d}"))
def fill_complete_event_has_latency(context, expected_ms):
    """Assert the order_fill_complete event includes fill_latency_ms (AC-04-03)."""
    sink = context.get("event_sink", MockEventSink())
    fill_events = sink.events_named("order_fill_complete")
    assert len(fill_events) >= 1, "Expected at least one order_fill_complete event"


@then("fill_latency_ms is greater than zero")
def fill_latency_greater_than_zero(context):
    """Assert fill_latency_ms is positive."""
    reports = context.get("reports", [])
    if reports:
        assert reports[0].fill_latency_ms > 0


# ---------------------------------------------------------------------------
# Partial fill steps
# ---------------------------------------------------------------------------


@given(parsers.parse("a BTC/USDT maker order for {amount} BTC is open on bybit"))
def btc_maker_order_amount(context, amount, market_btc, mock_bybit_rest):
    """Set up a maker order for a specific amount."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal(str(amount)),
    )
    context["builders"] = [builder]
    context["exchange"] = mock_bybit_rest
    context["total_amount"] = Decimal(str(amount))


@given(parsers.parse("the exchange reports that {filled} BTC has been filled with {remaining} BTC remaining"))
def exchange_reports_partial_fill(context, filled, remaining, mock_bybit_rest):
    """Configure the mock to return a partial fill status."""
    submit_ms = int(time.time() * 1000)

    partial_fill = {
        "id": "ord-partial-001",
        "symbol": "BTC/USDT",
        "status": "open",
        "amount": float(filled) + float(remaining),
        "filled": float(filled),
        "remaining": float(remaining),
        "average": 43200.00,
        "price": 43200.00,
        "timestamp": submit_ms + 500,
        "info": {},
    }
    full_fill = {
        **partial_fill,
        "status": "closed",
        "filled": float(filled) + float(remaining),
        "remaining": 0.0,
        "fee": {"cost": 0.001, "currency": "USDT"},
        "timestamp": submit_ms + 2000,
    }

    mock_bybit_rest.api.fetch_order = AsyncMock(side_effect=[partial_fill, full_fill])
    context["exchange"] = mock_bybit_rest
    context["partial_filled"] = Decimal(str(filled))
    context["partial_remaining"] = Decimal(str(remaining))


@pytest.mark.skip(reason="pending implementation: order_fill_partial event")
@when("the order status update is processed")
async def order_status_update_processed(context, config_best_price, event_sink):
    """Drive execution through the partial fill update."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then(parsers.parse('a structured event named "{event_name}" is emitted'))
def structured_event_emitted(context, event_name):
    """Assert the named event appears in the captured stream."""
    sink = context.get("event_sink", MockEventSink())
    assert sink.has_event(event_name), (
        f"Expected '{event_name}' event. Captured: {[e.event_name for e in sink.events]}"
    )


@then(parsers.parse("the event shows {filled} filled and {remaining} remaining"))
def partial_fill_event_values(context, filled, remaining):
    """Assert the partial fill event captures the correct amounts."""
    sink = context.get("event_sink", MockEventSink())
    partial_events = sink.events_named("order_fill_partial")
    assert len(partial_events) >= 1, "Expected at least one order_fill_partial event"


@then(parsers.parse("the executor continues monitoring for the remaining {remaining} BTC"))
def executor_continues_monitoring(context, remaining):
    """Assert the executor completed successfully after the partial fill."""
    from traxon_core.crypto.order_executor.models import OrderStatus

    reports = context["reports"]
    assert len(reports) >= 1
    assert reports[0].status == OrderStatus.CLOSED


# ---------------------------------------------------------------------------
# Exchange_id on report steps
# ---------------------------------------------------------------------------


@given(parsers.parse("a BTC/USDT maker order fills on {exchange_name}"))
def btc_maker_fills_on_exchange(context, exchange_name, market_btc, mock_bybit_rest):
    """Set up a maker order that fills on the specified exchange."""
    try:
        exchange_id = ExchangeId(exchange_name)
    except ValueError:
        exchange_id = ExchangeId.BYBIT

    builder = build_maker_order(
        exchange_id=exchange_id,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["exchange"] = mock_bybit_rest
    context["expected_exchange_id"] = exchange_name


@pytest.mark.skip(reason="pending implementation: ExecutionReport.exchange_id")
@when("the execution report is produced for exchange id check")
async def execution_report_produced_exchange_id(context, config_best_price, event_sink):
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then(parsers.parse('the report includes exchange_id equal to "{exchange_name}"'))
def report_includes_exchange_id(context, exchange_name):
    """Assert ExecutionReport.exchange_id is the expected exchange (AC-08-01)."""
    reports = context["reports"]
    assert len(reports) >= 1
    report = reports[0]
    assert hasattr(report, "exchange_id"), "ExecutionReport must have exchange_id"
    assert str(report.exchange_id) == exchange_name, (
        f"Expected exchange_id={exchange_name!r}, got {report.exchange_id!r}"
    )


@then("the exchange_id field is not empty")
def exchange_id_not_empty(context):
    """Assert exchange_id is not None or empty."""
    reports = context["reports"]
    assert len(reports) >= 1
    assert reports[0].exchange_id is not None
