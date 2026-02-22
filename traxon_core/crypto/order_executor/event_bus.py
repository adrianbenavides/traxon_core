"""
Order event bus: OrderState enum, OrderEvent dataclass, EventSink Protocol,
OrderEventBus fan-out, StructlogSink, and TelegramSink.

This module is the single source of truth for OrderState — all executors
import it from here.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

import structlog
from beartype import beartype

_log = logging.getLogger(__name__)
_structlog_logger: structlog.stdlib.BoundLogger = structlog.get_logger()


# ---------------------------------------------------------------------------
# OrderState
# ---------------------------------------------------------------------------


class OrderState(str, enum.Enum):
    """All lifecycle and internal state-machine states for an order."""

    # --- Public lifecycle states ---
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"

    # --- Internal state machine states ---
    INITIALIZING = "INITIALIZING"
    CREATING_ORDER = "CREATING_ORDER"
    MONITORING_ORDER = "MONITORING_ORDER"
    UPDATING_ORDER = "UPDATING_ORDER"
    WAIT_UNTIL_ORDER_CANCELLED = "WAIT_UNTIL_ORDER_CANCELLED"


# ---------------------------------------------------------------------------
# OrderEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderEvent:
    """Immutable event emitted at every significant state transition."""

    order_id: str
    exchange_id: str
    symbol: str
    side: str
    state: OrderState
    timestamp_ms: int
    event_name: str
    latency_ms: int | None
    fill_price: Decimal | None
    fill_qty: Decimal | None


# ---------------------------------------------------------------------------
# EventSink Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EventSink(Protocol):
    """Synchronous event receiver. All sinks must implement this protocol."""

    @beartype
    def on_event(self, event: OrderEvent) -> None:
        """Receive and process a single OrderEvent."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# OrderEventBus
# ---------------------------------------------------------------------------


class OrderEventBus:
    """
    Synchronous fan-out event bus.

    Delivers each event to all registered sinks in registration order.
    A failing sink is logged at WARNING and does not prevent remaining
    sinks from receiving the event.
    """

    def __init__(self) -> None:
        self._sinks: list[EventSink] = []

    @beartype
    def register_sink(self, sink: EventSink) -> None:
        """Register a sink to receive future events."""
        self._sinks.append(sink)

    @beartype
    def emit(self, event: OrderEvent) -> None:
        """Emit an event to all registered sinks."""
        for sink in self._sinks:
            try:
                sink.on_event(event)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "EventSink %s raised an exception for event %s: %s",
                    type(sink).__name__,
                    event.event_name,
                    exc,
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# StructlogSink
# ---------------------------------------------------------------------------


class StructlogSink:
    """Logs every OrderEvent field as structured key-value pairs via structlog."""

    @beartype
    def on_event(self, event: OrderEvent) -> None:
        """Log all OrderEvent fields as structured key-value pairs."""
        _structlog_logger.info(
            "order_event",
            order_id=event.order_id,
            exchange_id=event.exchange_id,
            symbol=event.symbol,
            side=event.side,
            state=event.state,
            timestamp_ms=event.timestamp_ms,
            event_name=event.event_name,
            latency_ms=event.latency_ms,
            fill_price=event.fill_price,
            fill_qty=event.fill_qty,
        )


# ---------------------------------------------------------------------------
# TelegramSink
# ---------------------------------------------------------------------------


class TelegramSink:
    """
    Accumulates events in memory and provides a flush_summary method
    that formats a human-readable batch summary with per-outcome counts.

    Per-outcome mapping:
      FILLED    -> filled
      TIMED_OUT -> timeout
      FAILED    -> rejected
      CANCELLED -> orphaned
      other     -> counted under the closest bucket or listed as-is
    """

    # Map OrderState values to outcome bucket names used in the summary header.
    _OUTCOME_BUCKETS: dict[str, str] = {
        OrderState.FILLED.value: "filled",
        OrderState.TIMED_OUT.value: "timeout",
        OrderState.FAILED.value: "rejected",
        OrderState.CANCELLED.value: "orphaned",
    }

    def __init__(self) -> None:
        self._events: list[OrderEvent] = []

    @beartype
    def on_event(self, event: OrderEvent) -> None:
        """Accumulate an event for the next flush."""
        self._events.append(event)

    @beartype
    def flush_summary(self) -> str:
        """
        Format and return a human-readable batch summary of accumulated events,
        then clear the internal buffer.

        The summary includes:
        - A header with per-outcome counts: filled: X  timeout: Y  rejected: Z  orphaned: W
        - Per-order lines grouped by outcome bucket.

        Returns an empty string if no events have been accumulated.
        """
        if not self._events:
            return ""

        # Count events per outcome bucket
        counts: dict[str, int] = {"filled": 0, "timeout": 0, "rejected": 0, "orphaned": 0}
        for evt in self._events:
            bucket = self._OUTCOME_BUCKETS.get(evt.state.value, "")
            if bucket in counts:
                counts[bucket] += 1

        count_header = (
            f"filled: {counts['filled']}  "
            f"timeout: {counts['timeout']}  "
            f"rejected: {counts['rejected']}  "
            f"orphaned: {counts['orphaned']}"
        )

        lines: list[str] = [
            "=== Order Batch Summary ===",
            count_header,
            "",
        ]
        for evt in self._events:
            fill_info = ""
            if evt.fill_price is not None and evt.fill_qty is not None:
                fill_info = f" fill={evt.fill_qty}@{evt.fill_price}"
            latency_info = f" latency={evt.latency_ms}ms" if evt.latency_ms is not None else ""
            lines.append(
                f"[{evt.state.value}] {evt.symbol} {evt.side} order={evt.order_id}{fill_info}{latency_info}"
            )
        self._events = []
        return "\n".join(lines)
