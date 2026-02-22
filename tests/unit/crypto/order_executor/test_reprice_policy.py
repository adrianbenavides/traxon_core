"""
Unit tests for reprice.py policies.

Test Budget: 5 behaviors x 2 = 10 unit tests
Behaviors:
  1. MinChangeRepricePolicy: suppresses reprice below threshold
  2. MinChangeRepricePolicy: allows reprice at/above threshold
  3. ElapsedTimeRepricePolicy: overrides min threshold when elapsed >= override seconds
  4. CompositeRepricePolicy: returns True only when all composed policies agree
  5. build_reprice_policy factory: constructs correct policy from ExecutorConfig
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.reprice import (
    AlwaysRepricePolicy,
    CompositeRepricePolicy,
    ElapsedTimeRepricePolicy,
    MinChangeRepricePolicy,
    build_reprice_policy,
)

# ---------------------------------------------------------------------------
# Behavior 1 & 2: MinChangeRepricePolicy — threshold filtering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "old_price, new_price, min_change_pct, expected",
    [
        # Below threshold: 0.5% change vs 1.0% minimum → suppress
        (Decimal("100"), Decimal("100.5"), Decimal("0.01"), False),
        # Exactly at threshold: 1.0% change vs 1.0% minimum → allow
        (Decimal("100"), Decimal("101.0"), Decimal("0.01"), True),
        # Above threshold: 2.0% change vs 1.0% minimum → allow
        (Decimal("100"), Decimal("102.0"), Decimal("0.01"), True),
        # Price decrease below threshold → suppress
        (Decimal("100"), Decimal("99.8"), Decimal("0.01"), False),
    ],
)
def test_min_change_reprice_policy_threshold(
    old_price: Decimal,
    new_price: Decimal,
    min_change_pct: Decimal,
    expected: bool,
) -> None:
    """Behavior 1 & 2: MinChangeRepricePolicy filters by minimum percentage change."""
    policy = MinChangeRepricePolicy(min_change_pct=min_change_pct)
    result = policy.should_reprice(old_price, new_price, elapsed_seconds=5.0)
    assert result == expected


# ---------------------------------------------------------------------------
# Behavior 3: ElapsedTimeRepricePolicy — elapsed override
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "elapsed_seconds, old_price, new_price, override_after, expected",
    [
        # Elapsed below override: delegates to inner (inner returns False for small change)
        (10.0, Decimal("100"), Decimal("100.3"), 30.0, False),
        # Elapsed at override: any non-zero change returns True, ignoring inner threshold
        (30.0, Decimal("100"), Decimal("100.3"), 30.0, True),
        # Elapsed above override: any non-zero change returns True
        (60.0, Decimal("100"), Decimal("100.01"), 30.0, True),
        # Elapsed above override but price unchanged: returns False (no change to apply)
        (60.0, Decimal("100"), Decimal("100"), 30.0, False),
    ],
)
def test_elapsed_time_reprice_policy_override(
    elapsed_seconds: float,
    old_price: Decimal,
    new_price: Decimal,
    override_after: float,
    expected: bool,
) -> None:
    """Behavior 3: ElapsedTimeRepricePolicy overrides inner policy when elapsed >= override seconds."""
    # Inner policy requires 1% minimum change — used to verify override behaviour
    inner = MinChangeRepricePolicy(min_change_pct=Decimal("0.01"))
    policy = ElapsedTimeRepricePolicy(override_after_seconds=override_after, inner=inner)
    result = policy.should_reprice(old_price, new_price, elapsed_seconds)
    assert result == expected


# ---------------------------------------------------------------------------
# Behavior 4: CompositeRepricePolicy — ALL must agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "policies_agree, expected",
    [
        # All policies agree → True
        ([True, True, True], True),
        # One policy disagrees → False
        ([True, False, True], False),
        # All disagree → False
        ([False, False, False], False),
    ],
)
def test_composite_reprice_policy_requires_all(
    policies_agree: list[bool],
    expected: bool,
) -> None:
    """Behavior 4: CompositeRepricePolicy returns True only when every constituent policy returns True."""

    class _Stub:
        def __init__(self, result: bool) -> None:
            self._result = result

        def should_reprice(self, old_price: Decimal, new_price: Decimal, elapsed_seconds: float) -> bool:
            return self._result

    stubs = [_Stub(v) for v in policies_agree]
    policy = CompositeRepricePolicy(policies=stubs)  # type: ignore[arg-type]
    result = policy.should_reprice(Decimal("100"), Decimal("101"), elapsed_seconds=5.0)
    assert result == expected


# ---------------------------------------------------------------------------
# Behavior 5: build_reprice_policy factory
# ---------------------------------------------------------------------------


def _config(min_pct: float = 0.0, override_seconds: float = 0.0) -> ExecutorConfig:
    return ExecutorConfig(
        execution=OrderExecutionStrategy.BEST_PRICE,
        max_spread_pct=0.01,
        min_reprice_threshold_pct=Decimal(str(min_pct)),
        reprice_override_after_seconds=override_seconds,
    )


def test_build_reprice_policy_backward_compat_returns_always_reprice() -> None:
    """Behavior 5a: When both thresholds are 0.0, factory returns AlwaysRepricePolicy."""
    policy = build_reprice_policy(_config(min_pct=0.0, override_seconds=0.0))
    assert isinstance(policy, AlwaysRepricePolicy)
    # AlwaysRepricePolicy always returns True
    assert policy.should_reprice(Decimal("100"), Decimal("100"), elapsed_seconds=0.0) is True


def test_build_reprice_policy_min_change_only() -> None:
    """Behavior 5b: When only min_change_pct is set, factory returns MinChangeRepricePolicy."""
    policy = build_reprice_policy(_config(min_pct=0.005, override_seconds=0.0))
    assert isinstance(policy, MinChangeRepricePolicy)
    # Small change below 0.5% → False
    assert policy.should_reprice(Decimal("100"), Decimal("100.3"), elapsed_seconds=0.0) is False
    # Change above 0.5% → True
    assert policy.should_reprice(Decimal("100"), Decimal("101.0"), elapsed_seconds=0.0) is True


def test_build_reprice_policy_both_thresholds_returns_elapsed_time_policy() -> None:
    """Behavior 5c: When both thresholds are set, factory returns ElapsedTimeRepricePolicy wrapping MinChange."""
    policy = build_reprice_policy(_config(min_pct=0.01, override_seconds=30.0))
    assert isinstance(policy, ElapsedTimeRepricePolicy)
    # Below elapsed override and below min change → False
    assert policy.should_reprice(Decimal("100"), Decimal("100.3"), elapsed_seconds=5.0) is False
    # At override elapsed, any change → True
    assert policy.should_reprice(Decimal("100"), Decimal("100.3"), elapsed_seconds=30.0) is True
