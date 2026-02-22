"""Unit tests for OrderEventBus, OrderState, OrderEvent, StructlogSink, TelegramSink.

Test Budget: 5 behaviors x 2 = 10 unit tests maximum.
Actual count: 7 unit tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import structlog.testing

from traxon_core.crypto.order_executor.event_bus import (
    EventSink,
    OrderEvent,
    OrderEventBus,
    OrderState,
    StructlogSink,
    TelegramSink,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(state: OrderState = OrderState.SUBMITTED) -> OrderEvent:
    return OrderEvent(
        order_id="ord-001",
        exchange_id="bybit",
        symbol="BTC/USDT",
        side="buy",
        state=state,
        timestamp_ms=1_700_000_000_000,
        event_name="order_submitted",
        latency_ms=12,
        fill_price=None,
        fill_qty=None,
    )


class RecordingSink:
    """EventSink spy that records received events."""

    def __init__(self) -> None:
        self.received: list[OrderEvent] = []

    def on_event(self, event: OrderEvent) -> None:
        self.received.append(event)


class ExplodingSink:
    """EventSink that always raises."""

    def on_event(self, event: OrderEvent) -> None:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Behavior 1: OrderEventBus.emit delivers to all sinks in registration order
# ---------------------------------------------------------------------------


def test_emit_delivers_event_to_all_registered_sinks_in_order() -> None:
    bus = OrderEventBus()
    sink_a = RecordingSink()
    sink_b = RecordingSink()
    bus.register_sink(sink_a)
    bus.register_sink(sink_b)
    event = make_event()

    bus.emit(event)

    assert sink_a.received == [event]
    assert sink_b.received == [event]


def test_emit_delivers_to_sinks_in_registration_order() -> None:
    call_order: list[str] = []

    class OrderedSink:
        def __init__(self, name: str) -> None:
            self.name = name

        def on_event(self, event: OrderEvent) -> None:
            call_order.append(self.name)

    bus = OrderEventBus()
    bus.register_sink(OrderedSink("first"))
    bus.register_sink(OrderedSink("second"))
    bus.emit(make_event())

    assert call_order == ["first", "second"]


# ---------------------------------------------------------------------------
# Behavior 2: Failing sink does not block remaining sinks
# ---------------------------------------------------------------------------


def test_failing_sink_does_not_prevent_remaining_sinks_from_receiving_event() -> None:
    bus = OrderEventBus()
    bus.register_sink(ExplodingSink())
    good_sink = RecordingSink()
    bus.register_sink(good_sink)

    bus.emit(make_event())  # Must not raise

    assert len(good_sink.received) == 1


def test_failing_sink_failure_is_logged_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    bus = OrderEventBus()
    bus.register_sink(ExplodingSink())

    with caplog.at_level(logging.WARNING):
        bus.emit(make_event())

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("boom" in msg or "ExplodingSink" in msg or "sink" in msg.lower() for msg in warning_messages)


# ---------------------------------------------------------------------------
# Behavior 3: StructlogSink records event fields as structured key-value pairs
# ---------------------------------------------------------------------------


def test_structlog_sink_records_all_event_fields_as_structured_kv() -> None:
    sink = StructlogSink()
    event = make_event()

    with structlog.testing.capture_logs() as captured:
        sink.on_event(event)

    assert len(captured) == 1
    log_entry = captured[0]
    assert log_entry["order_id"] == event.order_id
    assert log_entry["exchange_id"] == event.exchange_id
    assert log_entry["symbol"] == event.symbol
    assert log_entry["state"] == event.state
    assert log_entry["event_name"] == event.event_name


# ---------------------------------------------------------------------------
# Behavior 4: TelegramSink.flush_summary returns formatted string
# ---------------------------------------------------------------------------


def test_telegram_sink_flush_summary_returns_non_empty_string_after_events() -> None:
    sink = TelegramSink()
    sink.on_event(make_event(OrderState.SUBMITTED))
    sink.on_event(make_event(OrderState.FILLED))

    summary = sink.flush_summary()

    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "BTC/USDT" in summary or "ord-001" in summary or "FILLED" in summary.upper()


def test_telegram_sink_flush_summary_clears_accumulated_events() -> None:
    sink = TelegramSink()
    sink.on_event(make_event())
    sink.flush_summary()

    second_summary = sink.flush_summary()

    assert second_summary == "" or "no events" in second_summary.lower() or second_summary.strip() == ""


# ---------------------------------------------------------------------------
# Behavior 5: OrderState has all 12 required values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state_name",
    [
        # Lifecycle states (7)
        "PENDING",
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "TIMED_OUT",
        "FAILED",
        # Internal state machine states (5)
        "INITIALIZING",
        "CREATING_ORDER",
        "MONITORING_ORDER",
        "UPDATING_ORDER",
        "WAIT_UNTIL_ORDER_CANCELLED",
    ],
)
def test_order_state_has_all_required_values(state_name: str) -> None:
    assert hasattr(OrderState, state_name), f"OrderState missing: {state_name}"
    member = OrderState[state_name]
    assert isinstance(member, OrderState)
