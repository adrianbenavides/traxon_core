"""
Reprice policy protocol and implementations.

Policies control whether a cancel-and-replace should proceed based on
the magnitude of the price change and/or elapsed time since order placement.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from traxon_core.crypto.order_executor.config import ExecutorConfig

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class RepricePolicy(Protocol):
    """Protocol for deciding whether an order should be repriced."""

    def should_reprice(
        self,
        old_price: Decimal,
        new_price: Decimal,
        elapsed_seconds: float,
    ) -> bool:
        """Return True if a cancel-and-replace should proceed."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# AlwaysRepricePolicy — backward-compatible default
# ---------------------------------------------------------------------------


class AlwaysRepricePolicy:
    """Always allows repricing. Used when no threshold is configured."""

    def should_reprice(
        self,
        old_price: Decimal,
        new_price: Decimal,
        elapsed_seconds: float,
    ) -> bool:
        return True


# ---------------------------------------------------------------------------
# MinChangeRepricePolicy
# ---------------------------------------------------------------------------


class MinChangeRepricePolicy:
    """
    Suppresses repricing when the absolute price change is below a minimum
    percentage threshold.

    Attributes:
        min_change_pct: Minimum fractional change required (e.g. 0.005 = 0.5%).
    """

    @beartype
    def __init__(self, min_change_pct: Decimal) -> None:
        self.min_change_pct = min_change_pct

    @beartype
    def should_reprice(
        self,
        old_price: Decimal,
        new_price: Decimal,
        elapsed_seconds: float,
    ) -> bool:
        if old_price == Decimal("0"):
            return new_price != Decimal("0")
        change_pct = abs(new_price - old_price) / old_price
        return change_pct >= self.min_change_pct


# ---------------------------------------------------------------------------
# ElapsedTimeRepricePolicy
# ---------------------------------------------------------------------------


class ElapsedTimeRepricePolicy:
    """
    Delegates to an inner policy unless the elapsed time exceeds a threshold,
    in which case any non-zero price change is allowed through.

    Attributes:
        override_after_seconds: Once elapsed reaches this value, any price change
            triggers a reprice (ignoring inner policy).
        inner: Fallback policy consulted when elapsed < override_after_seconds.
    """

    @beartype
    def __init__(self, override_after_seconds: float, inner: RepricePolicy) -> None:
        self.override_after_seconds = override_after_seconds
        self.inner = inner

    @beartype
    def should_reprice(
        self,
        old_price: Decimal,
        new_price: Decimal,
        elapsed_seconds: float,
    ) -> bool:
        if elapsed_seconds >= self.override_after_seconds:
            return old_price != new_price
        return self.inner.should_reprice(old_price, new_price, elapsed_seconds)


# ---------------------------------------------------------------------------
# CompositeRepricePolicy
# ---------------------------------------------------------------------------


class CompositeRepricePolicy:
    """
    AND-combination of multiple policies: returns True only when every
    constituent policy returns True.

    Attributes:
        policies: List of policies to evaluate in order.
    """

    @beartype
    def __init__(self, policies: list[RepricePolicy]) -> None:
        self.policies = policies

    @beartype
    def should_reprice(
        self,
        old_price: Decimal,
        new_price: Decimal,
        elapsed_seconds: float,
    ) -> bool:
        return all(p.should_reprice(old_price, new_price, elapsed_seconds) for p in self.policies)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


@beartype
def build_reprice_policy(config: ExecutorConfig) -> RepricePolicy:
    """
    Construct the appropriate RepricePolicy from an ExecutorConfig.

    Rules:
    - Both thresholds == 0.0  →  AlwaysRepricePolicy (backward-compatible)
    - Only min_change_pct > 0  →  MinChangeRepricePolicy
    - Both thresholds > 0   →  ElapsedTimeRepricePolicy(inner=MinChangeRepricePolicy)
    """
    has_min_change = config.min_reprice_threshold_pct > Decimal("0.0")
    has_elapsed = config.reprice_override_after_seconds > 0.0

    if not has_min_change and not has_elapsed:
        return AlwaysRepricePolicy()

    if has_min_change and not has_elapsed:
        return MinChangeRepricePolicy(min_change_pct=config.min_reprice_threshold_pct)

    # Both set: elapsed override wraps the min-change inner policy
    inner = MinChangeRepricePolicy(min_change_pct=config.min_reprice_threshold_pct)
    return ElapsedTimeRepricePolicy(
        override_after_seconds=config.reprice_override_after_seconds,
        inner=inner,
    )
