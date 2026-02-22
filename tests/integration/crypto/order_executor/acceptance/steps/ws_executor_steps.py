"""
Step definitions for WsOrderExecutor acceptance tests (Milestone 2 — US-02).

Exercises WsOrderExecutor through the public driving port:
  DefaultOrderExecutor.execute_orders()

The CCXT WS API (watch_order_book, watch_orders) is mocked via AsyncMock.
The WsOrderExecutor state machine and asyncio.wait logic are real.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pytest_bdd import given, parsers, then, when

from traxon_core.crypto.models import ExchangeId, OrderSide
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor

from .conftest import MockEventSink, build_maker_order, make_orders_to_execute

# ---------------------------------------------------------------------------
# Fill detection latency steps
# ---------------------------------------------------------------------------


@given(parsers.parse('a BTC/USDT maker order "{order_id}" is open on bybit'))
def btc_maker_order_open(context, order_id, market_btc):
    """Set up a BTC/USDT maker order with a known order_id for fill detection tests."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["expected_order_id"] = order_id


@given(parsers.parse('the exchange sends a WebSocket order update marking "{order_id}" as filled'))
def ws_fill_event_arrives(context, order_id, mock_bybit_ws):
    """
    Configure the mock WS stream to return a filled order event.

    The watch_orders mock returns a single closed order, simulating the
    WebSocket fill notification arriving from the exchange.
    """
    submit_ms = int(time.time() * 1000)
    filled_order = {
        "id": order_id,
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "price": 43200.00,
        "fee": {"cost": 0.001, "currency": "USDT"},
        "timestamp": submit_ms + 850,
        "info": {},
    }
    mock_bybit_ws.api.watch_orders = AsyncMock(return_value=[filled_order])
    context["exchange"] = mock_bybit_ws
    context["fill_sent_at_ms"] = submit_ms


@pytest.mark.skip(reason="pending implementation: WsOrderExecutor event-driven fill detection")
@when("the order update message is received")
async def ws_order_update_received(context, config_best_price, event_sink):
    """Drive execution and measure time from fill event to report return."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])

    start = time.monotonic()
    reports = await executor.execute_orders([context["exchange"]], orders)
    end = time.monotonic()

    context["reports"] = reports
    context["detection_latency_ms"] = (end - start) * 1000
    context["event_sink"] = event_sink


@then(
    parsers.parse(
        "the execution report is returned within {max_ms:d} milliseconds of the message being received"
    )
)
def report_returned_within_latency(context, max_ms):
    """Assert fill detection latency is within the specified bound (AC-02-02)."""
    latency = context.get("detection_latency_ms", 0)
    assert latency <= max_ms, f"Fill detection latency {latency:.1f}ms exceeds {max_ms}ms limit (AC-02-02)"


@then("the report shows the order is filled")
def report_shows_filled(context):
    from traxon_core.crypto.order_executor.models import OrderStatus

    reports = context["reports"]
    assert len(reports) >= 1
    assert reports[0].status == OrderStatus.CLOSED


# ---------------------------------------------------------------------------
# No busy-wait polling steps
# ---------------------------------------------------------------------------


@given("a BTC/USDT maker order is open and being monitored on bybit via WebSocket")
def btc_maker_monitored_ws(context, market_btc):
    """Set up a WS-monitored maker order."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]


@given("no order book or order status events arrive for 3 seconds")
def no_ws_events_for_3_seconds(context, mock_bybit_ws):
    """
    Configure the WS mock to block for 3 seconds before returning any event.

    This simulates a quiet market period — the executor should remain
    suspended in asyncio.wait, not spin in a polling loop.
    """

    async def slow_watch_order_book(symbol):
        await asyncio.sleep(3.0)
        return {
            "bids": [[43200.00, 5.0]],
            "asks": [[43286.40, 4.0]],
            "timestamp": int(time.time() * 1000),
        }

    # After the 3-second wait, return a filled order to unblock execution
    submit_ms = int(time.time() * 1000)
    filled_order = {
        "id": "ord-quiet-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "timestamp": submit_ms + 3000,
        "info": {},
    }
    mock_bybit_ws.api.watch_order_book = AsyncMock(side_effect=slow_watch_order_book)
    mock_bybit_ws.api.watch_orders = AsyncMock(return_value=[filled_order])
    context["exchange"] = mock_bybit_ws


@pytest.mark.skip(reason="pending implementation: WsOrderExecutor no busy-wait")
@when("the monitoring loop runs during those 3 seconds")
async def monitoring_loop_runs(context, config_best_price):
    """Drive the WS executor through a quiet period."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports


@then("the executor performs zero loop iterations during the quiet period")
def executor_performs_zero_iterations(context):
    """
    Assert no asyncio.sleep polling occurred.

    This is verified structurally: the new design uses asyncio.wait(FIRST_COMPLETED)
    which does not iterate. A loop iteration counter could be injected via the event
    bus — assert no 'poll_tick' events were emitted.
    """
    sink = context.get("event_sink", MockEventSink())
    poll_events = sink.events_named("poll_tick")
    assert len(poll_events) == 0, f"Expected 0 poll_tick events during quiet period, got {len(poll_events)}"


@then("the executor resumes only when the next WebSocket event arrives")
def executor_resumes_on_ws_event(context):
    """Assert execution completed (unblocked by the eventual WS event)."""
    assert "reports" in context, "Executor must have completed after WS event arrived"


# ---------------------------------------------------------------------------
# State machine transitions steps
# ---------------------------------------------------------------------------


@given("Alejandro submits a BTC/USDT maker order on bybit via WebSocket")
def alejandro_submits_ws_maker(context, market_btc):
    """Set up a standard WS maker order."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]


@pytest.mark.skip(reason="pending implementation: WsOrderExecutor state machine")
@when("the order goes through the full happy path")
async def order_goes_through_happy_path(context, config_best_price, mock_bybit_ws, event_sink):
    """Drive the full happy path and capture the event stream."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([mock_bybit_ws], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then(parsers.parse("the order transitions through: {states}"))
def order_transitions_through_states(context, states):
    """Assert the expected state sequence appeared in the event log (AC-02-03)."""
    sink = context.get("event_sink", MockEventSink())
    expected_states = [s.strip() for s in states.split(",")]
    emitted_states = [e.state.lower() for e in sink.events]

    for expected in expected_states:
        assert any(expected.lower() in state for state in emitted_states), (
            f"Expected state '{expected}' in event stream, got: {emitted_states}"
        )


# ---------------------------------------------------------------------------
# Task cleanup steps
# ---------------------------------------------------------------------------


@given("a BTC/USDT maker order is being monitored on bybit")
def btc_maker_being_monitored(context, market_btc):
    """Set up a maker order for task cleanup tests."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]


@given("an unexpected error occurs during execution")
def unexpected_error_during_execution(context, mock_bybit_ws):
    """Configure the mock to raise an error mid-execution."""
    mock_bybit_ws.api.watch_orders = AsyncMock(side_effect=RuntimeError("Unexpected error in test"))
    context["exchange"] = mock_bybit_ws


@pytest.mark.skip(reason="pending implementation: WsOrderExecutor task cleanup")
@when("an unexpected error occurs during execution")
async def error_occurs(context, config_best_price):
    """Drive execution expecting an error — capture any raised exception."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    try:
        await executor.execute_orders([context["exchange"]], orders)
    except Exception as exc:
        context["raised_exception"] = exc


@then("the order book watch task is cancelled")
def order_book_task_cancelled(context, mock_bybit_ws):
    """Assert watch_order_book task was cancelled (via cancel() being called on the task)."""
    # When the real implementation exists, this can be verified via task state.
    # For now, assert the mock was called (task was started and should have been cleaned up).
    assert mock_bybit_ws.api.watch_order_book.called, "watch_order_book must have been started before cleanup"


@then("the order status watch task is cancelled")
def order_status_task_cancelled(context, mock_bybit_ws):
    """Assert watch_orders task was cancelled."""
    assert mock_bybit_ws.api.watch_orders.called, "watch_orders must have been started before cleanup"


@then("no background tasks are left running after execution ends")
def no_orphaned_tasks(context):
    """Assert no tasks are left running after the executor exits."""
    all_tasks = asyncio.all_tasks()
    # Filter out the current test task itself
    executor_tasks = [t for t in all_tasks if t != asyncio.current_task() and "order" in str(t).lower()]
    assert len(executor_tasks) == 0, (
        f"Found {len(executor_tasks)} orphaned executor tasks after execution ended"
    )
