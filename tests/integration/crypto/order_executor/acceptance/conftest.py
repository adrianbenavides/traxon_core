"""
Root conftest for order-executor acceptance tests.

Provides the shared `context` dict fixture used by all step definitions
to pass state between Given/When/Then steps within a scenario.

Also re-exports all fixtures from steps/conftest.py so they are
available to feature files without needing explicit imports.
"""

from __future__ import annotations

import pytest

# Re-export all fixtures from the steps conftest so they are visible
# to pytest-bdd step definitions without manual imports in each step file.
from tests.integration.crypto.order_executor.acceptance.steps.conftest import (  # noqa: F401
    CapturedEvent,
    MockEventSink,
    build_maker_order,
    build_taker_order,
    config_best_price,
    config_fast,
    event_sink,
    make_orders_to_execute,
    market_btc,
    market_eth,
    market_sol,
    mock_bybit_rest,
    mock_bybit_ws,
    mock_hyperliquid_rest,
)


@pytest.fixture
def context() -> dict:
    """
    Shared mutable context dict for passing state between BDD steps.

    Each scenario gets a fresh empty dict. Steps store and retrieve
    intermediate values (e.g. builders, reports, exchange handles) here.

    Usage in step definitions:
        @given("some precondition")
        def some_precondition(context, market_btc):
            context["builders"] = [build_maker_order(...)]

        @then("some outcome")
        def some_outcome(context):
            assert context["reports"][0].status == OrderStatus.CLOSED
    """
    return {}
