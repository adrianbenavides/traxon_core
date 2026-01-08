from hypothesis import given
from hypothesis import strategies as st

from traxon_core.floats import FLOAT_TOLERANCE, float_is_zero, floats_equal


def test_floats_equal_basic():
    assert floats_equal(1.0, 1.0)
    assert floats_equal(1.0, 1.0001) is False  # Default tol is 1e-5


def test_floats_equal_custom_tol():
    assert floats_equal(1.0, 1.01, tol=0.1)


def test_float_is_zero_basic():
    assert float_is_zero(0.0)
    assert float_is_zero(1e-10)
    assert float_is_zero(1.0) is False


def test_float_is_zero_custom_tol():
    assert float_is_zero(0.1, tol=0.2)


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_floats_equal_hypothesis_identity(f):
    assert floats_equal(f, f)


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_float_is_zero_hypothesis(f):
    if abs(f) <= FLOAT_TOLERANCE:
        assert float_is_zero(f)
    else:
        assert not float_is_zero(f)
