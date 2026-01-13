from decimal import Decimal

import pytest

from traxon_core.decimals import (
    ceil_to_step,
    floor_to_step,
    is_equal,
    is_zero,
    round_to_step,
    safe_div,
    to_decimal,
)


def test_to_decimal_valid_inputs():
    assert to_decimal("1.5") == Decimal("1.5")
    assert to_decimal(1) == Decimal("1")
    assert to_decimal(Decimal("2.5")) == Decimal("2.5")

    # Float conversion should be via string to preserve literal value
    assert to_decimal(1.1) == Decimal("1.1")


def test_to_decimal_strict_error_handling():
    with pytest.raises(ValueError):
        to_decimal("")

    with pytest.raises(ValueError):
        to_decimal("abc")

    with pytest.raises(TypeError):
        to_decimal(None)

    with pytest.raises(TypeError):
        to_decimal([])


def test_round_to_step():
    step = Decimal("0.01")

    assert round_to_step(Decimal("1.234"), step) == Decimal("1.23")
    assert round_to_step(Decimal("1.235"), step) == Decimal("1.24")
    assert round_to_step(Decimal("1.236"), step) == Decimal("1.24")


def test_floor_to_step():
    step = Decimal("0.01")

    assert floor_to_step(Decimal("1.239"), step) == Decimal("1.23")
    assert floor_to_step(Decimal("1.231"), step) == Decimal("1.23")
    assert floor_to_step(Decimal("1.230"), step) == Decimal("1.23")


def test_ceil_to_step():
    step = Decimal("0.01")

    assert ceil_to_step(Decimal("1.231"), step) == Decimal("1.24")
    assert ceil_to_step(Decimal("1.239"), step) == Decimal("1.24")
    assert ceil_to_step(Decimal("1.230"), step) == Decimal("1.23")


def test_safe_div():
    assert safe_div(Decimal("10"), Decimal("2")) == Decimal("5")
    assert safe_div(Decimal("10"), Decimal("0")) == Decimal("0")
    assert safe_div(Decimal("10"), Decimal("0"), default=Decimal("1")) == Decimal("1")


def test_is_zero():
    assert is_zero(Decimal("0")) is True
    assert is_zero(Decimal("0.0000000001")) is True  # Within tolerance
    assert is_zero(Decimal("0.0000001")) is False  # Outside tolerance


def test_is_equal():
    assert is_equal(Decimal("1.0000000001"), Decimal("1.0")) is True
    assert is_equal(Decimal("1.1"), Decimal("1.1")) is True
    assert is_equal(Decimal("1.1"), Decimal("1.2")) is False
