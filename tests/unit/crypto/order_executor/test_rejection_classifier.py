"""
Unit tests for RejectionClassifier (step 03-02).

Test Budget: 2 behaviors x 2 = 4 max unit tests.

Behaviors:
  B1 - FATAL for InsufficientFunds and BadSymbol exceptions
  B2 - TRANSIENT for RateLimitExceeded, NetworkError, and unknown exceptions
"""

from __future__ import annotations

import pytest
from ccxt.base.errors import (  # type: ignore[import-untyped]
    BadSymbol,
    InsufficientFunds,
    NetworkError,
    RateLimitExceeded,
)

from traxon_core.crypto.order_executor.rejection import RejectionClassifier, RejectionSeverity


class TestFatalRejections:
    @pytest.mark.parametrize(
        "exc",
        [
            InsufficientFunds("not enough funds"),
            BadSymbol("unknown symbol"),
        ],
    )
    def test_classifies_fatal_exceptions(self, exc: Exception) -> None:
        severity = RejectionClassifier.classify(exc)
        assert severity == RejectionSeverity.FATAL


class TestTransientRejections:
    @pytest.mark.parametrize(
        "exc",
        [
            RateLimitExceeded("rate limit hit"),
            NetworkError("connection reset"),
            ValueError("some unknown error"),
        ],
    )
    def test_classifies_transient_exceptions(self, exc: Exception) -> None:
        severity = RejectionClassifier.classify(exc)
        assert severity == RejectionSeverity.TRANSIENT
