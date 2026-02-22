"""
Unit tests for OrderRouter.

Test Budget: 4 distinct behaviors x 2 = 8 max unit tests.

Behaviors:
  1. Orphan notification — exchange absent -> pairing.notify_failed() called, order skipped
  2. Concurrent session initialization — sessions initialized in parallel (not sequential)
  3. DefaultOrderExecutor.execute_orders backward compatibility
  4. No state between calls — fresh sessions per invocation
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from traxon_core.crypto.exchanges.config import ExchangeApiConnection
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
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor
from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus
from traxon_core.crypto.order_executor.router import OrderRouter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def executor_config() -> ExecutorConfig:
    return ExecutorConfig(execution=OrderExecutionStrategy.FAST, max_spread_pct=0.01)


@pytest.fixture
def market_btc() -> MarketInfo:
    ccxt_market = {
        "symbol": "BTC/USDT",
        "type": "spot",
        "active": True,
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
        "precision": {"amount": 8, "price": 2},
    }
    return MarketInfo.from_ccxt(ccxt_market)


@pytest.fixture
def market_eth() -> MarketInfo:
    ccxt_market = {
        "symbol": "ETH/USDT",
        "type": "spot",
        "active": True,
        "limits": {"amount": {"min": 0.01}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
        "precision": {"amount": 6, "price": 2},
    }
    return MarketInfo.from_ccxt(ccxt_market)


def make_exchange(exchange_id: ExchangeId, has_ws: bool = False) -> MagicMock:
    exchange = MagicMock(spec=Exchange)
    exchange.id = exchange_id
    exchange.api = MagicMock()
    exchange.api.has = {}
    exchange.api_connection = ExchangeApiConnection.REST.value
    exchange.has_ws_support.return_value = has_ws
    exchange.leverage = 1
    return exchange


def make_taker_builder(
    exchange_id: ExchangeId,
    market: MarketInfo,
    size: Decimal = Decimal("0.1"),
) -> SizedOrderBuilder:
    builder = SizedOrderBuilder(
        exchange_id=exchange_id,
        market=market,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=size,
    )
    builder.pairing.set_events(asyncio.Event(), asyncio.Event())
    return builder


def make_report(exchange_id: str = "bybit") -> ExecutionReport:
    return ExecutionReport(
        id="order-1",
        symbol="BTC/USDT",
        status=OrderStatus.CLOSED,
        amount=Decimal("0.1"),
        filled=Decimal("0.1"),
        remaining=Decimal("0"),
        timestamp=123456789,
        exchange_id=exchange_id,
        fill_latency_ms=0,
    )


# ---------------------------------------------------------------------------
# Behavior 1: Orphan notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_notifies_failed_for_unknown_exchange(
    executor_config: ExecutorConfig, market_btc: MarketInfo
) -> None:
    """Order referencing exchange absent from the list -> pairing.notify_failed() called, order skipped."""
    router = OrderRouter(executor_config)

    builder = make_taker_builder(ExchangeId.BYBIT, market_btc)
    ote = OrdersToExecute(updates={}, new={BaseQuote("BTC", "USDT"): [builder]})

    # Pass empty exchanges list — BYBIT not present
    reports = await router.route_and_collect(exchanges=[], orders=ote)

    assert reports == []
    assert builder.pairing.is_pair_failed(), "pairing.notify_failed() must be called for orphan order"


@pytest.mark.asyncio
async def test_router_skips_orphan_and_executes_valid(
    executor_config: ExecutorConfig, market_btc: MarketInfo, market_eth: MarketInfo
) -> None:
    """Orphan order is skipped; valid order for a present exchange still executes."""
    router = OrderRouter(executor_config)

    orphan_builder = make_taker_builder(ExchangeId.BINANCE, market_btc)  # BINANCE not in exchanges
    valid_builder = make_taker_builder(ExchangeId.BYBIT, market_eth)

    bybit_exchange = make_exchange(ExchangeId.BYBIT)
    report = make_report("bybit")

    ote = OrdersToExecute(
        updates={},
        new={
            BaseQuote("BTC", "USDT"): [orphan_builder],
            BaseQuote("ETH", "USDT"): [valid_builder],
        },
    )

    with patch("traxon_core.crypto.order_executor.router.RestApiOrderExecutor") as MockRest:
        mock_rest_instance = MagicMock()
        mock_rest_instance.execute_taker_order = AsyncMock(return_value=report)
        MockRest.return_value = mock_rest_instance

        with patch("traxon_core.crypto.order_executor.router.ExchangeSession") as MockSession:
            mock_session = MagicMock()
            mock_session.initialize = AsyncMock()
            mock_session.is_circuit_open.return_value = False
            MockSession.return_value = mock_session

            reports = await router.route_and_collect(exchanges=[bybit_exchange], orders=ote)

    assert orphan_builder.pairing.is_pair_failed(), "orphan must notify_failed"
    assert len(reports) == 1


# ---------------------------------------------------------------------------
# Behavior 2: Concurrent session initialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_initializes_sessions_concurrently(
    executor_config: ExecutorConfig, market_btc: MarketInfo, market_eth: MarketInfo
) -> None:
    """All session.initialize() calls run concurrently; total wall time ~= slowest session, not sum."""
    router = OrderRouter(executor_config)

    bybit_exchange = make_exchange(ExchangeId.BYBIT)
    binance_exchange = make_exchange(ExchangeId.BINANCE)

    builder_bybit = make_taker_builder(ExchangeId.BYBIT, market_btc)
    builder_okx = make_taker_builder(ExchangeId.BINANCE, market_eth)

    ote = OrdersToExecute(
        updates={},
        new={
            BaseQuote("BTC", "USDT"): [builder_bybit],
            BaseQuote("ETH", "USDT"): [builder_okx],
        },
    )

    call_order: list[str] = []
    start_times: dict[str, float] = {}
    end_times: dict[str, float] = {}

    import time

    async def slow_initialize(symbol: str, exchange_label: str) -> None:
        start_times[exchange_label] = time.monotonic()
        call_order.append(f"start_{exchange_label}")
        await asyncio.sleep(0.05)  # simulate 50ms init
        call_order.append(f"end_{exchange_label}")
        end_times[exchange_label] = time.monotonic()

    with patch("traxon_core.crypto.order_executor.router.ExchangeSession") as MockSession:

        async def init_bybit(symbol: str) -> None:
            await slow_initialize(symbol, "bybit")

        async def init_binance(symbol: str) -> None:
            await slow_initialize(symbol, "okx")

        session_bybit = MagicMock()
        session_bybit.initialize = AsyncMock(side_effect=init_bybit)
        session_bybit.is_circuit_open.return_value = False

        session_binance = MagicMock()
        session_binance.initialize = AsyncMock(side_effect=init_binance)
        session_binance.is_circuit_open.return_value = False

        MockSession.side_effect = [session_bybit, session_binance]

        with patch("traxon_core.crypto.order_executor.router.RestApiOrderExecutor") as MockRest:
            mock_rest_instance = MagicMock()
            mock_rest_instance.execute_taker_order = AsyncMock(return_value=make_report())
            MockRest.return_value = mock_rest_instance

            overall_start = time.monotonic()
            await router.route_and_collect(exchanges=[bybit_exchange, binance_exchange], orders=ote)
            overall_elapsed = time.monotonic() - overall_start

    # If concurrent: overall elapsed ~50ms. If sequential: ~100ms.
    # Use 80ms as threshold with margin.
    assert overall_elapsed < 0.08, (
        f"Session initialization was sequential (took {overall_elapsed:.3f}s); expected concurrent (~0.05s)"
    )
    # Both sessions must have started
    assert "start_bybit" in call_order
    assert "start_okx" in call_order


# ---------------------------------------------------------------------------
# Behavior 3: DefaultOrderExecutor.execute_orders backward compatibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_executor_execute_orders_signature_unchanged(
    executor_config: ExecutorConfig, market_btc: MarketInfo
) -> None:
    """DefaultOrderExecutor.execute_orders(exchanges, orders) -> list[ExecutionReport] unchanged."""
    executor = DefaultOrderExecutor(executor_config)

    builder = make_taker_builder(ExchangeId.BYBIT, market_btc)
    bybit_exchange = make_exchange(ExchangeId.BYBIT)
    ote = OrdersToExecute(updates={}, new={BaseQuote("BTC", "USDT"): [builder]})
    report = make_report("bybit")

    # Patch _execute_order on DefaultOrderExecutor; it delegates through the router's execute_fn.
    with patch.object(DefaultOrderExecutor, "_execute_order", new=AsyncMock(return_value=report)):
        result = await executor.execute_orders([bybit_exchange], ote)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].status == OrderStatus.CLOSED


@pytest.mark.asyncio
async def test_default_executor_returns_empty_for_empty_orders(
    executor_config: ExecutorConfig,
) -> None:
    """DefaultOrderExecutor.execute_orders returns [] when no orders given."""
    executor = DefaultOrderExecutor(executor_config)
    ote = OrdersToExecute(updates={}, new={})

    result = await executor.execute_orders([], ote)

    assert result == []


# ---------------------------------------------------------------------------
# Behavior 4: No state between calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_creates_fresh_sessions_per_call(
    executor_config: ExecutorConfig, market_btc: MarketInfo
) -> None:
    """Two sequential route_and_collect calls create distinct ExchangeSession instances."""
    router = OrderRouter(executor_config)
    bybit_exchange = make_exchange(ExchangeId.BYBIT)

    def make_orders() -> OrdersToExecute:
        builder = make_taker_builder(ExchangeId.BYBIT, market_btc)
        return OrdersToExecute(updates={}, new={BaseQuote("BTC", "USDT"): [builder]})

    session_instances: list[MagicMock] = []

    with patch("traxon_core.crypto.order_executor.router.ExchangeSession") as MockSession:

        def session_factory(*args, **kwargs) -> MagicMock:
            s = MagicMock()
            s.initialize = AsyncMock()
            s.is_circuit_open.return_value = False
            session_instances.append(s)
            return s

        MockSession.side_effect = session_factory

        with patch("traxon_core.crypto.order_executor.router.RestApiOrderExecutor") as MockRest:
            mock_rest_instance = MagicMock()
            mock_rest_instance.execute_taker_order = AsyncMock(return_value=make_report())
            MockRest.return_value = mock_rest_instance

            await router.route_and_collect(exchanges=[bybit_exchange], orders=make_orders())
            await router.route_and_collect(exchanges=[bybit_exchange], orders=make_orders())

    assert len(session_instances) == 2, (
        f"Expected 2 distinct ExchangeSession instances (one per call), got {len(session_instances)}"
    )
    assert session_instances[0] is not session_instances[1], (
        "Sessions from two calls must be distinct objects (no state shared)"
    )


@pytest.mark.asyncio
async def test_router_no_cross_call_state_contamination(
    executor_config: ExecutorConfig, market_btc: MarketInfo
) -> None:
    """First call failure does not affect second call's execution."""
    router = OrderRouter(executor_config)
    bybit_exchange = make_exchange(ExchangeId.BYBIT)
    report = make_report("bybit")

    call_count = 0

    with patch("traxon_core.crypto.order_executor.router.ExchangeSession") as MockSession:

        def session_factory(*args, **kwargs) -> MagicMock:
            nonlocal call_count
            call_count += 1
            s = MagicMock()
            s.initialize = AsyncMock()
            s.is_circuit_open.return_value = False
            return s

        MockSession.side_effect = session_factory

        with patch("traxon_core.crypto.order_executor.router.RestApiOrderExecutor") as MockRest:
            first_mock = MagicMock()
            first_mock.execute_taker_order = AsyncMock(side_effect=Exception("transient failure"))
            second_mock = MagicMock()
            second_mock.execute_taker_order = AsyncMock(return_value=report)
            MockRest.side_effect = [first_mock, second_mock]

            builder1 = make_taker_builder(ExchangeId.BYBIT, market_btc)
            ote1 = OrdersToExecute(updates={}, new={BaseQuote("BTC", "USDT"): [builder1]})
            results1 = await router.route_and_collect(exchanges=[bybit_exchange], orders=ote1)

            builder2 = make_taker_builder(ExchangeId.BYBIT, market_btc)
            ote2 = OrdersToExecute(updates={}, new={BaseQuote("BTC", "USDT"): [builder2]})
            results2 = await router.route_and_collect(exchanges=[bybit_exchange], orders=ote2)

    # First call had failure -> no reports; second call succeeds
    assert results1 == []
    assert len(results2) == 1
    assert results2[0].status == OrderStatus.CLOSED
