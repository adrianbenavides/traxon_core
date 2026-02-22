"""
Unit tests for ExecutionReport model (step 03-03).

Test Budget: 3 behaviors x 2 = 6 max unit tests.

Behaviors:
  B4 - ExecutionReport requires exchange_id (ValidationError when absent)
  B5 - ExecutionReport requires fill_latency_ms (ValidationError when absent)
  B6 - fill_latency_ms >= 0 constraint enforced
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus


def _valid_report_kwargs(**overrides) -> dict:
    """Return a complete set of valid ExecutionReport fields."""
    base = dict(
        id="ord-001",
        symbol="BTC/USDT",
        status=OrderStatus.CLOSED,
        amount=Decimal("0.1"),
        filled=Decimal("0.1"),
        remaining=Decimal("0"),
        timestamp=1700000000000,
        exchange_id="bybit",
        fill_latency_ms=120,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# B4 — exchange_id is required
# ---------------------------------------------------------------------------


def test_execution_report_raises_when_exchange_id_is_absent() -> None:
    """ExecutionReport construction raises ValidationError when exchange_id is missing."""
    kwargs = _valid_report_kwargs()
    del kwargs["exchange_id"]

    with pytest.raises(ValidationError) as exc_info:
        ExecutionReport(**kwargs)

    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "exchange_id" in field_names


def test_execution_report_accepts_non_empty_exchange_id() -> None:
    """ExecutionReport accepts a valid non-empty exchange_id."""
    report = ExecutionReport(**_valid_report_kwargs(exchange_id="binance"))

    assert report.exchange_id == "binance"


# ---------------------------------------------------------------------------
# B5 — fill_latency_ms is required
# ---------------------------------------------------------------------------


def test_execution_report_raises_when_fill_latency_ms_is_absent() -> None:
    """ExecutionReport construction raises ValidationError when fill_latency_ms is missing."""
    kwargs = _valid_report_kwargs()
    del kwargs["fill_latency_ms"]

    with pytest.raises(ValidationError) as exc_info:
        ExecutionReport(**kwargs)

    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "fill_latency_ms" in field_names


def test_execution_report_stores_fill_latency_ms() -> None:
    """ExecutionReport stores fill_latency_ms equal to the value provided."""
    report = ExecutionReport(**_valid_report_kwargs(fill_latency_ms=250))

    assert report.fill_latency_ms == 250


# ---------------------------------------------------------------------------
# B6 — fill_latency_ms >= 0 constraint
# ---------------------------------------------------------------------------


def test_execution_report_raises_when_fill_latency_ms_is_negative() -> None:
    """ExecutionReport raises ValidationError when fill_latency_ms is negative."""
    with pytest.raises(ValidationError) as exc_info:
        ExecutionReport(**_valid_report_kwargs(fill_latency_ms=-1))

    errors = exc_info.value.errors()
    field_names = [e["loc"][0] for e in errors]
    assert "fill_latency_ms" in field_names


def test_execution_report_accepts_zero_fill_latency_ms() -> None:
    """fill_latency_ms = 0 is valid (instantaneous fill)."""
    report = ExecutionReport(**_valid_report_kwargs(fill_latency_ms=0))

    assert report.fill_latency_ms == 0
