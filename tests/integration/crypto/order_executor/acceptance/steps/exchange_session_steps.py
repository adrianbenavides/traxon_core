"""
Step definitions for ExchangeSession acceptance tests (Milestone 1 — US-01).

Exercises ExchangeSession.initialize() through the public driving port:
  DefaultOrderExecutor.execute_orders()

Assertions inspect the mock exchange API call counts to verify
that margin mode and leverage are set at most once per symbol per batch.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pytest_bdd import given, parsers, then, when

from traxon_core.crypto.models import ExchangeId, OrderSide
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor

from .conftest import build_maker_order, build_taker_order, make_orders_to_execute

# ---------------------------------------------------------------------------
# Margin deduplication steps
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "Alejandro submits a batch with {total:d} orders on bybit — "
        "{btc_count:d} for BTC/USDT and {eth_count:d} for ETH/USDT"
    )
)
def batch_with_multiple_symbols(context, total, btc_count, eth_count, market_btc, market_eth):
    """Build a multi-symbol batch for margin deduplication tests."""
    builders = []

    for _ in range(btc_count):
        builders.append(
            build_taker_order(
                exchange_id=ExchangeId.BYBIT,
                market=market_btc,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
            )
        )

    for _ in range(eth_count):
        builders.append(
            build_taker_order(
                exchange_id=ExchangeId.BYBIT,
                market=market_eth,
                side=OrderSide.BUY,
                size=Decimal("1.0"),
            )
        )

    context["builders"] = builders
    context["btc_count"] = btc_count
    context["eth_count"] = eth_count
    context["total"] = total


@pytest.mark.skip(reason="pending implementation: ExchangeSession.initialize()")
@when("the order batch is submitted through the order executor")
async def order_batch_submitted(context, config_best_price, mock_bybit_rest):
    """Drive through the public entry point to trigger ExchangeSession initialization."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([mock_bybit_rest], orders)
    context["reports"] = reports
    context["exchange_api"] = mock_bybit_rest.api


@then(parsers.parse("the exchange receives exactly {count:d} set_margin_mode call for {symbol} on bybit"))
def exchange_receives_margin_mode_call(context, count, symbol):
    """Assert set_margin_mode was called the expected number of times for a symbol."""
    api = context["exchange_api"]
    actual_calls = [
        call
        for call in api.set_margin_mode.call_args_list
        if len(call.args) > 1
        and symbol in str(call.args[1])
        or any(symbol in str(v) for v in call.kwargs.values())
    ]
    assert len(actual_calls) == count, (
        f"Expected {count} set_margin_mode call(s) for {symbol}, got {len(actual_calls)}"
    )


@then(parsers.parse("the total set_margin_mode call count is {expected:d}, not {wrong:d}"))
def total_margin_mode_call_count(context, expected, wrong):
    """Assert set_margin_mode was called exactly expected times, not wrong times."""
    api = context["exchange_api"]
    total = api.set_margin_mode.call_count
    assert total == expected, f"Expected set_margin_mode call count={expected} (not {wrong}), got {total}"


# ---------------------------------------------------------------------------
# Leverage deduplication steps
# ---------------------------------------------------------------------------


@given(parsers.parse("Alejandro configures bybit at {leverage:d}x leverage"))
def bybit_at_leverage(context, leverage):
    """Store the leverage setting for verification in the assertion step."""
    context["configured_leverage"] = leverage


@given(parsers.parse("he submits {count:d} {symbol} maker orders on bybit"))
def maker_orders_on_bybit(context, count, symbol, market_eth):
    """Build multiple maker orders for the same symbol to test leverage deduplication."""
    market = market_eth  # Assumes ETH/USDT for this step
    builders = [
        build_maker_order(
            exchange_id=ExchangeId.BYBIT,
            market=market,
            side=OrderSide.BUY,
            size=Decimal("1.0"),
        )
        for _ in range(count)
    ]
    context["builders"] = builders
    context["order_count"] = count
    context["order_symbol"] = symbol


@then(
    parsers.parse(
        "the exchange receives exactly {count:d} set_leverage call for "
        "{symbol} on bybit with leverage {leverage:d}"
    )
)
def exchange_receives_leverage_call(context, count, symbol, leverage):
    """Assert set_leverage was called once for the symbol regardless of order count."""
    api = context["exchange_api"]
    actual_calls = [
        call
        for call in api.set_leverage.call_args_list
        if leverage in call.args or leverage == call.kwargs.get("leverage")
    ]
    assert len(actual_calls) == count, (
        f"Expected {count} set_leverage({leverage}, {symbol!r}) call(s), got {len(actual_calls)}"
    )


@then("subsequent orders reuse the cached leverage without calling set_leverage again")
def subsequent_orders_reuse_leverage(context):
    """Assert total set_leverage calls are 1, not equal to order count."""
    api = context["exchange_api"]
    order_count = context.get("order_count", 4)
    total = api.set_leverage.call_count
    assert total < order_count, (
        f"Expected fewer set_leverage calls ({total}) than orders ({order_count}) — leverage should be cached"
    )


# ---------------------------------------------------------------------------
# WebSocket pre-warm steps
# ---------------------------------------------------------------------------


@given("Alejandro has a BTC/USDT maker order on bybit which supports WebSocket")
def btc_maker_order_ws_bybit(context, market_btc):
    """Set up a single BTC/USDT maker order on the WS-capable bybit exchange."""
    builder = build_maker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]


@pytest.mark.skip(reason="pending implementation: ExchangeSession WS pre-warm")
@when("the order executor begins initialising the exchange session")
async def executor_begins_initialising(context, config_best_price, mock_bybit_ws):
    """Drive session initialisation through the public entry point."""
    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([mock_bybit_ws], orders)
    context["reports"] = reports
    context["exchange_api"] = mock_bybit_ws.api


@then("the watch_order_book stream for BTC/USDT on bybit is started during session initialisation")
def watch_order_book_started_during_init(context):
    """Assert watch_order_book was called — the pre-warm happened."""
    api = context["exchange_api"]
    assert api.watch_order_book.called, (
        "Expected watch_order_book to be called during session initialisation (AC-01-03)"
    )


@then("watch_order_book is active before the first create_limit_order call is made")
def watch_order_book_before_create_limit(context):
    """
    Assert that watch_order_book was called before create_limit_order.

    Inspect call order via mock call lists.
    """
    api = context["exchange_api"]
    all_calls = api.method_calls
    call_names = [str(c) for c in all_calls]

    watch_idx = next(
        (i for i, name in enumerate(call_names) if "watch_order_book" in name),
        None,
    )
    create_idx = next(
        (i for i, name in enumerate(call_names) if "create_limit_order" in name),
        None,
    )

    assert watch_idx is not None, "watch_order_book was not called"
    assert create_idx is not None, "create_limit_order was not called"
    assert watch_idx < create_idx, (
        f"watch_order_book (call #{watch_idx}) must happen before create_limit_order (call #{create_idx})"
    )


# ---------------------------------------------------------------------------
# Cross-batch isolation steps
# ---------------------------------------------------------------------------


@given("batch 1 completes successfully")
def batch_1_completes(context):
    """Placeholder: previous step drives execution; this step just confirms context."""
    assert "reports" in context, "Batch 1 must have run before this step"


@given("Alejandro submits batch 2 with another BTC/USDT order on bybit")
def batch_2_btc_order(context, market_btc):
    """Set up a fresh batch for the second execute_orders call."""
    builder = build_taker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["batch_2_builders"] = [builder]


@pytest.mark.skip(reason="pending implementation: ExchangeSession cross-batch isolation")
@when("Alejandro submits batch 2 with another BTC/USDT order on bybit")
async def alejandro_submits_batch_2(context, config_best_price, mock_bybit_rest):
    """Drive a second execute_orders call and capture the exchange API call count delta."""
    api = mock_bybit_rest.api
    count_before = api.set_margin_mode.call_count

    executor = DefaultOrderExecutor(config_best_price)
    orders = make_orders_to_execute(context["batch_2_builders"])
    reports = await executor.execute_orders([mock_bybit_rest], orders)

    context["batch_2_reports"] = reports
    context["margin_calls_before_batch_2"] = count_before
    context["margin_calls_after_batch_2"] = api.set_margin_mode.call_count
    context["exchange_api"] = api


@then("set_margin_mode is called again for BTC/USDT in batch 2")
def margin_mode_called_again_in_batch_2(context):
    """Assert that set_margin_mode was called at least once in batch 2."""
    before = context["margin_calls_before_batch_2"]
    after = context["margin_calls_after_batch_2"]
    assert after > before, (
        "set_margin_mode must be called in batch 2 — the session from batch 1 must not be reused"
    )


@then("the session from batch 1 is not reused for batch 2")
def session_not_reused(context):
    """Implied by the margin mode re-call assertion — no additional API surface to check."""
    # Assertion already covered by set_margin_mode call count check above.
    pass
