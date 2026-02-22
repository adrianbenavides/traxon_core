"""
Unit tests for ExecutorConfig (step 03-03).

Test Budget: 3 behaviors x 2 = 6 max unit tests.

Behaviors:
  B1 - Backward compatibility: ExecutorConfig with only execution + max_spread_pct is valid
  B2 - New fields apply their documented defaults when not provided
  B3 - check_timeout reads timeout_duration from config (not hardcoded)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.exceptions import OrderTimeoutError
from traxon_core.crypto.order_executor.rest import RestApiOrderExecutor

# ---------------------------------------------------------------------------
# B1 — Backward compatibility
# ---------------------------------------------------------------------------


def test_executor_config_valid_with_only_execution_and_max_spread_pct() -> None:
    """ExecutorConfig constructed with only execution and max_spread_pct remains valid."""
    config = ExecutorConfig(execution=OrderExecutionStrategy.FAST, max_spread_pct=0.05)

    assert config.execution == OrderExecutionStrategy.FAST
    assert config.max_spread_pct == 0.05


# ---------------------------------------------------------------------------
# B2 — New fields apply documented defaults
# ---------------------------------------------------------------------------


def test_executor_config_default_timeout_duration_is_five_minutes() -> None:
    """timeout_duration defaults to timedelta(minutes=5)."""
    config = ExecutorConfig(execution=OrderExecutionStrategy.FAST, max_spread_pct=0.05)

    assert config.timeout_duration == timedelta(minutes=5)


def test_executor_config_new_fields_apply_documented_defaults() -> None:
    """ws_staleness_window_s, max_ws_reconnect_attempts, max_concurrent_orders_per_exchange default correctly."""
    config = ExecutorConfig(execution=OrderExecutionStrategy.FAST, max_spread_pct=0.05)

    assert config.ws_staleness_window_s == 30.0
    assert config.max_ws_reconnect_attempts == 5
    assert config.max_concurrent_orders_per_exchange == 10


# ---------------------------------------------------------------------------
# B3 — check_timeout reads timeout_duration from config
# ---------------------------------------------------------------------------


def test_check_timeout_does_not_raise_within_configured_duration() -> None:
    """check_timeout does not raise when elapsed time is less than config.timeout_duration."""
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.FAST,
        max_spread_pct=0.05,
        timeout_duration=timedelta(minutes=10),
    )
    executor = RestApiOrderExecutor(config)

    # 5 minutes ago — within 10-minute timeout
    start_time = datetime.now() - timedelta(minutes=5)
    executor.check_timeout(start_time, "BTC/USDT")  # must not raise


def test_check_timeout_raises_when_elapsed_exceeds_configured_duration() -> None:
    """check_timeout raises OrderTimeoutError when elapsed time exceeds config.timeout_duration."""
    config = ExecutorConfig(
        execution=OrderExecutionStrategy.FAST,
        max_spread_pct=0.05,
        timeout_duration=timedelta(seconds=1),
    )
    executor = RestApiOrderExecutor(config)

    # 10 seconds ago — beyond 1-second timeout
    start_time = datetime.now() - timedelta(seconds=10)

    with pytest.raises(OrderTimeoutError):
        executor.check_timeout(start_time, "BTC/USDT")
