from math import isclose
from typing import Final

from beartype import beartype

FLOAT_TOLERANCE: Final[float] = 1e-5


@beartype
def floats_equal(a: float, b: float, tol: float | None = None) -> bool:
    """Compare two floats for equality with explicit tolerance."""
    if tol is None:
        tol = FLOAT_TOLERANCE
    return isclose(a, b, rel_tol=tol, abs_tol=tol)


@beartype
def float_is_zero(a: float, tol: float | None = None) -> bool:
    """Check if a float is effectively zero with explicit tolerance."""
    if tol is None:
        tol = FLOAT_TOLERANCE
    return isclose(a, 0.0, rel_tol=tol, abs_tol=tol)
