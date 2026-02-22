"""
Unit tests for RestApiOrderExecutor (step 02-01).

Test Budget: 5 behaviors x 2 = 10 max unit tests.

Behaviors:
  B1 - Adaptive polling: 0.2s in first 10s, 1.0s thereafter
  B2 - Exponential backoff on consecutive fetch_order failures
  B3 - request.params forwarded to create_limit/market_order
  B4 - ExecutionReport includes exchange_id and fill_latency_ms
  B5 - OrderEvent emitted via event_bus at each state transition
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.order import OrderRequest, OrderSide, OrderType
from traxon_core.crypto.models.order.execution_type import OrderExecutionType
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.event_bus import OrderEvent, OrderEventBus, OrderState
from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus
from traxon_core.crypto.order_executor.rest import RestApiOrderExecutor

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
    exchange.id = "bybit"
    exchange.api.fetch_open_orders = AsyncMock(return_value=[])
    exchange.api.cancel_order = AsyncMock(return_value={})
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
        params={"clientOrderId": "test-123"},
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
        params={"postOnly": "true"},
    )


def make_order_dict(status: str = "closed", filled: str = "0.1") -> dict:
    return {
        "id": "order-456",
        "symbol": "BTC/USDT",
        "status": status,
        "amount": "0.1",
        "filled": filled,
        "remaining": "0",
        "price": "50000",
        "lastTradePrice": None,
        "timestamp": 1700000000000,
    }


# ---------------------------------------------------------------------------
# B1 — Adaptive polling intervals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taker_order_uses_fast_polling_in_first_10_seconds(
    config, event_bus, mock_exchange, taker_request
):
    """Polling sleep should be 0.2s when elapsed < 10s (asserts via _adaptive_sleep_interval result)."""
    # Use an open order first, then closed, so the polling sleep is actually invoked
    open_order = make_order_dict(status="open", filled="0")
    closed_order = make_order_dict(status="closed")

    mock_exchange.api.create_market_order = AsyncMock(return_value={"id": "order-456", **open_order})
    mock_exchange.api.fetch_order = AsyncMock(side_effect=[open_order, closed_order])

    executor = RestApiOrderExecutor(config, event_bus=event_bus)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with patch("traxon_core.crypto.order_executor.rest.asyncio.sleep", side_effect=fake_sleep):
        with patch("traxon_core.crypto.order_executor.rest.datetime") as mock_dt:
            start = datetime(2026, 1, 1, 12, 0, 0)
            # Provide enough values: start_time, check_timeout(x2), _make_event(x2),
            # _poll_until_closed check_timeout(x2), elapsed(x2), _make_event(x2)
            mock_dt.now.return_value = start
            await executor.execute_taker_order(mock_exchange, taker_request)

    # All polling sleeps during first-10s window must be 0.2s
    polling_sleeps = [s for s in sleep_calls if s in (0.2, 1.0)]
    assert len(polling_sleeps) > 0, f"Expected at least one polling sleep, got {sleep_calls}"
    assert all(s == 0.2 for s in polling_sleeps), f"Expected all polling sleeps 0.2s, got {sleep_calls}"


@pytest.mark.asyncio
async def test_taker_order_uses_slow_polling_after_10_seconds(
    config, event_bus, mock_exchange, taker_request
):
    """Polling sleep should be 1.0s when elapsed >= 10s."""
    open_order = make_order_dict(status="open", filled="0")
    closed_order = make_order_dict(status="closed")

    mock_exchange.api.create_market_order = AsyncMock(return_value={"id": "order-456", **open_order})
    mock_exchange.api.fetch_order = AsyncMock(side_effect=[open_order, closed_order])

    executor = RestApiOrderExecutor(config, event_bus=event_bus)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with patch("traxon_core.crypto.order_executor.rest.asyncio.sleep", side_effect=fake_sleep):
        with patch("traxon_core.crypto.order_executor.rest.datetime") as mock_dt:
            start = datetime(2026, 1, 1, 12, 0, 0)
            # Return elapsed = 15s for all calls after start_time assignment
            after_10s = start + timedelta(seconds=15)
            # First call returns start (for start_time), all subsequent return after_10s
            mock_dt.now.side_effect = [start] + [after_10s] * 20
            await executor.execute_taker_order(mock_exchange, taker_request)

    polling_sleeps = [s for s in sleep_calls if s in (0.2, 1.0)]
    assert len(polling_sleeps) > 0, f"Expected at least one polling sleep, got {sleep_calls}"
    assert all(s == 1.0 for s in polling_sleeps), f"Expected all polling sleeps 1.0s, got {sleep_calls}"


# ---------------------------------------------------------------------------
# B2 — Exponential backoff on consecutive fetch_order failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_order_failures_trigger_exponential_backoff(
    config, event_bus, mock_exchange, taker_request
):
    """Consecutive fetch_order errors produce backoff delays [0.5, 1.0, 2.0, 4.0]."""
    mock_exchange.api.create_market_order = AsyncMock(return_value={"id": "order-456"})
    mock_exchange.api.fetch_order = AsyncMock(side_effect=Exception("network error"))

    executor = RestApiOrderExecutor(config, event_bus=event_bus)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with patch("traxon_core.crypto.order_executor.rest.asyncio.sleep", side_effect=fake_sleep):
        with pytest.raises(Exception):
            await executor.execute_taker_order(mock_exchange, taker_request)

    # Backoff delays must follow [0.5, 1.0, 2.0, 4.0] pattern
    backoff_delays = [0.5, 1.0, 2.0, 4.0]
    assert sleep_calls == backoff_delays, f"Expected backoff {backoff_delays}, got {sleep_calls}"


# ---------------------------------------------------------------------------
# B3 — request.params forwarded to exchange API calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taker_order_forwards_request_params_to_create_market_order(
    config, event_bus, mock_exchange, taker_request
):
    """request.params must be passed as 'params' arg to create_market_order."""
    closed_order = make_order_dict(status="closed")
    mock_exchange.api.create_market_order = AsyncMock(return_value={"id": "order-456", **closed_order})
    mock_exchange.api.fetch_order = AsyncMock(return_value=closed_order)

    executor = RestApiOrderExecutor(config, event_bus=event_bus)

    with patch("traxon_core.crypto.order_executor.rest.asyncio.sleep", new_callable=AsyncMock):
        await executor.execute_taker_order(mock_exchange, taker_request)

    mock_exchange.api.create_market_order.assert_called_once()
    call_kwargs = mock_exchange.api.create_market_order.call_args.kwargs
    assert call_kwargs["params"] == {"clientOrderId": "test-123"}


@pytest.mark.asyncio
async def test_maker_order_forwards_request_params_to_create_limit_order(
    config, event_bus, mock_exchange, maker_request
):
    """request.params must be passed as 'params' arg to create_limit_order."""
    order_book = {"bids": [[50000.0, 1.0]], "asks": [[50001.0, 1.0]]}
    closed_order = make_order_dict(status="closed")

    mock_exchange.api.fetch_order_book = AsyncMock(return_value=order_book)
    mock_exchange.api.create_limit_order = AsyncMock(return_value={"id": "order-456", **closed_order})
    mock_exchange.api.fetch_order = AsyncMock(return_value=closed_order)

    executor = RestApiOrderExecutor(config, event_bus=event_bus)

    with patch("traxon_core.crypto.order_executor.rest.asyncio.sleep", new_callable=AsyncMock):
        await executor.execute_maker_order(mock_exchange, maker_request)

    mock_exchange.api.create_limit_order.assert_called_once()
    call_kwargs = mock_exchange.api.create_limit_order.call_args.kwargs
    assert call_kwargs["params"] == {"postOnly": "true"}


# ---------------------------------------------------------------------------
# B4 — ExecutionReport includes exchange_id and fill_latency_ms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taker_order_report_includes_exchange_id_and_fill_latency(
    config, event_bus, mock_exchange, taker_request
):
    """Returned ExecutionReport must have exchange_id and fill_latency_ms >= 0."""
    closed_order = make_order_dict(status="closed")
    mock_exchange.api.create_market_order = AsyncMock(return_value={"id": "order-456", **closed_order})
    mock_exchange.api.fetch_order = AsyncMock(return_value=closed_order)
    mock_exchange.api.id = "bybit"

    executor = RestApiOrderExecutor(config, event_bus=event_bus)

    with patch("traxon_core.crypto.order_executor.rest.asyncio.sleep", new_callable=AsyncMock):
        report = await executor.execute_taker_order(mock_exchange, taker_request)

    assert report is not None
    assert report.exchange_id == "bybit"
    assert report.fill_latency_ms >= 0


# ---------------------------------------------------------------------------
# B5 — OrderEvent emitted via event_bus at each state transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taker_order_emits_submitted_and_fill_complete_events(config, mock_exchange, taker_request):
    """event_bus must receive order_submitted and order_fill_complete events."""
    closed_order = make_order_dict(status="closed")
    mock_exchange.api.create_market_order = AsyncMock(return_value={"id": "order-456", **closed_order})
    mock_exchange.api.fetch_order = AsyncMock(return_value=closed_order)
    mock_exchange.api.id = "bybit"

    bus = OrderEventBus()
    received_events: list[OrderEvent] = []

    class CaptureSink:
        def on_event(self, event: OrderEvent) -> None:
            received_events.append(event)

    bus.register_sink(CaptureSink())

    executor = RestApiOrderExecutor(config, event_bus=bus)

    with patch("traxon_core.crypto.order_executor.rest.asyncio.sleep", new_callable=AsyncMock):
        await executor.execute_taker_order(mock_exchange, taker_request)

    event_names = [e.event_name for e in received_events]
    assert "order_submitted" in event_names
    assert "order_fill_complete" in event_names


@pytest.mark.asyncio
async def test_taker_order_emits_order_failed_on_error(config, mock_exchange, taker_request):
    """event_bus must receive order_failed when order is rejected."""
    rejected_order = make_order_dict(status="rejected")
    mock_exchange.api.create_market_order = AsyncMock(return_value={"id": "order-456", **rejected_order})
    mock_exchange.api.fetch_order = AsyncMock(return_value=rejected_order)
    mock_exchange.api.id = "bybit"

    bus = OrderEventBus()
    received_events: list[OrderEvent] = []

    class CaptureSink:
        def on_event(self, event: OrderEvent) -> None:
            received_events.append(event)

    bus.register_sink(CaptureSink())

    executor = RestApiOrderExecutor(config, event_bus=bus)

    with patch("traxon_core.crypto.order_executor.rest.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(Exception):
            await executor.execute_taker_order(mock_exchange, taker_request)

    event_names = [e.event_name for e in received_events]
    assert "order_submitted" in event_names
    assert "order_failed" in event_names
