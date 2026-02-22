"""
Integration tests validating the full DefaultOrderExecutor stack.
Tests criteria from roadmap step 04-02.

Acceptance criteria:
1. All pre-existing unit and integration tests pass without modification to test logic.
2. The Telegram batch summary includes per-outcome counts (filled, timeout, rejected, orphaned)
   and per-order lines for every outcome.
3. A multi-exchange batch (two distinct exchange_ids) produces ExecutionReport entries
   with correctly distinct exchange_id values.
4. WS executor routes to REST via ExchangeSession after circuit opens, confirmed by
   exchange API call counts in an integration test.
5. DefaultOrderExecutor.execute_orders accepts the same arguments as before the refactor
   and returns list[ExecutionReport].
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from traxon_core.crypto.exchanges.config import ExchangeApiConnection
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import ExchangeId, OrderSide, OrdersToExecute, SizedOrderBuilder
from traxon_core.crypto.models.market_info import MarketInfo
from traxon_core.crypto.models.order import OrderExecutionType
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor
from traxon_core.crypto.order_executor.event_bus import OrderEvent, OrderEventBus, OrderState, TelegramSink
from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus
from traxon_core.crypto.order_executor.session import ExchangeSession

# ---------------------------------------------------------------------------
# Test helpers shared across tests
# ---------------------------------------------------------------------------


class _FakeExchange(Exchange):
    """Minimal Exchange subclass for integration tests — bypasses Exchange.__init__."""

    def __init__(self, exchange_id: ExchangeId = ExchangeId.BYBIT, ws_support: bool = False) -> None:
        self.api = MagicMock()
        self.api.id = exchange_id.value
        self._exchange_id = exchange_id
        self._ws_support = ws_support
        self.api_connection = ExchangeApiConnection.WEBSOCKET if ws_support else ExchangeApiConnection.REST
        self.leverage = 1

    @property
    def id(self) -> ExchangeId:
        return self._exchange_id

    def has_ws_support(self) -> bool:
        return self._ws_support


def _make_market_info(symbol: str = "BTC/USDT") -> MarketInfo:
    """Build a standard MarketInfo for the given symbol."""
    ccxt_market = {
        "symbol": symbol,
        "type": "swap",
        "active": True,
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
        "precision": {"amount": 8, "price": 2},
    }
    return MarketInfo.from_ccxt(ccxt_market)


def _make_filled_order_response(
    order_id: str,
    symbol: str,
    submit_timestamp_ms: int = 1_700_000_000_000,
    fill_latency_ms: int = 1200,
    price: float = 43200.0,
) -> dict[str, Any]:
    """Build a CCXT-format filled order dict."""
    return {
        "id": order_id,
        "symbol": symbol,
        "status": "closed",
        "amount": 0.1,
        "filled": 0.1,
        "remaining": 0.0,
        "average": price,
        "price": price,
        "fee": {"cost": 0.001, "currency": "USDT"},
        "timestamp": submit_timestamp_ms + fill_latency_ms,
        "info": {},
    }


def _configure_rest_exchange(
    exchange: _FakeExchange,
    order_id: str,
    symbol: str,
    price: float = 43200.0,
) -> _FakeExchange:
    """Wire AsyncMock methods on the exchange API to simulate a taker fill."""
    submit_ms = 1_700_000_000_000
    filled_order = _make_filled_order_response(
        order_id=order_id,
        symbol=symbol,
        submit_timestamp_ms=submit_ms,
        price=price,
    )
    exchange.api.has = {"setMarginMode": True, "setLeverage": True}
    exchange.api.set_margin_mode = AsyncMock(return_value=None)
    exchange.api.set_leverage = AsyncMock(return_value=None)
    exchange.api.create_market_order = AsyncMock(return_value=filled_order)
    exchange.api.fetch_order = AsyncMock(return_value=filled_order)
    exchange.api.fetch_open_orders = AsyncMock(return_value=[])
    exchange.api.cancel_order = AsyncMock(return_value=None)
    return exchange


def _make_taker_order(
    exchange_id: ExchangeId,
    market: MarketInfo,
    side: OrderSide = OrderSide.BUY,
    size: Decimal = Decimal("0.1"),
) -> SizedOrderBuilder:
    """Build a taker SizedOrderBuilder with asyncio events wired."""
    builder = SizedOrderBuilder(
        exchange_id=exchange_id,
        market=market,
        execution_type=OrderExecutionType.TAKER,
        side=side,
        size=size,
    )
    builder.pairing.set_events(asyncio.Event(), asyncio.Event())
    return builder


def _group_builders(builders: list[SizedOrderBuilder]) -> OrdersToExecute:
    """Group builders into OrdersToExecute by BaseQuote."""
    from collections import defaultdict

    from traxon_core.crypto.models.order.builder import OrderBuilder
    from traxon_core.crypto.models.symbol import BaseQuote

    grouped: dict[BaseQuote, list[OrderBuilder]] = defaultdict(list)
    for b in builders:
        bq = b.market.symbol.base_quote
        grouped[bq].append(b)

    return OrdersToExecute(updates={}, new=dict(grouped))


def _make_executor_config(max_ws_reconnect_attempts: int = 5) -> ExecutorConfig:
    """Build a fast ExecutorConfig."""
    return ExecutorConfig(
        execution=OrderExecutionStrategy.FAST,
        max_spread_pct=0.05,
        max_ws_reconnect_attempts=max_ws_reconnect_attempts,
    )


def _make_telegram_event(
    order_id: str,
    exchange_id: str,
    symbol: str,
    side: str,
    state: OrderState,
) -> OrderEvent:
    """Build an OrderEvent for TelegramSink testing."""
    return OrderEvent(
        order_id=order_id,
        exchange_id=exchange_id,
        symbol=symbol,
        side=side,
        state=state,
        timestamp_ms=1_700_000_000_000,
        event_name=state.value.lower(),
        latency_ms=None,
        fill_price=None,
        fill_qty=None,
    )


# ---------------------------------------------------------------------------
# Test 1: AC3 — multi-exchange batch returns distinct exchange_id values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_exchange_batch_returns_distinct_exchange_ids() -> None:
    """
    A batch with orders on two distinct exchanges produces ExecutionReports
    with correctly distinct exchange_id values.

    Acceptance criterion 3: multi-exchange batch has exchange_id-distinct reports.
    Acceptance criterion 5: execute_orders signature unchanged, returns list[ExecutionReport].
    """
    # --- Arrange ---------------------------------------------------------
    bybit = _FakeExchange(exchange_id=ExchangeId.BYBIT, ws_support=False)
    _configure_rest_exchange(bybit, order_id="ord-bybit-001", symbol="BTC/USDT", price=43200.0)

    hyperliquid = _FakeExchange(exchange_id=ExchangeId.HYPERLIQUID, ws_support=False)
    _configure_rest_exchange(hyperliquid, order_id="ord-hl-001", symbol="BTC/USDT", price=43150.0)

    market_btc = _make_market_info("BTC/USDT")

    bybit_order = _make_taker_order(ExchangeId.BYBIT, market_btc)
    hl_order = _make_taker_order(ExchangeId.HYPERLIQUID, market_btc)

    orders = _group_builders([bybit_order, hl_order])

    config = _make_executor_config()
    executor = DefaultOrderExecutor(config)
    event_bus = OrderEventBus()
    executor._event_bus = event_bus

    # --- Act (AC5: same public API as before refactor) -------------------
    reports: list[ExecutionReport] = await executor.execute_orders(
        exchanges=[bybit, hyperliquid],
        orders=orders,
    )

    # --- Assert: AC3 — two reports with distinct exchange_ids ------------
    assert len(reports) == 2, f"Expected 2 reports, got {len(reports)}: {reports}"

    exchange_ids = {r.exchange_id for r in reports}
    assert "bybit" in exchange_ids, f"Expected 'bybit' in exchange_ids, got {exchange_ids}"
    assert "hyperliquid" in exchange_ids, f"Expected 'hyperliquid' in exchange_ids, got {exchange_ids}"

    # All reports must be CLOSED
    for report in reports:
        assert report.status == OrderStatus.CLOSED, (
            f"Expected CLOSED for {report.exchange_id}, got {report.status}"
        )

    # Each exchange_id must be non-empty
    for report in reports:
        assert report.exchange_id, "exchange_id must not be empty"


# ---------------------------------------------------------------------------
# Test 2: AC4 — WS circuit breaker routes to REST after circuit opens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_routes_to_rest_after_circuit_opens() -> None:
    """
    After max_ws_reconnect_attempts WS NetworkError failures, the ExchangeSession
    circuit breaker opens, and subsequent orders route to REST.

    Acceptance criterion 4: WS executor routes to REST via ExchangeSession after
    circuit opens, confirmed by exchange API call counts.

    Implementation: uses ExchangeSession directly (as noted in task instructions)
    to isolate the circuit breaker logic without the full DefaultOrderExecutor stack
    complexity at the WS layer.
    """
    from ccxt.base.errors import NetworkError  # type: ignore[import-untyped]

    from traxon_core.crypto.order_executor.ws import CircuitOpenError, WebSocketOrderExecutor

    # --- Arrange: WS exchange that fails watch_orders -------------------
    exchange = _FakeExchange(exchange_id=ExchangeId.BYBIT, ws_support=True)
    exchange.api.has = {}

    submit_ms = 1_700_000_000_000
    closed_order = _make_filled_order_response(
        order_id="ord-ws-001",
        symbol="BTC/USDT",
        submit_timestamp_ms=submit_ms,
    )
    exchange.api.set_margin_mode = AsyncMock(return_value=None)
    exchange.api.set_leverage = AsyncMock(return_value=None)
    exchange.api.fetch_open_orders = AsyncMock(return_value=[])
    exchange.api.cancel_order = AsyncMock(return_value=None)
    exchange.api.create_market_order = AsyncMock(return_value=closed_order)
    exchange.api.fetch_order = AsyncMock(return_value=closed_order)

    # watch_order_book returns immediately (for session.initialize)
    exchange.api.watch_order_book = AsyncMock(
        return_value={"bids": [[43200.0, 1.0]], "asks": [[43201.0, 1.0]]}
    )

    # watch_orders raises NetworkError exactly max_ws_reconnect_attempts times
    max_attempts = 2
    network_errors = [NetworkError("connection refused")] * max_attempts

    exchange.api.watch_orders = AsyncMock(side_effect=network_errors)

    config = ExecutorConfig(
        execution=OrderExecutionStrategy.FAST,
        max_spread_pct=0.05,
        max_ws_reconnect_attempts=max_attempts,
    )

    event_bus = OrderEventBus()
    session = ExchangeSession(
        exchange=exchange,
        event_bus=event_bus,
        max_concurrent_orders=5,
    )

    ws_executor = WebSocketOrderExecutor(config, event_bus=event_bus)

    # --- Act: call _watch_orders_with_backoff which should open circuit ---
    with pytest.raises(CircuitOpenError) as exc_info:
        await ws_executor._watch_orders_with_backoff(
            exchange=exchange,
            symbol="BTC/USDT",
            order_id="ord-ws-001",
            log_prefix="bybit BTC/USDT BUY",
            exchange_id="bybit",
            start_time=__import__("datetime").datetime.now(),
            session=session,
        )

    # --- Assert: circuit opened -------------------------------------------
    assert exc_info.value.attempts == max_attempts, (
        f"Expected {max_attempts} attempts, got {exc_info.value.attempts}"
    )
    assert session.is_circuit_open(), "ExchangeSession circuit must be open after max failures"

    # --- Assert: watch_orders was called exactly max_attempts times ------
    assert exchange.api.watch_orders.call_count == max_attempts, (
        f"Expected watch_orders called {max_attempts} times, got {exchange.api.watch_orders.call_count}"
    )

    # --- Assert: after circuit open, _select_executor returns REST -------
    from traxon_core.crypto.order_executor.router import OrderRouter

    router = OrderRouter(config, event_bus=event_bus)
    executor_selected = router._select_executor(exchange, session)

    from traxon_core.crypto.order_executor.rest import RestApiOrderExecutor

    assert isinstance(executor_selected, RestApiOrderExecutor), (
        f"After circuit open, expected RestApiOrderExecutor, got {type(executor_selected).__name__}"
    )


# ---------------------------------------------------------------------------
# Test 3: AC2 — TelegramSink.flush_summary() format validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_sink_flush_summary_format() -> None:
    """
    TelegramSink.flush_summary() returns a string with:
    - Per-outcome counts: filled X, timeout Y, rejected Z, orphaned W
    - Per-order lines for each outcome group

    Acceptance criterion 2: Telegram batch summary includes per-outcome counts
    and per-order lines for every outcome.
    """
    # --- Arrange: create a TelegramSink and register it to an event bus --
    sink = TelegramSink()
    event_bus = OrderEventBus()
    event_bus.register_sink(sink)

    # Emit events covering four distinct outcomes:
    # 1 FILLED, 1 TIMED_OUT, 1 FAILED (rejected), 1 CANCELLED (orphaned)
    filled_event = OrderEvent(
        order_id="order-filled-1",
        exchange_id="bybit",
        symbol="BTC/USDT",
        side="buy",
        state=OrderState.FILLED,
        timestamp_ms=1_700_000_001_000,
        event_name="order_fill_complete",
        latency_ms=1200,
        fill_price=Decimal("43200.00"),
        fill_qty=Decimal("0.1"),
    )
    timeout_event = OrderEvent(
        order_id="order-timeout-1",
        exchange_id="bybit",
        symbol="ETH/USDT",
        side="sell",
        state=OrderState.TIMED_OUT,
        timestamp_ms=1_700_000_002_000,
        event_name="order_timeout",
        latency_ms=None,
        fill_price=None,
        fill_qty=None,
    )
    rejected_event = OrderEvent(
        order_id="order-rejected-1",
        exchange_id="hyperliquid",
        symbol="SOL/USDT",
        side="buy",
        state=OrderState.FAILED,
        timestamp_ms=1_700_000_003_000,
        event_name="order_failed",
        latency_ms=None,
        fill_price=None,
        fill_qty=None,
    )
    orphaned_event = OrderEvent(
        order_id="order-orphaned-1",
        exchange_id="bybit",
        symbol="BTC/USDT",
        side="sell",
        state=OrderState.CANCELLED,
        timestamp_ms=1_700_000_004_000,
        event_name="order_cancelled",
        latency_ms=None,
        fill_price=None,
        fill_qty=None,
    )

    event_bus.emit(filled_event)
    event_bus.emit(timeout_event)
    event_bus.emit(rejected_event)
    event_bus.emit(orphaned_event)

    # --- Act: flush_summary must include per-outcome counts --------------
    summary = sink.flush_summary()

    # --- Assert: non-empty -----------------------------------------------
    assert summary, "flush_summary() must not return empty string after events are emitted"

    # --- Assert: per-outcome count header present -----------------------
    # The summary must contain "filled: N  timeout: N  rejected: N  orphaned: N"
    # on a dedicated counts line. This validates the aggregate count format.
    assert "filled: 1" in summary, f"Expected 'filled: 1' count in summary header.\nSummary:\n{summary}"
    assert "timeout: 1" in summary, f"Expected 'timeout: 1' count in summary header.\nSummary:\n{summary}"
    assert "rejected: 1" in summary, f"Expected 'rejected: 1' count in summary header.\nSummary:\n{summary}"
    assert "orphaned: 1" in summary, f"Expected 'orphaned: 1' count in summary header.\nSummary:\n{summary}"

    # --- Assert: per-order lines present — all 4 order_ids in summary ---
    assert "order-filled-1" in summary, f"Expected 'order-filled-1' in per-order lines.\nSummary:\n{summary}"
    assert "order-timeout-1" in summary, (
        f"Expected 'order-timeout-1' in per-order lines.\nSummary:\n{summary}"
    )
    assert "order-rejected-1" in summary, (
        f"Expected 'order-rejected-1' in per-order lines.\nSummary:\n{summary}"
    )
    assert "order-orphaned-1" in summary, (
        f"Expected 'order-orphaned-1' in per-order lines.\nSummary:\n{summary}"
    )

    # --- Assert: flush clears the buffer — second call returns empty -----
    second_summary = sink.flush_summary()
    assert second_summary == "", (
        f"Expected empty string on second flush_summary() call, got: {second_summary!r}"
    )
