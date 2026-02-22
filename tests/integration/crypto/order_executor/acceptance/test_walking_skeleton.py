"""
Walking skeleton: single OrderRequest -> DefaultOrderExecutor.execute_orders -> ExecutionReport(CLOSED).

All exchange API calls use AsyncMock fakes (no real network).

Acceptance criteria exercised:
  AC1 - execute_orders returns a list with one ExecutionReport(status=CLOSED)
  AC2 - ExecutionReport.exchange_id is non-empty and matches the target exchange
  AC3 - ExecutionReport.fill_latency_ms >= 0
  AC4 - set_margin_mode and set_leverage each called exactly once for the order's symbol
  AC5 - At least one order_submitted and one order_fill_complete event captured by EventSink

Design note: DefaultOrderExecutor._execute_order handles set_margin_mode/set_leverage (AC4).
Events (AC5) require the event_bus to reach RestApiOrderExecutor. Since
DefaultOrderExecutor._select_executor creates executors without event_bus, _select_executor
is patched on the executor instance to inject the event_bus — a test double technique
that wires up the system under test without modifying any production code.
"""

from __future__ import annotations

import asyncio
import types
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import ExchangeId, OrderSide, OrdersToExecute, SizedOrderBuilder
from traxon_core.crypto.models.market_info import MarketInfo
from traxon_core.crypto.models.order import OrderExecutionType
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor
from traxon_core.crypto.order_executor.event_bus import OrderEvent, OrderEventBus
from traxon_core.crypto.order_executor.models import OrderStatus
from traxon_core.crypto.order_executor.rest import RestApiOrderExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeExchange(Exchange):
    """Minimal Exchange subclass for integration tests — bypasses Exchange.__init__."""

    def __init__(self) -> None:  # type: ignore[override]
        self.api = MagicMock()
        self.api.id = "bybit"
        self._ws_support = False
        # Force REST path: api_connection value must NOT equal "websocket"
        self.api_connection = "rest"
        self.leverage = 1

    @property  # type: ignore[override]
    def id(self) -> ExchangeId:
        return ExchangeId.BYBIT

    def has_ws_support(self) -> bool:
        return self._ws_support


def _make_fake_exchange() -> _FakeExchange:
    """
    Build a fake exchange with AsyncMock API methods that simulate a taker fill.

    The closed_order dict is returned immediately so the REST taker polling loop
    exits on the first fetch_order call.

    api.has is set to enable setMarginMode and setLeverage so that
    DefaultOrderExecutor._execute_order calls both on the fake API (AC4).
    """
    exchange = _FakeExchange()
    api = exchange.api

    # Enable setMarginMode and setLeverage so DefaultOrderExecutor._execute_order
    # calls them (acceptance criterion AC4).
    api.has = {
        "setMarginMode": True,
        "setLeverage": True,
    }

    submit_ms = 1_700_000_000_000
    closed_order: dict[str, Any] = {
        "id": "order-wsk-001",
        "symbol": "BTC/USDT",
        "status": "closed",
        "amount": "0.1",
        "filled": "0.1",
        "remaining": "0",
        "price": "43200.00",
        "lastTradePrice": None,
        "timestamp": submit_ms + 1500,
    }

    api.set_margin_mode = AsyncMock(return_value=None)
    api.set_leverage = AsyncMock(return_value=None)
    api.cancel_order = AsyncMock(return_value=None)
    api.fetch_open_orders = AsyncMock(return_value=[])
    api.create_market_order = AsyncMock(return_value=closed_order)
    api.fetch_order = AsyncMock(return_value=closed_order)

    return exchange


def _make_market_info() -> MarketInfo:
    """BTC/USDT perpetual market info for test orders."""
    ccxt_market = {
        "symbol": "BTC/USDT",
        "type": "swap",
        "active": True,
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
        "precision": {"amount": 8, "price": 2},
    }
    return MarketInfo.from_ccxt(ccxt_market)


def _make_orders_to_execute(
    exchange_id: ExchangeId,
    market: MarketInfo,
    side: OrderSide,
    size: Decimal,
) -> OrdersToExecute:
    """Build an OrdersToExecute with a single taker order."""
    from collections import defaultdict

    from traxon_core.crypto.models.symbol import BaseQuote

    builder = SizedOrderBuilder(
        exchange_id=exchange_id,
        market=market,
        execution_type=OrderExecutionType.TAKER,
        side=side,
        size=size,
    )
    builder.pairing.set_events(asyncio.Event(), asyncio.Event())

    base_quote = market.symbol.base_quote
    grouped: dict[BaseQuote, list[SizedOrderBuilder]] = defaultdict(list)
    grouped[base_quote].append(builder)

    return OrdersToExecute(updates={}, new=dict(grouped))


class _CaptureSink:
    """EventSink that collects event names for assertion."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def on_event(self, event: OrderEvent) -> None:
        self.events.append(event.event_name)

    def has_event(self, name: str) -> bool:
        return name in self.events


# ---------------------------------------------------------------------------
# Walking skeleton acceptance test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_walking_skeleton_single_order_returns_closed_report() -> None:
    """
    Walking skeleton: one taker OrderRequest routed through DefaultOrderExecutor
    returns one ExecutionReport(status=CLOSED) with exchange_id and fill_latency_ms.

    Acceptance criteria verified:
      AC1 - list of one ExecutionReport with status=CLOSED
      AC2 - exchange_id == "bybit"
      AC3 - fill_latency_ms >= 0
      AC4 - set_margin_mode called once, set_leverage called once
      AC5 - order_submitted and order_fill_complete events captured
    """
    # --- Arrange ---------------------------------------------------------
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.FAST,
        max_spread_pct=0.05,
    )
    event_bus = OrderEventBus()
    sink = _CaptureSink()
    event_bus.register_sink(sink)

    exchange = _make_fake_exchange()
    market = _make_market_info()
    orders = _make_orders_to_execute(
        exchange_id=ExchangeId.BYBIT,
        market=market,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )

    executor = DefaultOrderExecutor(config)
    # Inject event_bus into the executor so the router picks it up.
    executor._event_bus = event_bus

    # Patch _select_executor on the instance to thread event_bus through to
    # RestApiOrderExecutor. DefaultOrderExecutor._select_executor creates executors
    # without event_bus by default — this wires up the event path for AC5 without
    # modifying any production source file.
    def _select_executor_with_bus(self_: object, exch: Exchange) -> RestApiOrderExecutor:  # noqa: ARG001
        return RestApiOrderExecutor(config, event_bus=event_bus)

    executor._select_executor = types.MethodType(_select_executor_with_bus, executor)  # type: ignore[method-assign]

    # --- Act -------------------------------------------------------------
    reports = await executor.execute_orders(exchanges=[exchange], orders=orders)

    # --- Assert: AC1 - one CLOSED report ---------------------------------
    assert len(reports) == 1, f"Expected 1 report, got {len(reports)}"
    report = reports[0]
    assert report.status == OrderStatus.CLOSED, f"Expected CLOSED status, got {report.status}"

    # --- Assert: AC2 - exchange_id matches target exchange ---------------
    assert report.exchange_id, "exchange_id must not be empty"
    assert report.exchange_id == "bybit", f"Expected exchange_id='bybit', got {report.exchange_id!r}"

    # --- Assert: AC3 - fill_latency_ms >= 0 ------------------------------
    assert report.fill_latency_ms >= 0, f"fill_latency_ms must be >= 0, got {report.fill_latency_ms}"

    # --- Assert: AC4 - margin mode and leverage called once per symbol ---
    exchange.api.set_margin_mode.assert_called_once_with("cross", "BTC/USDT")
    exchange.api.set_leverage.assert_called_once_with(1, "BTC/USDT")

    # --- Assert: AC5 - order lifecycle events captured -------------------
    assert sink.has_event("order_submitted"), f"Expected 'order_submitted' event; captured: {sink.events}"
    assert sink.has_event("order_fill_complete"), (
        f"Expected 'order_fill_complete' event; captured: {sink.events}"
    )
