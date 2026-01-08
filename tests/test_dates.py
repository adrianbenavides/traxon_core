from datetime import date, datetime, timedelta

from traxon_core.dates import (
    as_ymd_str,
    curr_trading_day,
    get_market_close_time,
    get_month_trading_days,
    is_eom,
    is_nth_trading_day,
    is_older_than,
    is_trading_day,
    last_eom,
    last_nth_trading_day,
    n_trading_days_ago,
    prev_trading_day,
    to_datetime,
    to_rfc3339,
)


def test_as_ymd_str():
    d = date(2023, 1, 1)
    dt = datetime(2023, 1, 1, 12, 0)
    assert as_ymd_str(d) == "2023-01-01"
    assert as_ymd_str(dt) == "2023-01-01"


def test_to_datetime():
    assert to_datetime("2023-01-01") == datetime(2023, 1, 1)
    assert to_datetime(date(2023, 1, 1)) == datetime(2023, 1, 1)
    dt = datetime(2023, 1, 1, 12, 0)
    assert to_datetime(dt) == dt


def test_to_rfc3339():
    dt = datetime(2023, 1, 1, 12, 0)
    assert to_rfc3339(dt) == "2023-01-01T12:00:00Z"


def test_is_older_than():
    today = datetime.today()
    old_date = today - timedelta(days=10)
    recent_date = today - timedelta(days=2)
    delta = timedelta(days=5)

    assert is_older_than(old_date, delta)
    assert not is_older_than(recent_date, delta)


def test_is_trading_day():
    # Wednesday, 2023-01-04 is a trading day
    assert is_trading_day(datetime(2023, 1, 4))
    # Sunday, 2023-01-01 is not a trading day
    assert not is_trading_day(datetime(2023, 1, 1))
    # Monday, 2023-01-02 was a holiday (New Year's observed)
    assert not is_trading_day(datetime(2023, 1, 2))


def test_curr_trading_day():
    # On a trading day
    assert curr_trading_day(datetime(2023, 1, 4)) == date(2023, 1, 4)
    # On a weekend (Sunday)
    assert curr_trading_day(datetime(2023, 1, 1)) == date(2022, 12, 30)  # Friday


def test_prev_trading_day():
    # Wednesday -> Tuesday
    assert prev_trading_day(datetime(2023, 1, 4)) == date(2023, 1, 3)
    # Tuesday -> Friday (Monday was holiday)
    assert prev_trading_day(datetime(2023, 1, 3)) == date(2022, 12, 30)


def test_is_nth_trading_day():
    # January 2023 trading days: 3, 4, 5, 6, 9, ...
    assert is_nth_trading_day(1, datetime(2023, 1, 3))
    assert is_nth_trading_day(2, datetime(2023, 1, 4))
    assert not is_nth_trading_day(1, datetime(2023, 1, 4))


def test_last_nth_trading_day():
    # 1st trading day of Jan 2023 is Jan 3
    assert last_nth_trading_day(1, datetime(2023, 1, 10)) == date(2023, 1, 3)
    # If today is before the nth day, it should return nth day of last month
    # Dec 2022 1st trading day was Dec 1
    assert last_nth_trading_day(1, datetime(2023, 1, 2)) == date(2022, 12, 1)


def test_is_eom():
    # Jan 2023 last trading day was Jan 31
    assert is_eom(datetime(2023, 1, 31))
    assert not is_eom(datetime(2023, 1, 30))


def test_last_eom():
    # Last EOM from Jan 2023 is Dec 30, 2022
    assert last_eom(datetime(2023, 1, 15)) == date(2022, 12, 30)


def test_n_trading_days_ago():
    # Wednesday Jan 4, 1 trading day ago was Tuesday Jan 3
    assert n_trading_days_ago(1, datetime(2023, 1, 4)) == date(2023, 1, 3)
    # 2 trading days ago was Friday Dec 30 (Monday holiday, weekend)
    assert n_trading_days_ago(2, datetime(2023, 1, 4)) == date(2022, 12, 30)


def test_get_market_close_time():
    # Jan 4, 2023 NYSE closed at 16:00 EST / 21:00 UTC
    close_time = get_market_close_time(datetime(2023, 1, 4))
    assert close_time is not None
    assert close_time.hour == 21 or close_time.hour == 16  # Adjusting for UTC vs local


def test_get_market_close_time_non_trading():
    # Jan 1, 2023 was Sunday
    assert get_market_close_time(datetime(2023, 1, 1)) is None


def test_get_month_trading_days():
    # Jan 2023 had 20 trading days
    days = get_month_trading_days(date(2023, 1, 15))
    assert len(days) == 20
    assert days[0] == date(2023, 1, 3)
    assert days[-1] == date(2023, 1, 31)
