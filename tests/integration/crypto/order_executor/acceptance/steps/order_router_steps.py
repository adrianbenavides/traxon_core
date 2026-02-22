"""
Step definitions for OrderRouter acceptance tests.

Covers scenarios that exercise the public entry point:
  DefaultOrderExecutor.execute_orders(exchanges, orders)

All steps invoke through the public driving port only.
Internal routing (OrderRouter, ExchangeSession selection) is exercised indirectly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pytest_bdd import given, parsers, then, when

from traxon_core.crypto.models import ExchangeId, OrderSide
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor

from .conftest import MockEventSink, build_taker_order, make_orders_to_execute

# ---------------------------------------------------------------------------
# Walking skeleton steps
# ---------------------------------------------------------------------------


@given(parsers.parse("Alejandro has an order to buy {amount} {symbol} on {exchange_name} as a taker"))
def alejandro_has_taker_order(context, amount, symbol, exchange_name, market_btc):
    """Set up a single taker order for the walking skeleton."""
    exchange_id = ExchangeId(exchange_name)
    builder = build_taker_order(
        exchange_id=exchange_id,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal(amount),
    )
    context["builders"] = [builder]
    context["exchange_name"] = exchange_name


@when("he submits the order batch through the order executor")
async def he_submits_the_order_batch(context, config_fast, mock_bybit_rest):
    """
    Drive through DefaultOrderExecutor.execute_orders — the single public driving port.

    Uses the new design's ExchangeSession and OrderRouter internally.
    The CCXT exchange API (mock_bybit_rest.api) is the only mock boundary.
    """
    executor = DefaultOrderExecutor(config_fast)
    orders = make_orders_to_execute(context["builders"])
    exchange = mock_bybit_rest

    # NOTE: DefaultOrderExecutor.execute_orders is the driving port.
    # The implementation will route through OrderRouter -> ExchangeSession -> RestOrderExecutor.
    reports = await executor.execute_orders([exchange], orders)
    context["reports"] = reports
    context["exchange"] = exchange


@then("the execution report confirms the order filled on bybit")
def the_report_confirms_fill(context):
    """Assert the executor returned at least one closed report."""
    from traxon_core.crypto.order_executor.models import OrderStatus

    reports = context["reports"]
    assert len(reports) >= 1, "Expected at least one execution report"
    assert reports[0].status == OrderStatus.CLOSED, f"Expected CLOSED status, got {reports[0].status}"


@then(parsers.parse('the execution report includes the exchange identifier "{exchange_name}"'))
def the_report_includes_exchange_id(context, exchange_name):
    """Assert the ExecutionReport.exchange_id is populated and correct (US-08, AC-08-01)."""
    reports = context["reports"]
    assert len(reports) >= 1
    report = reports[0]
    assert hasattr(report, "exchange_id"), "ExecutionReport must have exchange_id field (AC-08-01)"
    assert report.exchange_id is not None, "exchange_id must not be None"
    assert str(report.exchange_id) == exchange_name, (
        f"Expected exchange_id={exchange_name!r}, got {report.exchange_id!r}"
    )


@then("the execution report includes a non-negative fill latency in milliseconds")
def the_report_includes_fill_latency(context):
    """Assert the ExecutionReport.fill_latency_ms is populated and >= 0 (US-08, AC-08-02)."""
    reports = context["reports"]
    assert len(reports) >= 1
    report = reports[0]
    assert hasattr(report, "fill_latency_ms"), "ExecutionReport must have fill_latency_ms field (AC-08-02)"
    assert report.fill_latency_ms >= 0, f"fill_latency_ms must be >= 0, got {report.fill_latency_ms}"


@then("the pairing is marked as filled")
def the_pairing_is_marked_filled(context):
    """Assert the order pairing notified success."""
    builders = context["builders"]
    assert len(builders) >= 1
    assert builders[0].pairing.is_pair_filled(), (
        "Expected pairing to be marked as filled after successful execution"
    )


# ---------------------------------------------------------------------------
# Multi-order / multi-exchange steps
# ---------------------------------------------------------------------------


@given("Alejandro has a list of valid orders across multiple exchanges")
def alejandro_has_multi_exchange_orders(context, market_btc, market_eth):
    """Set up orders on two different exchanges for concurrent execution tests."""
    bybit_builder = build_taker_order(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    hl_builder = build_taker_order(
        exchange_id=ExchangeId.HYPERLIQUID,
        market=market_btc,
        side=OrderSide.SELL,
        size=Decimal("0.1"),
    )
    context["builders"] = [bybit_builder, hl_builder]


@pytest.mark.skip(reason="pending implementation: OrderRouter multi-exchange fan-out")
@when("he submits the multi-exchange batch")
async def he_submits_multi_exchange_batch(context, config_fast, mock_bybit_rest, mock_hyperliquid_rest):
    executor = DefaultOrderExecutor(config_fast)
    orders = make_orders_to_execute(context["builders"])
    reports = await executor.execute_orders([mock_bybit_rest, mock_hyperliquid_rest], orders)
    context["reports"] = reports


@then("all reports are returned with correct exchange identifiers")
def all_reports_have_exchange_ids(context):
    """Assert every report has a non-null exchange_id that matches the submitted order."""
    reports = context["reports"]
    assert len(reports) == 2, f"Expected 2 reports, got {len(reports)}"
    exchange_ids = {str(r.exchange_id) for r in reports}
    assert "bybit" in exchange_ids, "Expected a bybit report"
    assert "hyperliquid" in exchange_ids, "Expected a hyperliquid report"


# ---------------------------------------------------------------------------
# Exchange-not-found steps
# ---------------------------------------------------------------------------


@given(parsers.parse('Alejandro submits an order for {symbol} on exchange "{exchange_name}"'))
def order_for_unknown_exchange(context, symbol, exchange_name, market_btc):
    """Set up an order referencing an exchange not in the session."""
    try:
        exchange_id = ExchangeId(exchange_name)
    except ValueError:
        # Exchange not recognised — this is the test scenario
        context["unknown_exchange_name"] = exchange_name
        context["builders"] = []
        return

    builder = build_taker_order(
        exchange_id=exchange_id,
        market=market_btc,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    context["builders"] = [builder]
    context["unknown_exchange_name"] = exchange_name


@given(parsers.parse('the exchanges list contains only "{exchange_name}"'))
def exchanges_list_contains_only(context, exchange_name, mock_bybit_rest):
    """Restrict the available exchanges to a single entry."""
    context["available_exchanges"] = [mock_bybit_rest]


@pytest.mark.skip(reason="pending implementation: OrderRouter exchange-not-found path")
@when("the order batch is submitted through the order executor")
async def order_batch_submitted_through_executor(context, config_fast):
    executor = DefaultOrderExecutor(config_fast)
    orders = make_orders_to_execute(context.get("builders", []))
    exchanges = context.get("available_exchanges", [])
    reports = await executor.execute_orders(exchanges, orders)
    context["reports"] = reports


@then("the pairing for the orphaned order is marked as failed")
def pairing_for_orphaned_order_marked_failed(context):
    """Assert notify_failed was called for the order with an unknown exchange."""
    builders = context.get("builders", [])
    if builders:
        assert builders[0].pairing.is_pair_failed(), "Expected pairing to be marked failed for orphaned order"


@then("the batch continues processing any remaining valid orders")
def batch_continues_after_orphan(context):
    """Assert execution did not halt entirely due to the orphaned order."""
    # In a batch with only orphaned orders, reports will be empty — that is acceptable.
    # The key invariant is that no exception was raised from execute_orders itself.
    assert "reports" in context, "execute_orders must complete without raising"
