"""
Unit tests for WebSocketOrderExecutor (step 02-02).

Test Budget: 4 behaviors x 2 = 8 max unit tests.

Behaviors:
  B1 - asyncio.wait(FIRST_COMPLETED) drives monitoring loop — no asyncio.sleep as polling floor
  B2 - NetworkError triggers exponential backoff starting at 100ms, doubling, capped at 30s
  B3 - OrderTimeoutError calls execute_taker_fallback and emits order_timeout_fallback event
  B4 - CLOSED order status detected within one cycle of watch_orders returning
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.order import OrderRequest, OrderSide, OrderType
from traxon_core.crypto.models.order.execution_type import OrderExecutionType
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.event_bus import OrderEvent, OrderEventBus, OrderState
from traxon_core.crypto.order_executor.exceptions import OrderTimeoutError
from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus
from traxon_core.crypto.order_executor.ws import WebSocketOrderExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_order_dict(status: str = "closed", order_id: str = "ws-order-1") -> dict[str, Any]:
    return {
        "id": order_id,
        "symbol": "BTC/USDT",
        "status": status,
        "amount": "0.1",
        "filled": "0.1",
        "remaining": "0",
        "price": "50000",
        "lastTradePrice": None,
        "timestamp": 1700000000000,
    }


def make_closed_report() -> ExecutionReport:
    return ExecutionReport(
        id="ws-order-1",
        symbol="BTC/USDT",
        status=OrderStatus.CLOSED,
        amount=Decimal("0.1"),
        filled=Decimal("0.1"),
        remaining=Decimal("0"),
        average_price=Decimal("50000"),
        timestamp=1700000000000,
        exchange_id="bybit",
        fill_latency_ms=10,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> ExecutorConfig:
    return ExecutorConfig(execution=OrderExecutionStrategy.FAST, max_spread_pct=0.05)


@pytest.fixture
def event_bus() -> OrderEventBus:
    return OrderEventBus()


@pytest.fixture
def mock_exchange() -> MagicMock:
    exchange = MagicMock(spec=Exchange)
    exchange.api = MagicMock()
    exchange.api.id = "bybit"
    exchange.id = MagicMock()
    exchange.id.__str__ = MagicMock(return_value="bybit")
    exchange.has_ws_support = MagicMock(return_value=True)
    exchange.api.fetch_open_orders = AsyncMock(return_value=[])
    exchange.api.cancel_order = AsyncMock(return_value={})
    exchange.api.create_market_order = AsyncMock(return_value=make_order_dict("closed"))
    return exchange


@pytest.fixture
def taker_request() -> OrderRequest:
    return OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        amount=Decimal("0.1"),
        execution_type=OrderExecutionType.TAKER,
        exchange_id=ExchangeId.BYBIT,
    )


@pytest.fixture
def maker_request() -> OrderRequest:
    return OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        amount=Decimal("0.1"),
        price=Decimal("50000"),
        execution_type=OrderExecutionType.MAKER,
        exchange_id=ExchangeId.BYBIT,
    )


# ---------------------------------------------------------------------------
# B1 — asyncio.wait used for monitoring; no asyncio.sleep polling floor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maker_order_uses_asyncio_wait_not_sleep_for_monitoring(
    config: ExecutorConfig, event_bus: OrderEventBus, mock_exchange: MagicMock, maker_request: OrderRequest
) -> None:
    """The monitoring loop must suspend via asyncio.wait, not a polling asyncio.sleep."""
    order_book = {"bids": [[49999.0, 1.0]], "asks": [[50001.0, 1.0]]}
    mock_exchange.api.watch_order_book = AsyncMock(return_value=order_book)
    mock_exchange.api.watch_orders = AsyncMock(return_value=[make_order_dict("closed", "ws-order-1")])
    mock_exchange.api.create_limit_order = AsyncMock(
        return_value={"id": "ws-order-1", **make_order_dict("open", "ws-order-1")}
    )

    executor = WebSocketOrderExecutor(config, event_bus=event_bus)

    wait_called = False
    original_wait = asyncio.wait

    async def tracking_wait(fs: Any, **kwargs: Any) -> Any:
        nonlocal wait_called
        wait_called = True
        return await original_wait(fs, **kwargs)

    # Do NOT patch asyncio.sleep — the deadline task uses asyncio.sleep(remaining_seconds)
    # inside asyncio.wait, which is correct. Patching sleep would break the deadline task.
    with patch("traxon_core.crypto.order_executor.ws.asyncio.wait", side_effect=tracking_wait):
        report = await executor.execute_maker_order(mock_exchange, maker_request)

    assert wait_called, "asyncio.wait must be called in the monitoring loop"
    assert report is not None
    assert report.status == OrderStatus.CLOSED


@pytest.mark.asyncio
async def test_fill_detected_immediately_when_watch_orders_returns_closed(
    config: ExecutorConfig, event_bus: OrderEventBus, mock_exchange: MagicMock, maker_request: OrderRequest
) -> None:
    """Fill detection completes within a small number of asyncio.wait cycles — no polling floor."""
    order_book = {"bids": [[49999.0, 1.0]], "asks": [[50001.0, 1.0]]}
    mock_exchange.api.watch_order_book = AsyncMock(return_value=order_book)
    mock_exchange.api.watch_orders = AsyncMock(return_value=[make_order_dict("closed", "ws-order-1")])
    mock_exchange.api.create_limit_order = AsyncMock(
        return_value={"id": "ws-order-1", **make_order_dict("open", "ws-order-1")}
    )

    executor = WebSocketOrderExecutor(config, event_bus=event_bus)

    # Measure how many asyncio.wait calls it takes — should be minimal (not polling-floor-many)
    wait_count = 0
    original_wait = asyncio.wait

    async def counting_wait(fs: Any, **kwargs: Any) -> Any:
        nonlocal wait_count
        wait_count += 1
        return await original_wait(fs, **kwargs)

    with patch("traxon_core.crypto.order_executor.ws.asyncio.wait", side_effect=counting_wait):
        report = await executor.execute_maker_order(mock_exchange, maker_request)

    assert report.status == OrderStatus.CLOSED
    # Fill detection should happen within a small number of wait cycles
    # (book update + order placed + fill = ~3 cycles)
    assert wait_count <= 10, f"Expected <= 10 asyncio.wait calls for immediate fill, got {wait_count}"


# ---------------------------------------------------------------------------
# B2 — NetworkError triggers exponential backoff + ws_reconnect_attempt events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_error_triggers_exponential_backoff_delays(
    config: ExecutorConfig, mock_exchange: MagicMock, maker_request: OrderRequest
) -> None:
    """On NetworkError, reconnect delays follow 0.1, 0.2, 0.4, ... capped at 30s."""
    from ccxt.base.errors import NetworkError  # type: ignore[import-untyped]

    order_book = {"bids": [[49999.0, 1.0]], "asks": [[50001.0, 1.0]]}
    closed_orders = [make_order_dict("closed", "ws-order-1")]

    # watch_orders raises NetworkError 3 times, then succeeds
    mock_exchange.api.watch_orders = AsyncMock(
        side_effect=[
            NetworkError("connection lost"),
            NetworkError("connection lost"),
            NetworkError("connection lost"),
            closed_orders,
        ]
    )
    mock_exchange.api.watch_order_book = AsyncMock(return_value=order_book)
    mock_exchange.api.create_limit_order = AsyncMock(
        return_value={"id": "ws-order-1", **make_order_dict("open", "ws-order-1")}
    )

    executor = WebSocketOrderExecutor(config)

    # Patch asyncio.sleep only inside _watch_orders_with_backoff context by tracking calls.
    # We must allow the deadline asyncio.sleep to run normally, so we capture but forward calls.
    sleep_calls: list[float] = []
    original_sleep = asyncio.sleep

    async def capture_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Only skip the actual sleep for backoff delays (< 1s); let deadline sleep run
        if seconds < 1.0:
            return
        await original_sleep(seconds)

    with patch("traxon_core.crypto.order_executor.ws.asyncio.sleep", side_effect=capture_sleep):
        await executor.execute_maker_order(mock_exchange, maker_request)

    # Filter to only backoff sleep calls (< 1s)
    backoff_calls = [s for s in sleep_calls if s < 1.0]
    # First 3 sleeps must be exponential backoff: 0.1, 0.2, 0.4
    assert len(backoff_calls) >= 3, (
        f"Expected >= 3 backoff sleeps, got backoff_calls={backoff_calls}, all={sleep_calls}"
    )
    assert backoff_calls[0] == pytest.approx(0.1), f"First backoff must be 100ms, got {backoff_calls[0]}"
    assert backoff_calls[1] == pytest.approx(0.2), f"Second backoff must be 200ms, got {backoff_calls[1]}"
    assert backoff_calls[2] == pytest.approx(0.4), f"Third backoff must be 400ms, got {backoff_calls[2]}"


@pytest.mark.asyncio
async def test_network_error_emits_ws_reconnect_attempt_events(
    config: ExecutorConfig, maker_request: OrderRequest, mock_exchange: MagicMock
) -> None:
    """Each NetworkError reconnect attempt emits a ws_reconnect_attempt OrderEvent."""
    from ccxt.base.errors import NetworkError  # type: ignore[import-untyped]

    order_book = {"bids": [[49999.0, 1.0]], "asks": [[50001.0, 1.0]]}
    closed_orders = [make_order_dict("closed", "ws-order-1")]

    mock_exchange.api.watch_orders = AsyncMock(
        side_effect=[
            NetworkError("ws dropped"),
            NetworkError("ws dropped"),
            closed_orders,
        ]
    )
    mock_exchange.api.watch_order_book = AsyncMock(return_value=order_book)
    mock_exchange.api.create_limit_order = AsyncMock(
        return_value={"id": "ws-order-1", **make_order_dict("open", "ws-order-1")}
    )

    bus = OrderEventBus()
    received_events: list[OrderEvent] = []

    class CaptureSink:
        def on_event(self, event: OrderEvent) -> None:
            received_events.append(event)

    bus.register_sink(CaptureSink())
    executor = WebSocketOrderExecutor(config, event_bus=bus)

    # Allow backoff sleeps to complete quickly, preserve deadline sleep
    original_sleep = asyncio.sleep

    async def fast_backoff_sleep(seconds: float) -> None:
        if seconds < 1.0:
            return  # Skip actual wait for backoff delays in test
        await original_sleep(seconds)

    with patch("traxon_core.crypto.order_executor.ws.asyncio.sleep", side_effect=fast_backoff_sleep):
        await executor.execute_maker_order(mock_exchange, maker_request)

    reconnect_events = [e for e in received_events if e.event_name == "ws_reconnect_attempt"]
    assert len(reconnect_events) == 2, (
        f"Expected 2 ws_reconnect_attempt events (one per NetworkError), got {len(reconnect_events)}"
    )
    # Verify attempt numbers are sequential
    attempt_numbers = [e.latency_ms for e in reconnect_events]  # latency_ms stores attempt number
    assert attempt_numbers == [1, 2], f"Expected attempt numbers [1, 2], got {attempt_numbers}"


# ---------------------------------------------------------------------------
# B3 — OrderTimeoutError calls execute_taker_fallback + order_timeout_fallback event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_triggers_taker_fallback_and_returns_execution_report(
    config: ExecutorConfig, maker_request: OrderRequest, mock_exchange: MagicMock
) -> None:
    """On OrderTimeoutError, execute_taker_fallback is called and returns ExecutionReport."""
    # watch_order_book returns immediately with valid data
    mock_exchange.api.watch_order_book = AsyncMock(
        return_value={"bids": [[49999.0, 1.0]], "asks": [[50001.0, 1.0]]}
    )

    # watch_orders blocks forever (never resolves); timeout will fire via deadline task
    async def blocking_watch_orders(_symbol: str) -> list[Any]:
        await asyncio.sleep(3600)
        return []  # pragma: no cover

    mock_exchange.api.watch_orders = blocking_watch_orders
    mock_exchange.api.create_limit_order = AsyncMock(
        return_value={"id": "ws-order-1", **make_order_dict("open", "ws-order-1")}
    )

    executor = WebSocketOrderExecutor(config)
    # Very short timeout so deadline fires quickly in real time
    import datetime as dt

    executor.timeout_duration = dt.timedelta(milliseconds=50)

    fallback_report = make_closed_report()
    executor.execute_taker_fallback = AsyncMock(return_value=fallback_report)  # type: ignore[method-assign]

    result = await executor.execute_maker_order(mock_exchange, maker_request)

    assert result is not None
    assert result.status == OrderStatus.CLOSED
    executor.execute_taker_fallback.assert_called_once()


@pytest.mark.asyncio
async def test_timeout_emits_order_timeout_fallback_event(
    config: ExecutorConfig, maker_request: OrderRequest, mock_exchange: MagicMock
) -> None:
    """On OrderTimeoutError, order_timeout_fallback event is emitted before returning."""
    mock_exchange.api.watch_order_book = AsyncMock(
        return_value={"bids": [[49999.0, 1.0]], "asks": [[50001.0, 1.0]]}
    )

    # watch_orders blocks forever; deadline fires after short timeout
    async def blocking_watch_orders_2(_symbol: str) -> list[Any]:
        await asyncio.sleep(3600)
        return []  # pragma: no cover

    mock_exchange.api.watch_orders = blocking_watch_orders_2
    mock_exchange.api.create_limit_order = AsyncMock(
        return_value={"id": "ws-order-1", **make_order_dict("open", "ws-order-1")}
    )
    mock_exchange.api.create_market_order = AsyncMock(
        return_value={"id": "fb-order-1", **make_order_dict("closed", "fb-order-1")}
    )

    bus = OrderEventBus()
    received_events: list[OrderEvent] = []

    class CaptureSink:
        def on_event(self, event: OrderEvent) -> None:
            received_events.append(event)

    bus.register_sink(CaptureSink())
    executor = WebSocketOrderExecutor(config, event_bus=bus)
    import datetime as dt

    executor.timeout_duration = dt.timedelta(milliseconds=50)

    await executor.execute_maker_order(mock_exchange, maker_request)

    timeout_events = [e for e in received_events if e.event_name == "order_timeout_fallback"]
    assert len(timeout_events) >= 1, (
        f"Expected at least one order_timeout_fallback event, got event_names={[e.event_name for e in received_events]}"
    )


# ---------------------------------------------------------------------------
# B4 — execute_taker_fallback in base.py: shared method behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_taker_fallback_creates_market_order_and_returns_report(
    config: ExecutorConfig, mock_exchange: MagicMock, taker_request: OrderRequest
) -> None:
    """execute_taker_fallback places a REST market order and returns ExecutionReport."""
    closed_dict = make_order_dict("closed", "fb-order-1")
    mock_exchange.api.create_market_order = AsyncMock(return_value=closed_dict)

    executor = WebSocketOrderExecutor(config)

    report = await executor.execute_taker_fallback(mock_exchange, taker_request, "ws_timeout")

    assert report is not None
    assert report.status == OrderStatus.CLOSED
    mock_exchange.api.create_market_order.assert_called_once()


@pytest.mark.asyncio
async def test_execute_taker_fallback_emits_order_timeout_fallback_event(
    config: ExecutorConfig, mock_exchange: MagicMock, taker_request: OrderRequest
) -> None:
    """execute_taker_fallback emits order_timeout_fallback event via event_bus."""
    closed_dict = make_order_dict("closed", "fb-order-1")
    mock_exchange.api.create_market_order = AsyncMock(return_value=closed_dict)

    bus = OrderEventBus()
    received_events: list[OrderEvent] = []

    class CaptureSink:
        def on_event(self, event: OrderEvent) -> None:
            received_events.append(event)

    bus.register_sink(CaptureSink())
    executor = WebSocketOrderExecutor(config, event_bus=bus)

    await executor.execute_taker_fallback(mock_exchange, taker_request, "ws_timeout")

    timeout_events = [e for e in received_events if e.event_name == "order_timeout_fallback"]
    assert len(timeout_events) == 1, f"Expected 1 order_timeout_fallback event, got {len(timeout_events)}"
