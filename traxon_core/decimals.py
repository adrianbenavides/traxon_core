from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_UP,
    Decimal,
    DivisionByZero,
    InvalidOperation,
)
from typing import Any, Final

from beartype import beartype

# Default tolerance for decimal equality checks if needed
DECIMAL_TOLERANCE: Final[Decimal] = Decimal("1e-9")


@beartype
def to_decimal(value: Any) -> Decimal:
    """
    Convert a value to a Decimal with strict error handling.

    Floats are converted via string representation to preserve literal value.
    Raises ValueError for invalid strings.
    """
    if isinstance(value, Decimal):
        return value

    if isinstance(value, int):
        return Decimal(value)

    if isinstance(value, float):
        return Decimal(str(value))

    if isinstance(value, str):
        if not value:
            raise ValueError("Cannot convert empty string to Decimal")
        try:
            return Decimal(value)
        except InvalidOperation as e:
            raise ValueError(f"Invalid decimal string: {value}") from e

    raise TypeError(f"Cannot convert type {type(value).__name__} to Decimal")


@beartype
def round_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round a Decimal to the nearest step using ROUND_HALF_UP."""
    return value.quantize(step, rounding=ROUND_HALF_UP)


@beartype
def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round a Decimal down to the nearest step using ROUND_FLOOR."""
    return value.quantize(step, rounding=ROUND_FLOOR)


@beartype
def ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round a Decimal up to the nearest step using ROUND_CEILING."""
    return value.quantize(step, rounding=ROUND_CEILING)


@beartype
def safe_div(numerator: Decimal, denominator: Decimal, default: Decimal = Decimal(0)) -> Decimal:
    """
    Safe division that returns a default value on ZeroDivisionError or DivisionByZero.
    """
    try:
        return numerator / denominator
    except (ZeroDivisionError, DivisionByZero):
        return default


@beartype
def is_zero(value: Decimal, tol: Decimal | None = None) -> bool:
    """Check if a Decimal is effectively zero within tolerance."""
    if tol is None:
        tol = DECIMAL_TOLERANCE
    return abs(value) <= tol


@beartype
def is_equal(a: Decimal, b: Decimal, tol: Decimal | None = None) -> bool:
    """Compare two Decimals for equality within tolerance."""
    if tol is None:
        tol = DECIMAL_TOLERANCE
    return abs(a - b) <= tol
