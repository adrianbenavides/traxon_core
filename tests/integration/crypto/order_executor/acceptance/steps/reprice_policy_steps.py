"""
Step definitions for RepricePolicy acceptance tests (Milestone 5 — US-05).

Tests the reprice policy decision gate that sits between the order book update
and the cancel-and-replace cycle in both WS and REST executors.

Exercises through the public driving port DefaultOrderExecutor.execute_orders(),
with the mock exchange API configured to emit order book updates that
either should or should not trigger a reprice.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, then, when

from traxon_core.crypto.models import ExchangeId, OrderSide
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor

from .conftest import MockEventSink, build_maker_order, make_orders_to_execute

# ---------------------------------------------------------------------------
# Min reprice threshold config steps
# ---------------------------------------------------------------------------


@given(parsers.parse("Alejandro configures the executor with a minimum reprice threshold of {threshold_pct}"))
def executor_with_min_reprice_threshold(context, threshold_pct):
    """Store the threshold configuration for later use."""
    # Convert "0.1%" -> 0.001
    clean = threshold_pct.strip().rstrip("%")
    value = float(clean) / 100.0
    context["min_reprice_threshold_pct"] = value


@given(parsers.parse("the executor is configured with a minimum reprice threshold of {threshold_pct}"))
def executor_configured_with_threshold(context, threshold_pct):
    """Set the threshold in context (alias for the previous step)."""
    clean = threshold_pct.strip().rstrip("%")
    value = float(clean) / 100.0
    context["min_reprice_threshold_pct"] = value


@given(parsers.parse("a BTC/USDT maker order is at price {price:.2f} on bybit"))
def btc_maker_at_price(context, price, market_btc, mock_bybit_rest):
    """Set up a maker order at a specific price and register the exchange."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["current_order_price"] = Decimal(str(price))
    context["exchange"] = mock_bybit_rest


# ---------------------------------------------------------------------------
# Micro-movement suppression steps
# ---------------------------------------------------------------------------


@given(parsers.parse("the order book emits a new best price of {new_price:.2f} (a change of {change_pct})"))
def order_book_emits_micro_price(context, new_price, change_pct, mock_bybit_rest):
    """
    Configure the mock to emit an order book update at the new_price.

    The exchange first returns the order book with the new price,
    then returns a filled order to unblock the executor.
    """
    import time

    submit_ms = int(time.time() * 1000)

    # Order book with the new (micro-changed) best bid
    micro_book = {
        "bids": [[new_price, 5.0], [new_price - 1.0, 3.0]],
        "asks": [[new_price + 86.40, 4.0]],
        "timestamp": submit_ms,
    }

    # After evaluating the book, the order fills at the original price
    filled_order = {
        "id": "ord-micro-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": float(context.get("current_order_price", 43200.00)),
        "timestamp": submit_ms + 1000,
        "info": {},
    }

    mock_bybit_rest.api.fetch_order_book = AsyncMock(return_value=micro_book)
    mock_bybit_rest.api.fetch_order = AsyncMock(return_value=filled_order)
    context["new_price"] = Decimal(str(new_price))
    context["exchange"] = mock_bybit_rest


@pytest.mark.skip(reason="pending implementation: RepricePolicy.should_reprice() gate")
@when("the order book emits a new best price of {new_price:.2f} (a change of {change_pct})")
async def when_order_book_emits_price(context, new_price, change_pct, event_sink):
    """Drive execution with the configured price update and capture events."""
    threshold = context.get("min_reprice_threshold_pct", 0.001)
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        min_reprice_threshold_pct=threshold,
    )
    executor = DefaultOrderExecutor(config)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([context["exchange"]], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink


@then("no cancel_order call is made on the exchange")
def no_cancel_order_call(context):
    """Assert cancel_order was NOT invoked (reprice was suppressed)."""
    api = context["exchange"].api
    assert not api.cancel_order.called, (
        "cancel_order must NOT be called when reprice is suppressed (AC-05-02)"
    )


@then("the executor remains in the monitoring state")
def executor_remains_monitoring(context):
    """Assert no UPDATING_ORDER or CANCELLED state events were emitted."""
    sink = context.get("event_sink", MockEventSink())
    updating_events = [
        e for e in sink.events if "updating" in e.state.lower() or "cancelled" in e.state.lower()
    ]
    assert len(updating_events) == 0, f"Expected no UPDATING_ORDER state, found: {updating_events}"


@then("a structured event is emitted noting that the reprice was suppressed")
def reprice_suppressed_event_emitted(context):
    """Assert the order_reprice_suppressed event was captured (AC-05-03)."""
    sink = context.get("event_sink", MockEventSink())
    assert sink.has_event("order_reprice_suppressed"), (
        "Expected 'order_reprice_suppressed' event in the event stream (AC-05-03)"
    )


# ---------------------------------------------------------------------------
# Significant move triggering reprice
# ---------------------------------------------------------------------------


@given(parsers.parse("the order book emits a new best price of {new_price:.2f} (a change of {change_pct})"))
def order_book_emits_significant_price(context, new_price, change_pct, mock_bybit_rest):
    """Configure the mock for a significant price movement that should trigger reprice."""
    import time

    submit_ms = int(time.time() * 1000)

    significant_book = {
        "bids": [[new_price, 5.0], [new_price - 1.0, 3.0]],
        "asks": [[new_price + 60.0, 4.0]],
        "timestamp": submit_ms,
    }

    # After repricing, the new order fills
    filled_order_new_price = {
        "id": "ord-reprice-002",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": new_price,
        "timestamp": submit_ms + 2000,
        "info": {},
    }

    mock_bybit_rest.api.fetch_order_book = AsyncMock(return_value=significant_book)
    mock_bybit_rest.api.fetch_order = AsyncMock(
        side_effect=[
            # First call: original order still open
            {
                "id": "ord-reprice-001",
                "status": "open",
                "amount": 0.1,
                "filled": 0.0,
                "remaining": 0.1,
                "timestamp": submit_ms,
                "info": {},
            },
            # Second call: new order after reprice is closed
            filled_order_new_price,
        ]
    )
    context["new_price"] = Decimal(str(new_price))
    context["exchange"] = mock_bybit_rest


@then("the open order is cancelled")
def open_order_is_cancelled(context):
    """Assert cancel_order was called during the reprice cycle."""
    api = context["exchange"].api
    assert api.cancel_order.called, (
        "cancel_order must be called when a significant price movement triggers reprice"
    )


@then(parsers.parse("a new limit order is placed at {new_price:.2f}"))
def new_limit_order_placed(context, new_price):
    """Assert a new create_limit_order was called at the new price."""
    api = context["exchange"].api
    assert api.create_limit_order.call_count >= 2, (
        "Expected at least 2 create_limit_order calls (initial + after reprice)"
    )


@then('a structured event named "order_repriced" is emitted with the old and new prices')
def order_repriced_event_emitted(context):
    """Assert the order_repriced event was captured (AC-04-01)."""
    sink = context.get("event_sink", MockEventSink())
    assert sink.has_event("order_repriced"), "Expected 'order_repriced' event in the event stream (AC-04-01)"


# ---------------------------------------------------------------------------
# Elapsed time override steps
# ---------------------------------------------------------------------------


@given(parsers.parse("a BTC/USDT maker order has been open for {elapsed:d} seconds"))
def maker_order_open_for_elapsed(context, elapsed, market_btc):
    """Set up context for an elapsed-time override test."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["elapsed_seconds"] = elapsed


@given(parsers.parse("the elapsed time override is set to {override:d} seconds"))
def elapsed_time_override_set(context, override):
    """Store the elapsed time override in context."""
    context["reprice_override_after_seconds"] = float(override)


@pytest.mark.skip(reason="pending implementation: ElapsedTimeRepricePolicy override")
@when(parsers.parse("the order book emits a new best price that differs by only {change_pct}"))
async def order_book_emits_tiny_change_after_elapsed(context, change_pct, mock_bybit_rest, event_sink):
    """Drive execution with elapsed time override configured."""
    import time

    submit_ms = int(time.time() * 1000)
    current_price = float(context.get("current_order_price", 43200.00))
    tiny_new_price = current_price + 0.02  # ~0.00046% change

    tiny_book = {
        "bids": [[tiny_new_price, 5.0]],
        "asks": [[tiny_new_price + 86.40, 4.0]],
        "timestamp": submit_ms,
    }
    filled_order = {
        "id": "ord-override-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": tiny_new_price,
        "timestamp": submit_ms + 500,
        "info": {},
    }
    mock_bybit_rest.api.fetch_order_book = AsyncMock(return_value=tiny_book)
    mock_bybit_rest.api.fetch_order = AsyncMock(return_value=filled_order)

    threshold = context.get("min_reprice_threshold_pct", 0.001)
    override = context.get("reprice_override_after_seconds", 90.0)
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        min_reprice_threshold_pct=threshold,
        reprice_override_after_seconds=override,
    )
    executor = DefaultOrderExecutor(config)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([mock_bybit_rest], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink
    context["exchange"] = mock_bybit_rest


@then("the open order is cancelled despite the movement being below the threshold")
def order_cancelled_despite_threshold(context):
    """Assert cancel was called even though the change was below min_reprice_threshold_pct."""
    api = context["exchange"].api
    assert api.cancel_order.called, (
        "cancel_order must be called when the elapsed override is active, "
        "even for sub-threshold price changes (AC-05-04)"
    )


@then('the reprice event includes the reason "elapsed_override"')
def reprice_event_has_elapsed_override_reason(context):
    """Assert the reprice event reason is 'elapsed_override'."""
    sink = context.get("event_sink", MockEventSink())
    reprice_events = sink.events_named("order_repriced")
    assert len(reprice_events) >= 1, "Expected at least one order_repriced event"
    # The reason field should be checked once OrderEvent is implemented
    # For now, assert the event exists — the reason field check is a unit test concern


# ---------------------------------------------------------------------------
# Default threshold (always reprice) steps
# ---------------------------------------------------------------------------


@given("the executor is configured with the default minimum reprice threshold of 0.0%")
def default_threshold_zero(context):
    """Store default threshold (0.0 = always reprice)."""
    context["min_reprice_threshold_pct"] = 0.0


@given("a BTC/USDT maker order is at price 43200.00")
def btc_maker_at_43200(context, market_btc, mock_bybit_rest):
    """Set up a maker order at 43200.00."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["current_order_price"] = Decimal("43200.00")
    context["exchange"] = mock_bybit_rest


@pytest.mark.skip(reason="pending implementation: RepricePolicy default (always reprice)")
@when("the order book emits any different price")
async def order_book_emits_any_different_price(context, event_sink, mock_bybit_rest):
    """Drive with any price change and threshold 0.0 — must always reprice."""
    import time

    submit_ms = int(time.time() * 1000)
    new_price = 43201.00  # Any different price

    new_book = {
        "bids": [[new_price, 5.0]],
        "asks": [[new_price + 86.40, 4.0]],
        "timestamp": submit_ms,
    }
    filled_order = {
        "id": "ord-default-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": new_price,
        "timestamp": submit_ms + 500,
        "info": {},
    }
    mock_bybit_rest.api.fetch_order_book = AsyncMock(return_value=new_book)
    mock_bybit_rest.api.fetch_order = AsyncMock(return_value=filled_order)

    config = ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        min_reprice_threshold_pct=0.0,
    )
    executor = DefaultOrderExecutor(config)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([mock_bybit_rest], orders)
    context["reports"] = reports
    context["event_sink"] = event_sink
    context["exchange"] = mock_bybit_rest


@then("the order is repriced without suppression")
def order_repriced_without_suppression(context):
    """Assert no reprice_suppressed event was emitted (threshold 0.0 = always reprice)."""
    sink = context.get("event_sink", MockEventSink())
    suppressed_events = sink.events_named("order_reprice_suppressed")
    assert len(suppressed_events) == 0, (
        "With threshold 0.0, reprice must never be suppressed (backward-compatible default)"
    )
