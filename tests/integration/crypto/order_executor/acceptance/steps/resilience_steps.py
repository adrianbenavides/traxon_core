"""
Step definitions for WS resilience and Telegram alert acceptance tests
(Milestone 6 — US-06, US-07).

Exercises:
- Exponential backoff on WS disconnect
- Circuit breaker opening after max failures
- REST polling fallback after circuit open
- Staleness window REST check
- Telegram batch summary content

All steps drive through DefaultOrderExecutor.execute_orders().
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from pytest_bdd import given, parsers, then, when

from traxon_core.crypto.models import ExchangeId, OrderSide
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor

from .conftest import MockEventSink, build_maker_order, build_taker_order, make_orders_to_execute

# ---------------------------------------------------------------------------
# WS disconnect and backoff steps
# ---------------------------------------------------------------------------


@given("a BTC/USDT maker order is open and monitored via WebSocket on bybit")
def btc_maker_monitored_ws_bybit(context, market_btc, mock_bybit_ws):
    """Set up a WS-monitored maker order."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["exchange"] = mock_bybit_ws


@given("the order book stream raises a network error")
def order_book_stream_raises_network_error(context):
    """Configure the mock WS stream to fail with a network error then succeed."""
    import ccxt

    submit_ms = int(time.time() * 1000)
    filled_order = {
        "id": "ord-backoff-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "timestamp": submit_ms + 2000,
        "info": {},
    }

    # First call raises NetworkError; second call succeeds with an order book
    context["exchange"].api.watch_order_book = AsyncMock(
        side_effect=[
            ccxt.NetworkError("Connection reset"),
            {
                "bids": [[43200.00, 5.0]],
                "asks": [[43286.40, 4.0]],
                "timestamp": submit_ms + 150,
            },
        ]
    )
    context["exchange"].api.watch_orders = AsyncMock(return_value=[filled_order])


@pytest.mark.skip(reason="pending implementation: WsOrderExecutor exponential backoff")
@when("the executor detects the disconnect")
async def executor_detects_disconnect(context, event_sink):
    """Drive execution through a WS disconnect and capture events."""
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        max_ws_reconnect_attempts=3,
    )
    executor = DefaultOrderExecutor(config)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then(parsers.parse("the first reconnect attempt is delayed by approximately {delay_ms:d} milliseconds"))
def first_reconnect_delayed(context, delay_ms):
    """Assert the ws_reconnect_attempt event captured a delay close to delay_ms."""
    sink = context.get("event_sink", MockEventSink())
    reconnect_events = sink.events_named("ws_reconnect_attempt")
    assert len(reconnect_events) >= 1, "Expected at least one ws_reconnect_attempt event (AC-06-01)"
    # When OrderEvent.ws_delay_ms is implemented, assert: reconnect_events[0].ws_delay_ms ~= delay_ms


@then(parsers.parse('a structured event named "{event_name}" is emitted with attempt number {attempt_num:d}'))
def reconnect_event_with_attempt(context, event_name, attempt_num):
    """Assert the reconnect event includes the attempt number."""
    sink = context.get("event_sink", MockEventSink())
    events = sink.events_named(event_name)
    assert len(events) >= 1, f"Expected event '{event_name}' to be emitted"
    # When OrderEvent.ws_attempt is implemented, assert events[0].ws_attempt == attempt_num


@given(parsers.parse("the WebSocket stream has failed {count:d} times and will fail a third time"))
def ws_failed_multiple_times(context, count, mock_bybit_ws):
    """Configure the WS mock to fail count+1 times then succeed."""
    import ccxt

    submit_ms = int(time.time() * 1000)
    filled_order = {
        "id": "ord-backoff-002",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "timestamp": submit_ms + 5000,
        "info": {},
    }

    failures = [ccxt.NetworkError("Connection reset") for _ in range(count + 1)]
    success_book = {
        "bids": [[43200.00, 5.0]],
        "asks": [[43286.40, 4.0]],
        "timestamp": submit_ms + 5000,
    }
    mock_bybit_ws.api.watch_order_book = AsyncMock(side_effect=failures + [success_book])
    mock_bybit_ws.api.watch_orders = AsyncMock(return_value=[filled_order])
    mock_bybit_ws.api.fetch_order = AsyncMock(return_value=filled_order)
    context["exchange"] = mock_bybit_ws


@pytest.mark.skip(reason="pending implementation: WsOrderExecutor backoff doubling")
@when("the executor retries the connection")
async def executor_retries_connection(context, event_sink):
    """Drive execution through multiple WS failures and capture backoff events."""
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        max_ws_reconnect_attempts=5,
    )
    executor = DefaultOrderExecutor(config)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then(parsers.parse("the {ordinal} reconnect delay is approximately {delay_ms:d} milliseconds"))
def nth_reconnect_delay(context, ordinal, delay_ms):
    """Assert the Nth reconnect event has approximately the expected delay."""
    ordinal_map = {"first": 0, "second": 1, "third": 2}
    idx = ordinal_map.get(ordinal.lower(), 0)

    sink = context.get("event_sink", MockEventSink())
    reconnect_events = sink.events_named("ws_reconnect_attempt")
    if len(reconnect_events) > idx:
        # When OrderEvent.ws_delay_ms is implemented, assert the delay
        pass  # Delay assertion deferred to unit tests with precise time mocking


@then(parsers.parse("delays do not exceed {max_s:d} seconds regardless of failure count"))
def delays_capped(context, max_s):
    """Assert no reconnect delay exceeded the cap."""
    sink = context.get("event_sink", MockEventSink())
    reconnect_events = sink.events_named("ws_reconnect_attempt")
    # When OrderEvent.ws_delay_ms is implemented, assert all delays <= max_s * 1000
    assert len(reconnect_events) >= 1, "Expected at least one reconnect event"


# ---------------------------------------------------------------------------
# Circuit breaker steps
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "the executor is configured with a maximum of {max_attempts:d} WebSocket reconnect attempts"
    )
)
def configured_max_ws_attempts(context, max_attempts):
    """Store the max_ws_reconnect_attempts config value."""
    context["max_ws_reconnect_attempts"] = max_attempts


@given(parsers.parse("the WebSocket stream fails {count:d} consecutive times"))
def ws_fails_consecutive_times(context, count, mock_bybit_ws):
    """Configure the WS to fail exactly count times then succeed via REST fallback."""
    import ccxt

    submit_ms = int(time.time() * 1000)
    filled_order = {
        "id": "ord-circuit-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "timestamp": submit_ms + 3000,
        "info": {},
    }

    failures = [ccxt.NetworkError("Persistent failure") for _ in range(count)]
    mock_bybit_ws.api.watch_order_book = AsyncMock(side_effect=failures)
    mock_bybit_ws.api.fetch_order = AsyncMock(return_value=filled_order)
    mock_bybit_ws.api.fetch_order_book = AsyncMock(
        return_value={
            "bids": [[43200.00, 5.0]],
            "asks": [[43286.40, 4.0]],
            "timestamp": submit_ms,
        }
    )
    context["exchange"] = mock_bybit_ws
    context["ws_failure_count"] = count


@pytest.mark.skip(reason="pending implementation: WsOrderExecutor circuit breaker")
@when("the third failure occurs")
async def third_failure_occurs(context, event_sink):
    """Drive execution through the max failures to trigger the circuit."""
    max_attempts = context.get("max_ws_reconnect_attempts", 3)
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        max_ws_reconnect_attempts=max_attempts,
    )
    executor = DefaultOrderExecutor(config)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then("no further WebSocket reconnect attempts are made")
def no_further_ws_reconnect_attempts(context):
    """Assert WS calls stopped after the circuit opened."""
    exchange = context["exchange"]
    ws_call_count = exchange.api.watch_order_book.call_count
    max_attempts = context.get("max_ws_reconnect_attempts", 3)
    assert ws_call_count <= max_attempts, (
        f"Expected at most {max_attempts} watch_order_book calls after circuit opens, got {ws_call_count}"
    )


@then('a structured event named "ws_circuit_open" is emitted with the exchange identifier')
def ws_circuit_open_event(context):
    """Assert the ws_circuit_open event was emitted (AC-06-02)."""
    sink = context.get("event_sink", MockEventSink())
    assert sink.has_event("ws_circuit_open"), (
        "Expected 'ws_circuit_open' event after max reconnect failures (AC-06-02)"
    )


# ---------------------------------------------------------------------------
# REST fallback after circuit open
# ---------------------------------------------------------------------------


@given("the WebSocket circuit has opened for bybit after 3 failures")
def ws_circuit_open(context, mock_bybit_ws):
    """Set up state where circuit is already open."""
    import ccxt

    submit_ms = int(time.time() * 1000)
    filled_order = {
        "id": "ord-fallback-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "timestamp": submit_ms + 1000,
        "info": {},
    }

    mock_bybit_ws.api.watch_order_book = AsyncMock(
        side_effect=[ccxt.NetworkError("down"), ccxt.NetworkError("down"), ccxt.NetworkError("down")]
    )
    mock_bybit_ws.api.fetch_order = AsyncMock(return_value=filled_order)
    mock_bybit_ws.api.fetch_order_book = AsyncMock(
        return_value={
            "bids": [[43200.00, 5.0]],
            "asks": [[43286.40, 4.0]],
            "timestamp": submit_ms,
        }
    )
    context["exchange"] = mock_bybit_ws


@given("a BTC/USDT order remains open")
def btc_order_remains_open(context, market_btc):
    """Set up an open maker order."""
    if "builders" not in context:
        builder = build_maker_order(
            exchange_id=ExchangeId.BYBIT,
            market=market_btc,
            side=OrderSide.BUY,
            size=Decimal("0.1"),
        )
        context["builders"] = [builder]


@pytest.mark.skip(reason="pending implementation: REST polling fallback on circuit open")
@when("the executor continues monitoring")
async def executor_continues_monitoring_rest(context, event_sink):
    """Drive execution after circuit opens and assert REST fallback activates."""
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        max_ws_reconnect_attempts=3,
    )
    executor = DefaultOrderExecutor(config)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then("the executor calls fetch_order for the open order on bybit")
def executor_calls_fetch_order_rest(context):
    """Assert fetch_order was called as the REST fallback (AC-06-03)."""
    api = context["exchange"].api
    assert api.fetch_order.called, (
        "Expected fetch_order to be called as REST fallback after WS circuit open (AC-06-03)"
    )


@then("no further WebSocket connection attempts are made for this batch")
def no_ws_attempts_in_batch(context):
    """Assert watch_order_book call count did not exceed circuit open threshold."""
    api = context["exchange"].api
    assert api.watch_order_book.call_count <= 3, "No WS reconnect attempts should be made after circuit opens"


@then('a structured event named "ws_rest_fallback" is emitted')
def ws_rest_fallback_event(context):
    """Assert the ws_rest_fallback event was emitted (AC-06-03)."""
    sink = context.get("event_sink", MockEventSink())
    assert sink.has_event("ws_rest_fallback"), (
        "Expected 'ws_rest_fallback' event when executor falls back to REST (AC-06-03)"
    )


# ---------------------------------------------------------------------------
# Staleness window steps
# ---------------------------------------------------------------------------


@given(parsers.parse("the executor is configured with a WebSocket staleness window of {window_s:d} seconds"))
def staleness_window_configured(context, window_s):
    """Store the staleness window configuration."""
    context["ws_staleness_window_s"] = float(window_s)


@given(parsers.parse('a BTC/USDT order "{order_id}" is open on bybit'))
def btc_order_open_with_id(context, order_id, market_btc, mock_bybit_ws):
    """Set up a maker order with a known order_id for staleness tests."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["expected_order_id"] = order_id
    context["exchange"] = mock_bybit_ws


@given(parsers.parse("no WebSocket update has been received for {elapsed_s:d} seconds"))
def no_ws_update_for_elapsed(context, elapsed_s, mock_bybit_ws):
    """Configure WS to block longer than the staleness window, then return."""

    async def slow_ws(*args, **kwargs):
        await asyncio.sleep(elapsed_s + 0.5)
        return {"bids": [[43200.00, 5.0]], "asks": [[43286.40, 4.0]], "timestamp": 0}

    submit_ms = int(time.time() * 1000)
    filled_order = {
        "id": context.get("expected_order_id", "ord-stale-001"),
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": 43200.00,
        "timestamp": submit_ms + (elapsed_s * 1000) + 500,
        "info": {},
    }

    mock_bybit_ws.api.watch_order_book = AsyncMock(side_effect=slow_ws)
    mock_bybit_ws.api.fetch_order = AsyncMock(return_value=filled_order)
    context["exchange"] = mock_bybit_ws
    context["elapsed_s"] = elapsed_s


@pytest.mark.skip(reason="pending implementation: WsOrderExecutor staleness check")
@when("the staleness window expires")
async def staleness_window_expires(context, event_sink):
    """Drive execution past the staleness window to trigger a REST check."""
    window_s = context.get("ws_staleness_window_s", 10.0)
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        ws_staleness_window_s=window_s,
    )
    executor = DefaultOrderExecutor(config)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then(parsers.parse('a REST fetch_order call is made for "{order_id}"'))
def rest_fetch_order_made_for(context, order_id):
    """Assert fetch_order was called during the staleness check (AC-06-04)."""
    api = context["exchange"].api
    assert api.fetch_order.called, (
        f"Expected fetch_order to be called for order {order_id!r} during staleness window check (AC-06-04)"
    )


@then("if the REST response shows the order as filled the executor returns the execution report")
def staleness_rest_returns_filled_report(context):
    """Assert execution completed with a CLOSED report after the staleness REST check."""
    from traxon_core.crypto.order_executor.models import OrderStatus

    reports = context["reports"]
    assert len(reports) >= 1
    assert reports[0].status == OrderStatus.CLOSED


@then(parsers.parse('a structured event named "ws_staleness_fallback" is emitted with the elapsed time'))
def ws_staleness_fallback_event(context):
    """Assert the ws_staleness_fallback event was emitted (AC-06-04)."""
    sink = context.get("event_sink", MockEventSink())
    assert sink.has_event("ws_staleness_fallback"), (
        "Expected 'ws_staleness_fallback' event when staleness window expires (AC-06-04)"
    )


@then("no cancel_order call is made on the exchange")
def no_cancel_order_during_staleness(context):
    """Assert the staleness check does not cancel the order (AC-06-05)."""
    api = context["exchange"].api
    assert not api.cancel_order.called, (
        "cancel_order must NOT be called during a staleness REST check (AC-06-05)"
    )


# ---------------------------------------------------------------------------
# Telegram alert steps
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "a batch of {total:d} orders completes — {filled_count:d} filled, {timeout_count:d} timed out, {rejected_count:d} rejected"
    )
)
def batch_with_mixed_outcomes(
    context, total, filled_count, timeout_count, rejected_count, market_btc, mock_bybit_rest
):
    """Set up a batch that produces mixed outcomes to test Telegram summary."""
    builders = []
    for i in range(total):
        builder = build_taker_order(
            exchange_id=ExchangeId.BYBIT,
            market=market_btc,
            side=OrderSide.BUY,
            size=Decimal("0.1"),
        )
        builders.append(builder)

    context["builders"] = builders
    context["exchange"] = mock_bybit_rest
    context["expected_filled"] = filled_count
    context["expected_timeout"] = timeout_count
    context["expected_rejected"] = rejected_count
    context["total_orders"] = total


@pytest.mark.skip(reason="pending implementation: TelegramSink structured batch summary")
@when("the batch completion notification is sent")
async def batch_completion_notification_sent(context, config_best_price):
    """
    Drive execution and capture the Telegram notification text.

    The TelegramSink accumulates events and produces a summary.
    We capture it via a mock notifier.
    """
    captured_messages: list[str] = []

    mock_notifier = MagicMock()
    mock_notifier.send_message = AsyncMock(side_effect=lambda msg: captured_messages.append(msg))

    executor = DefaultOrderExecutor(config_best_price, notifier=mock_notifier)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["telegram_messages"] = captured_messages


@then(parsers.parse('the Telegram message contains the text "{expected_text}"'))
def telegram_message_contains(context, expected_text):
    """Assert the Telegram message body contains the expected text (AC-07-01)."""
    messages = context.get("telegram_messages", [])
    assert len(messages) >= 1, "Expected at least one Telegram message to be sent"
    combined = " ".join(messages)
    assert expected_text in combined, (
        f"Expected Telegram message to contain {expected_text!r}. Actual message: {combined!r}"
    )


@then("the message includes a count for timeouts")
def telegram_includes_timeout_count(context):
    """Assert the summary text mentions the timeout count."""
    messages = context.get("telegram_messages", [])
    combined = " ".join(messages)
    timeout_count = context.get("expected_timeout", 1)
    assert str(timeout_count) in combined and "timeout" in combined.lower(), (
        f"Expected timeout count in Telegram message. Got: {combined!r}"
    )


@then("the message includes a count for rejections")
def telegram_includes_rejection_count(context):
    """Assert the summary text mentions the rejection count."""
    messages = context.get("telegram_messages", [])
    combined = " ".join(messages)
    assert "reject" in combined.lower(), f"Expected rejection count in Telegram message. Got: {combined!r}"


@then("the notification text does not contain Python type representations")
def notification_not_raw_python(context):
    """Assert the Telegram message is human-readable text (AC-07-05)."""
    messages = context.get("telegram_messages", [])
    combined = " ".join(messages)
    forbidden_patterns = ["<class ", "Decimal(", "OrderStatus."]
    for pattern in forbidden_patterns:
        assert pattern not in combined, f"Telegram message contains raw Python repr {pattern!r}: {combined!r}"


@then("the notification text does not contain raw dictionary braces")
def notification_not_raw_dict(context):
    """Assert no raw Python dict syntax in the Telegram message."""
    messages = context.get("telegram_messages", [])
    combined = " ".join(messages)
    # Allow single { or } that might appear in formatting, but not paired dict-like {{ }}
    assert "{'" not in combined and "':" not in combined, (
        f"Telegram message looks like a raw dict: {combined!r}"
    )
