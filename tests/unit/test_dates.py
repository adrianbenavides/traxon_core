from datetime import date, datetime, timedelta

from traxon_core.dates import (
    as_ymd_str,
    is_older_than,
    to_datetime,
    to_rfc3339,
)


def test_as_ymd_str() -> None:
    d = date(2023, 1, 1)
    dt = datetime(2023, 1, 1, 12, 0)
    assert as_ymd_str(d) == "2023-01-01"
    assert as_ymd_str(dt) == "2023-01-01"


def test_to_datetime() -> None:
    assert to_datetime("2023-01-01") == datetime(2023, 1, 1)
    assert to_datetime(date(2023, 1, 1)) == datetime(2023, 1, 1)
    dt = datetime(2023, 1, 1, 12, 0)
    assert to_datetime(dt) == dt


def test_to_rfc3339() -> None:
    dt = datetime(2023, 1, 1, 12, 0)
    assert to_rfc3339(dt) == "2023-01-01T12:00:00Z"


def test_is_older_than() -> None:
    today = datetime.today()
    old_date = today - timedelta(days=10)
    recent_date = today - timedelta(days=2)
    delta = timedelta(days=5)

    assert is_older_than(old_date, delta)
    assert not is_older_than(recent_date, delta)
