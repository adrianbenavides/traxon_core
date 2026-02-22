"""
RejectionClassifier: classify ccxt exceptions as FATAL or TRANSIENT.

FATAL  -> permanent business errors (InsufficientFunds, BadSymbol)
           caller should notify pairing and emit order_failed without retrying
TRANSIENT -> recoverable errors (RateLimitExceeded, NetworkError, unknown)
             caller should apply backoff and retry
"""

from __future__ import annotations

from enum import Enum

from ccxt.base.errors import (  # type: ignore[import-untyped]
    BadSymbol,
    InsufficientFunds,
    NetworkError,
    RateLimitExceeded,
)

_FATAL_TYPES = (InsufficientFunds, BadSymbol)
_TRANSIENT_TYPES = (RateLimitExceeded, NetworkError)


class RejectionSeverity(str, Enum):
    FATAL = "fatal"
    TRANSIENT = "transient"


class RejectionClassifier:
    """Classify an exception as FATAL or TRANSIENT."""

    @staticmethod
    def classify(exc: Exception) -> RejectionSeverity:
        """
        Return RejectionSeverity for the given exception.

        InsufficientFunds and BadSymbol -> FATAL
        RateLimitExceeded and NetworkError -> TRANSIENT
        Unknown exceptions -> TRANSIENT (safe default; avoids silencing real bugs)
        """
        if isinstance(exc, _FATAL_TYPES):
            return RejectionSeverity.FATAL
        return RejectionSeverity.TRANSIENT
