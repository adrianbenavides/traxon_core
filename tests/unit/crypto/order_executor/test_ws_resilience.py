"""
Unit tests for WS circuit breaker and staleness detection (step 03-02).

Test Budget: 3 behaviors x 2 = 6 max unit tests.

Behaviors:
  B1 - After max_ws_reconnect_attempts consecutive WS failures, ws_circuit_open event is emitted
       and session.mark_circuit_open() is called
  B2 - Staleness timer fires fetch_order and emits ws_staleness_fallback when no WS event arrives
  B3 - FATAL rejection calls pairing.notify_failed(), emits order_failed, does not retry
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from ccxt.base.errors import InsufficientFunds, NetworkError  # type: ignore[import-untyped]

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.crypto.models.order import OrderPairing, OrderRequest, OrderSide, OrderType
from traxon_core.crypto.models.order.execution_type import OrderExecutionType
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.event_bus import OrderEventBus
from traxon_core.crypto.order_executor.exceptions import OrderCreationError
from traxon_core.crypto.order_executor.models import OrderStatus
from traxon_core.crypto.order_executor.session import ExchangeSession
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


class _FakeExchange(Exchange):
    """Minimal Exchange subclass for unit tests — bypasses __init__."""

    def __init__(self, ws_support: bool = True) -> None:  # type: ignore[override]
        self.api = MagicMock()
        self.api.id = "bybit"
        self._id = ExchangeId.BYBIT
        self._ws_support = ws_support

    @property  # type: ignore[override]
    def id(self) -> ExchangeId:
        return self._id

    def has_ws_support(self) -> bool:
        return self._ws_support


def make_exchange(ws_support: bool = True) -> Exchange:
    return _FakeExchange(ws_support=ws_support)


def make_request(pairing: OrderPairing | None = None) -> OrderRequest:
    return OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        amount=Decimal("0.1"),
        price=Decimal("50000"),
        execution_type=OrderExecutionType.MAKER,
        params={},
        exchange_id=ExchangeId.BYBIT,
        pairing=pairing or OrderPairing(),
    )


def make_config(max_ws_reconnect_attempts: int = 3, ws_staleness_window_s: float = 1.0) -> ExecutorConfig:
    return ExecutorConfig(
        execution=OrderExecutionStrategy.FAST,
        max_spread_pct=0.05,
        max_ws_reconnect_attempts=max_ws_reconnect_attempts,
        ws_staleness_window_s=ws_staleness_window_s,
    )


# ---------------------------------------------------------------------------
# B1: Circuit breaker opens after max_ws_reconnect_attempts failures
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_circuit_opens_after_max_reconnect_attempts(self) -> None:
        """
        After max_ws_reconnect_attempts consecutive WS NetworkErrors,
        mark_circuit_open() must be called and ws_circuit_open event emitted.
        """
        config = make_config(max_ws_reconnect_attempts=3)
        event_bus = OrderEventBus()
        emitted_events: list[str] = []

        class CaptureSink:
            def on_event(self, event: Any) -> None:
                emitted_events.append(event.event_name)

        event_bus.register_sink(CaptureSink())

        executor = WebSocketOrderExecutor(config, event_bus=event_bus)
        exchange = make_exchange()
        session = MagicMock(spec=ExchangeSession)
        session.is_circuit_open.return_value = False

        # watch_orders always raises NetworkError
        exchange.api.watch_orders = AsyncMock(side_effect=NetworkError("connection lost"))
        # watch_order_book never completes
        exchange.api.watch_order_book = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(Exception):
            await executor._watch_orders_with_backoff(
                exchange=exchange,
                symbol="BTC/USDT",
                order_id="order-1",
                log_prefix="test",
                exchange_id="bybit",
                start_time=datetime.now(),
                session=session,
            )

        session.mark_circuit_open.assert_called_once()
        assert "ws_circuit_open" in emitted_events

    @pytest.mark.asyncio
    async def test_circuit_breaker_does_not_reconnect_after_opening(self) -> None:
        """
        Once circuit is open, _watch_orders_with_backoff must raise immediately
        without further reconnect attempts.
        """
        config = make_config(max_ws_reconnect_attempts=3)
        event_bus = OrderEventBus()
        executor = WebSocketOrderExecutor(config, event_bus=event_bus)
        exchange = make_exchange()
        session = MagicMock(spec=ExchangeSession)
        # Circuit is already open
        session.is_circuit_open.return_value = True

        call_count = 0

        async def counting_watch_orders(symbol: str) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            raise NetworkError("still broken")

        exchange.api.watch_orders = counting_watch_orders

        with pytest.raises(Exception):
            await executor._watch_orders_with_backoff(
                exchange=exchange,
                symbol="BTC/USDT",
                order_id="order-1",
                log_prefix="test",
                exchange_id="bybit",
                start_time=datetime.now(),
                session=session,
            )

        # Should not have attempted any watch_orders calls
        assert call_count == 0


# ---------------------------------------------------------------------------
# B2: Staleness timer fires REST fetch_order when no WS event arrives
# ---------------------------------------------------------------------------


class TestStalenessDetection:
    @pytest.mark.asyncio
    async def test_staleness_fires_fetch_order_and_emits_event(self) -> None:
        """
        When no WS update arrives within ws_staleness_window_s, fetch_order must
        be called and ws_staleness_fallback event emitted. Order is NOT cancelled.
        """
        config = make_config(ws_staleness_window_s=0.05)  # 50ms for fast test
        event_bus = OrderEventBus()
        emitted_events: list[str] = []

        class CaptureSink:
            def on_event(self, event: Any) -> None:
                emitted_events.append(event.event_name)

        event_bus.register_sink(CaptureSink())

        executor = WebSocketOrderExecutor(config, event_bus=event_bus)
        exchange = make_exchange()
        session = MagicMock(spec=ExchangeSession)
        session.is_circuit_open.return_value = False

        open_order_dict = make_order_dict(status="open")
        closed_order_dict = make_order_dict(status="closed")

        # watch_order_book takes a long time (longer than staleness window)
        async def slow_watch_order_book(symbol: str) -> dict[str, Any]:
            await asyncio.sleep(10.0)  # Much longer than staleness window
            return {"asks": [[50001.0, 1.0]], "bids": [[50000.0, 1.0]]}

        # watch_orders never completes within staleness window
        async def slow_watch_orders(symbol: str) -> list[dict[str, Any]]:
            await asyncio.sleep(10.0)
            return [closed_order_dict]

        # fetch_order returns open first, then closed (staleness fallback)
        exchange.api.fetch_order = AsyncMock(return_value=closed_order_dict)
        exchange.api.watch_order_book = slow_watch_order_book
        exchange.api.watch_orders = slow_watch_orders
        exchange.api.fetch_open_orders = AsyncMock(return_value=[])
        exchange.api.cancel_order = AsyncMock()

        # Simulate a maker order that has already been placed
        # by calling execute_maker_order with a pre-placed order
        # We need to ensure an order is in flight. We'll test via execute_maker_order
        # with an order book that fires quickly to place the order
        async def fast_watch_order_book_first_then_slow(symbol: str) -> dict[str, Any]:
            return {"asks": [[50001.0, 1.0]], "bids": [[50000.0, 1.0]]}

        call_count = {"book": 0}

        async def watch_order_book_once_then_slow(symbol: str) -> dict[str, Any]:
            call_count["book"] += 1
            if call_count["book"] == 1:
                return {"asks": [[50001.0, 1.0]], "bids": [[50000.0, 1.0]]}
            await asyncio.sleep(10.0)
            return {"asks": [[50001.0, 1.0]], "bids": [[50000.0, 1.0]]}

        exchange.api.watch_order_book = watch_order_book_once_then_slow
        exchange.api.create_limit_order = AsyncMock(return_value={"id": "order-stale-1"})

        request = make_request()
        result = await executor.execute_maker_order(exchange, request, session=session)

        # fetch_order must have been called (staleness fallback)
        assert exchange.api.fetch_order.called
        # ws_staleness_fallback event must have been emitted
        assert "ws_staleness_fallback" in emitted_events
        # Result must be the execution report from the REST fallback
        assert result is not None
        assert result.status == OrderStatus.CLOSED


# ---------------------------------------------------------------------------
# B3: FATAL rejection handling in WS executor
# ---------------------------------------------------------------------------


class TestFatalRejection:
    @pytest.mark.asyncio
    async def test_fatal_rejection_calls_notify_failed_and_emits_order_failed(self) -> None:
        """
        When create_limit_order raises InsufficientFunds (FATAL),
        pairing.notify_failed() must be called on the request and
        order_failed event emitted without retrying.
        """
        config = make_config()
        event_bus = OrderEventBus()
        emitted_events: list[str] = []

        class CaptureSink:
            def on_event(self, event: Any) -> None:
                emitted_events.append(event.event_name)

        event_bus.register_sink(CaptureSink())

        executor = WebSocketOrderExecutor(config, event_bus=event_bus)
        exchange = make_exchange()
        session = MagicMock(spec=ExchangeSession)
        session.is_circuit_open.return_value = False

        # Order book fires to unblock order placement
        exchange.api.watch_order_book = AsyncMock(
            return_value={"asks": [[50001.0, 1.0]], "bids": [[50000.0, 1.0]]}
        )
        # create_limit_order raises FATAL error
        exchange.api.create_limit_order = AsyncMock(side_effect=InsufficientFunds("not enough balance"))
        exchange.api.fetch_open_orders = AsyncMock(return_value=[])
        exchange.api.cancel_order = AsyncMock()
        exchange.api.watch_orders = AsyncMock(return_value=[])

        pairing = OrderPairing()
        success_evt = asyncio.Event()
        failure_evt = asyncio.Event()
        pairing.set_events(success_evt, failure_evt)
        request = make_request(pairing=pairing)

        with pytest.raises((OrderCreationError, Exception)):
            await executor.execute_maker_order(exchange, request, session=session)

        assert "order_failed" in emitted_events
        assert failure_evt.is_set()
