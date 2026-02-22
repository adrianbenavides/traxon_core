"""
Unit tests for ExchangeSession.

Test Budget: 5 distinct behaviors x 2 = 10 unit tests maximum.

Behaviors:
  1. set_margin_mode called at most once per symbol per session
  2. set_leverage called at most once per symbol per session
  3. initialize pre-warms WS order book on WS-capable exchanges
  4. Concurrent executions bounded by semaphore
  5. mark_circuit_open transitions session to REST-only mode
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.order_executor.event_bus import OrderEventBus
from traxon_core.crypto.order_executor.session import ExchangeSession


def _make_exchange(has_ws: bool = True) -> Exchange:
    exchange = MagicMock(spec=Exchange)
    exchange.id = "bybit"
    exchange.api = AsyncMock()
    exchange.has_ws_support = MagicMock(return_value=has_ws)
    exchange.leverage = 5
    return exchange


def _make_session(max_concurrent: int = 3, has_ws: bool = True) -> tuple[ExchangeSession, MagicMock]:
    exchange = _make_exchange(has_ws=has_ws)
    event_bus = OrderEventBus()
    session = ExchangeSession(
        exchange=exchange,
        event_bus=event_bus,
        max_concurrent_orders=max_concurrent,
    )
    return session, exchange


# ---------------------------------------------------------------------------
# Behavior 1 & 2: margin_mode + leverage each called once per symbol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_margin_initialized_calls_set_margin_mode_once_per_symbol() -> None:
    """set_margin_mode is called exactly once for a given symbol, never twice."""
    session, exchange = _make_session()

    await session.ensure_margin_initialized("BTC/USDT:USDT")
    await session.ensure_margin_initialized("BTC/USDT:USDT")

    exchange.api.set_margin_mode.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_margin_initialized_calls_set_leverage_once_per_symbol() -> None:
    """set_leverage is called exactly once for a given symbol, never twice."""
    session, exchange = _make_session()

    await session.ensure_margin_initialized("ETH/USDT:USDT")
    await session.ensure_margin_initialized("ETH/USDT:USDT")

    exchange.api.set_leverage.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_margin_initialized_calls_apis_for_distinct_symbols() -> None:
    """Each unique symbol gets its own margin + leverage initialization."""
    session, exchange = _make_session()

    await session.ensure_margin_initialized("BTC/USDT:USDT")
    await session.ensure_margin_initialized("ETH/USDT:USDT")

    assert exchange.api.set_margin_mode.await_count == 2
    assert exchange.api.set_leverage.await_count == 2


# ---------------------------------------------------------------------------
# Behavior 3: initialize pre-warms WS connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_prewarms_ws_order_book_on_ws_capable_exchange() -> None:
    """initialize calls watch_order_book once on WS-capable exchange."""
    session, exchange = _make_session(has_ws=True)

    await session.initialize("BTC/USDT:USDT")

    exchange.api.watch_order_book.assert_awaited_once()


@pytest.mark.asyncio
async def test_initialize_skips_ws_prewarm_on_non_ws_exchange() -> None:
    """initialize does not call watch_order_book when exchange lacks WS support."""
    session, exchange = _make_session(has_ws=False)

    await session.initialize("BTC/USDT:USDT")

    exchange.api.watch_order_book.assert_not_awaited()


@pytest.mark.asyncio
async def test_initialize_is_nonfatal_when_watch_order_book_raises() -> None:
    """Pre-warm failure does not propagate — initialize completes without raising."""
    session, exchange = _make_session(has_ws=True)
    exchange.api.watch_order_book.side_effect = Exception("WS connection refused")

    # Must not raise
    await session.initialize("BTC/USDT:USDT")


# ---------------------------------------------------------------------------
# Behavior 4: semaphore bounds concurrency
# ---------------------------------------------------------------------------


def test_semaphore_value_matches_max_concurrent_orders() -> None:
    """Semaphore is initialized with max_concurrent_orders capacity."""
    session, _ = _make_session(max_concurrent=5)

    assert session.semaphore._value == 5  # noqa: SLF001 — only way to inspect asyncio.Semaphore


# ---------------------------------------------------------------------------
# Behavior 5: circuit breaker transitions session to REST-only mode
# ---------------------------------------------------------------------------


def test_circuit_open_false_by_default() -> None:
    """Session starts with circuit breaker closed (WS eligible)."""
    session, _ = _make_session()

    assert session.is_circuit_open() is False


def test_mark_circuit_open_sets_circuit_to_open() -> None:
    """mark_circuit_open transitions session to REST-only mode."""
    session, _ = _make_session()

    session.mark_circuit_open()

    assert session.is_circuit_open() is True
