"""
Acceptance test fixtures for order-executor integration tests.

Provides reusable fixtures for:
- Mock exchange API (CCXT layer only — all internal components are real)
- ExchangeSession and OrderRouter factories (new design components)
- OrderEventBus with a capturable MockSink
- ExecutorConfig factory
- OrdersToExecute builder helpers

All exchange API calls (exchange.api.*) are mocked via AsyncMock.
Internal components (ExchangeSession, OrderRouter, RepricePolicy, etc.) are real.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import (
    BaseQuote,
    ExchangeId,
    OrderExecutionType,
    OrderSide,
    OrdersToExecute,
    SizedOrderBuilder,
)
from traxon_core.crypto.models.market_info import MarketInfo
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy

# ---------------------------------------------------------------------------
# Captured event sink — collects all OrderEvents for assertion
# ---------------------------------------------------------------------------


@dataclass
class CapturedEvent:
    """Simplified representation of a captured OrderEvent for test assertions."""

    event_name: str
    order_id: str
    exchange_id: str
    symbol: str
    state: str
    timestamp_ms: int
    elapsed_ms: int
    extra: dict = field(default_factory=dict)


class MockEventSink:
    """
    Test double for EventSink protocol.

    Captures every OrderEvent emitted by the executor so tests can assert
    on the structured event stream without relying on log output parsing.

    Usage:
        sink = MockEventSink()
        # inject into OrderEventBus(sinks=[sink])
        # after test: assert any(e.event_name == "order_submitted" for e in sink.events)
    """

    def __init__(self) -> None:
        self.events: list[CapturedEvent] = []

    def on_event(self, event: object) -> None:
        """
        Capture any OrderEvent.

        Accepts 'object' so this stub works before the real OrderEvent class
        is implemented. When OrderEvent is implemented, replace with the
        typed signature: on_event(self, event: OrderEvent) -> None
        """
        # Guard: handle both real OrderEvent (once implemented) and plain dicts
        if hasattr(event, "__dataclass_fields__"):
            self.events.append(
                CapturedEvent(
                    event_name=getattr(event, "event_name", ""),
                    order_id=getattr(event, "order_id", ""),
                    exchange_id=str(getattr(event, "exchange_id", "")),
                    symbol=getattr(event, "symbol", ""),
                    state=str(getattr(event, "state", "")),
                    timestamp_ms=getattr(event, "timestamp_ms", 0),
                    elapsed_ms=getattr(event, "elapsed_ms", 0),
                )
            )

    def events_named(self, name: str) -> list[CapturedEvent]:
        """Return all captured events with the given event_name."""
        return [e for e in self.events if e.event_name == name]

    def has_event(self, name: str) -> bool:
        """Return True if at least one event with name was captured."""
        return any(e.event_name == name for e in self.events)


# ---------------------------------------------------------------------------
# Market fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def market_btc() -> MarketInfo:
    """Standard BTC/USDT market info for test orders."""
    ccxt_market = {
        "symbol": "BTC/USDT",
        "type": "swap",
        "active": True,
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
        "precision": {"amount": 8, "price": 2},
    }
    return MarketInfo.from_ccxt(ccxt_market)


@pytest.fixture
def market_eth() -> MarketInfo:
    """Standard ETH/USDT market info for test orders."""
    ccxt_market = {
        "symbol": "ETH/USDT",
        "type": "swap",
        "active": True,
        "limits": {"amount": {"min": 0.01}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
        "precision": {"amount": 6, "price": 2},
    }
    return MarketInfo.from_ccxt(ccxt_market)


@pytest.fixture
def market_sol() -> MarketInfo:
    """Standard SOL/USDT market info for test orders."""
    ccxt_market = {
        "symbol": "SOL/USDT",
        "type": "swap",
        "active": True,
        "limits": {"amount": {"min": 0.1}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
        "precision": {"amount": 4, "price": 3},
    }
    return MarketInfo.from_ccxt(ccxt_market)


# ---------------------------------------------------------------------------
# Exchange mock fixtures
# ---------------------------------------------------------------------------


def _make_filled_order_response(
    order_id: str,
    symbol: str,
    amount: float,
    price: float,
    submit_timestamp_ms: int,
    fill_latency_ms: int = 1200,
) -> dict:
    """Build a CCXT-format filled order dict for use in AsyncMock return values."""
    return {
        "id": order_id,
        "symbol": symbol,
        "status": "closed",
        "amount": amount,
        "filled": amount,
        "remaining": 0.0,
        "average": price,
        "price": price,
        "fee": {"cost": 0.001, "currency": "USDT"},
        "timestamp": submit_timestamp_ms + fill_latency_ms,
        "info": {},
    }


@pytest.fixture
def mock_bybit_rest() -> MagicMock:
    """
    Mock exchange representing bybit with REST support only.

    Mocked API surface:
    - set_margin_mode (AsyncMock — returns None)
    - set_leverage (AsyncMock — returns None)
    - fetch_order_book (AsyncMock — returns a simple BTC/USDT order book)
    - create_market_order (AsyncMock — returns a filled order dict)
    - create_limit_order (AsyncMock — returns a submitted order dict)
    - fetch_order (AsyncMock — returns a filled order dict)
    - fetch_open_orders (AsyncMock — returns empty list)
    - cancel_order (AsyncMock — returns None)

    WS methods (watch_*) are NOT configured — use mock_bybit_ws for WS tests.
    """
    exchange = MagicMock(spec=Exchange)
    exchange.id = ExchangeId.BYBIT
    exchange.leverage = 1
    exchange.has_ws_support.return_value = False

    api = MagicMock()
    submit_ms = 1_700_000_000_000
    filled_order = _make_filled_order_response(
        order_id="ord-bybit-001",
        symbol="BTC/USDT",
        amount=0.1,
        price=43200.00,
        submit_timestamp_ms=submit_ms,
        fill_latency_ms=1200,
    )

    api.set_margin_mode = AsyncMock(return_value=None)
    api.set_leverage = AsyncMock(return_value=None)
    api.fetch_order_book = AsyncMock(
        return_value={
            "bids": [[43200.00, 5.0], [43199.00, 3.0]],
            "asks": [[43286.40, 4.0], [43290.00, 2.0]],
            "timestamp": submit_ms,
        }
    )
    api.create_market_order = AsyncMock(return_value=filled_order)
    api.create_limit_order = AsyncMock(return_value={**filled_order, "status": "open"})
    api.fetch_order = AsyncMock(return_value=filled_order)
    api.fetch_open_orders = AsyncMock(return_value=[])
    api.cancel_order = AsyncMock(return_value=None)
    api.has = {}

    exchange.api = api
    return exchange


@pytest.fixture
def mock_bybit_ws() -> MagicMock:
    """
    Mock exchange representing bybit with WebSocket support.

    Configures watch_order_book and watch_orders as AsyncMocks in addition
    to the REST API surface on mock_bybit_rest.

    watch_order_book returns a simple order book snapshot.
    watch_orders returns a list with one filled order event.
    """
    exchange = MagicMock(spec=Exchange)
    exchange.id = ExchangeId.BYBIT
    exchange.leverage = 1
    exchange.has_ws_support.return_value = True

    api = MagicMock()
    submit_ms = 1_700_000_000_000
    filled_order = _make_filled_order_response(
        order_id="ord-bybit-ws-001",
        symbol="BTC/USDT",
        amount=0.1,
        price=43200.00,
        submit_timestamp_ms=submit_ms,
        fill_latency_ms=850,
    )

    api.set_margin_mode = AsyncMock(return_value=None)
    api.set_leverage = AsyncMock(return_value=None)
    api.fetch_order_book = AsyncMock(
        return_value={
            "bids": [[43200.00, 5.0], [43199.00, 3.0]],
            "asks": [[43286.40, 4.0], [43290.00, 2.0]],
            "timestamp": submit_ms,
        }
    )
    api.watch_order_book = AsyncMock(
        return_value={
            "bids": [[43200.00, 5.0], [43199.00, 3.0]],
            "asks": [[43286.40, 4.0], [43290.00, 2.0]],
            "timestamp": submit_ms,
        }
    )
    api.watch_orders = AsyncMock(return_value=[{**filled_order, "status": "closed"}])
    api.create_market_order = AsyncMock(return_value=filled_order)
    api.create_limit_order = AsyncMock(return_value={**filled_order, "status": "open"})
    api.fetch_order = AsyncMock(return_value=filled_order)
    api.fetch_open_orders = AsyncMock(return_value=[])
    api.cancel_order = AsyncMock(return_value=None)
    api.has = {}

    exchange.api = api
    return exchange


@pytest.fixture
def mock_hyperliquid_rest() -> MagicMock:
    """Mock exchange representing hyperliquid with REST support."""
    exchange = MagicMock(spec=Exchange)
    exchange.id = ExchangeId.HYPERLIQUID
    exchange.leverage = 1
    exchange.has_ws_support.return_value = False

    api = MagicMock()
    submit_ms = 1_700_000_000_000
    filled_order = _make_filled_order_response(
        order_id="ord-hl-001",
        symbol="BTC/USDT",
        amount=0.1,
        price=43150.00,
        submit_timestamp_ms=submit_ms,
        fill_latency_ms=950,
    )

    api.set_margin_mode = AsyncMock(return_value=None)
    api.set_leverage = AsyncMock(return_value=None)
    api.fetch_order_book = AsyncMock(
        return_value={
            "bids": [[43150.00, 8.0], [43148.00, 4.0]],
            "asks": [[43200.00, 6.0], [43210.00, 3.0]],
            "timestamp": submit_ms,
        }
    )
    api.create_market_order = AsyncMock(return_value=filled_order)
    api.create_limit_order = AsyncMock(return_value={**filled_order, "status": "open"})
    api.fetch_order = AsyncMock(return_value=filled_order)
    api.fetch_open_orders = AsyncMock(return_value=[])
    api.cancel_order = AsyncMock(return_value=None)
    api.has = {}

    exchange.api = api
    return exchange


# ---------------------------------------------------------------------------
# ExecutorConfig fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_fast() -> ExecutorConfig:
    """Fast execution config — suitable for the walking skeleton."""
    return ExecutorConfig(
        execution=OrderExecutionStrategy.FAST,
        max_spread_pct=0.01,
    )


@pytest.fixture
def config_best_price() -> ExecutorConfig:
    """Best-price config with default new fields (all backward-compatible defaults)."""
    return ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.005,
    )


# ---------------------------------------------------------------------------
# MockEventSink fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def event_sink() -> MockEventSink:
    """A fresh event sink for capturing OrderEvents in each test."""
    return MockEventSink()


# ---------------------------------------------------------------------------
# OrdersToExecute builder helpers
# ---------------------------------------------------------------------------


def build_taker_order(
    exchange_id: ExchangeId,
    market: MarketInfo,
    side: OrderSide,
    size: Decimal,
) -> SizedOrderBuilder:
    """Build a taker SizedOrderBuilder with asyncio events wired for pairing."""
    builder = SizedOrderBuilder(
        exchange_id=exchange_id,
        market=market,
        execution_type=OrderExecutionType.TAKER,
        side=side,
        size=size,
    )
    builder.pairing.set_events(asyncio.Event(), asyncio.Event())
    return builder


def build_maker_order(
    exchange_id: ExchangeId,
    market: MarketInfo,
    side: OrderSide,
    size: Decimal,
) -> SizedOrderBuilder:
    """Build a maker SizedOrderBuilder with asyncio events wired for pairing."""
    builder = SizedOrderBuilder(
        exchange_id=exchange_id,
        market=market,
        execution_type=OrderExecutionType.MAKER,
        side=side,
        size=size,
    )
    builder.pairing.set_events(asyncio.Event(), asyncio.Event())
    return builder


def make_orders_to_execute(builders: list[SizedOrderBuilder]) -> OrdersToExecute:
    """
    Group a list of SizedOrderBuilders into an OrdersToExecute by BaseQuote.

    Assumes all builders are for 'new' orders (not updates).
    """
    from collections import defaultdict

    grouped: dict[BaseQuote, list[SizedOrderBuilder]] = defaultdict(list)
    for b in builders:
        base, quote = b.market.symbol.split("/")
        grouped[BaseQuote(base, quote)].append(b)

    return OrdersToExecute(updates={}, new=dict(grouped))
