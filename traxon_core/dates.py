from datetime import date, datetime, timedelta
from typing import Literal

import exchange_calendars as ecals
import pandas as pd
from beartype import beartype

rfc3339_format: str = "%Y-%m-%dT%H:%M:%SZ"
date_format: str = "%Y-%m-%d"


@beartype
def as_ymd_str(ddate: date | datetime) -> str:
    return ddate.strftime(date_format)


@beartype
def to_datetime(ddate: str | date | datetime, fmt: str = date_format) -> datetime:
    if isinstance(ddate, str):
        return datetime.strptime(ddate, fmt)
    elif isinstance(ddate, date) and not isinstance(ddate, datetime):
        return datetime.combine(ddate, datetime.min.time())
    else:
        return ddate


@beartype
def to_rfc3339(ddate: datetime) -> str:
    return ddate.strftime(rfc3339_format)


@beartype
def is_older_than(ddate: str | date | datetime, delta: timedelta) -> bool:
    ddate_dt = to_datetime(ddate)
    return datetime.today() - ddate_dt > delta


@beartype
def is_nth_trading_day(n: int, today: datetime) -> bool:
    today_date: date = today.date()
    trading_days = get_month_trading_days(today_date)
    return today_date in trading_days and trading_days.index(today_date) == n - 1


@beartype
def last_nth_trading_day(n: int, today: datetime) -> date:
    today_trading_day: date = curr_trading_day(today)
    today_date: date = today.date()
    trading_days = get_month_trading_days(today_date)
    last_nth_day: date = trading_days[n - 1]

    # If the nth trading day is in the future, get the nth trading day of last month
    if last_nth_day > today_trading_day:
        last_day_last_month: date = today_date.replace(day=1) - timedelta(days=1)
        trading_days = get_month_trading_days(last_day_last_month)
        last_nth_day = trading_days[n - 1]

    return last_nth_day


@beartype
def n_trading_days_ago(n: int, today: datetime) -> date:
    today_date: date = today.date()
    start: date = today_date - timedelta(days=10 + max(max(1, n), n))
    nyse = ecals.get_calendar("XNYS")
    trading_days_pd: pd.DatetimeIndex = nyse.sessions_in_range(pd.Timestamp(start), pd.Timestamp(today_date))
    trading_days: list[date] = [d.date() for d in trading_days_pd]
    return trading_days[-(n + 1)]


@beartype
def curr_trading_day(today: datetime) -> date:
    return n_trading_days_ago(0, today)


@beartype
def prev_trading_day(today: datetime) -> date:
    n: Literal[0, 1] = 1 if is_trading_day(today) else 0
    return n_trading_days_ago(n, today)


@beartype
def is_eom(today: datetime) -> bool:
    today_date: date = today.date()
    trading_days = get_month_trading_days(today_date)
    return today_date in trading_days and today_date == trading_days[-1]


@beartype
def last_eom(today: datetime) -> date:
    today_date: date = today.date()
    last_day_last_month: date = today_date.replace(day=1) - timedelta(days=1)
    trading_days = get_month_trading_days(last_day_last_month)
    return trading_days[-1]


@beartype
def is_trading_day(today: datetime) -> bool:
    today_date: date = today.date()
    nyse = ecals.get_calendar(
        "XNYS", start=today_date - timedelta(days=5), end=today_date + timedelta(days=5)
    )
    schedule_index: pd.DatetimeIndex = nyse.schedule.index
    return bool(schedule_index.isin([pd.Timestamp(today_date)]).any())


@beartype
def get_market_close_time(today: datetime) -> datetime | None:
    today_date: date = today.date()
    nyse = ecals.get_calendar(
        "XNYS", start=today_date - timedelta(days=5), end=today_date + timedelta(days=1)
    )

    today_str: str = as_ymd_str(today_date)
    if today_str in nyse.schedule.index:
        close_timestamp: pd.Timestamp = nyse.schedule.loc[today_str]["close"]
        return close_timestamp.to_pydatetime()
    else:
        return None


@beartype
def get_month_trading_days(today: date) -> list[date]:
    start_of_month: date = today.replace(day=1)
    end_of_month: date = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    nyse = ecals.get_calendar("XNYS", start=today - timedelta(days=365), end=today + timedelta(days=365))
    trading_days: pd.DatetimeIndex = nyse.sessions_in_range(
        pd.Timestamp(start_of_month), pd.Timestamp(end_of_month)
    )
    return [d.date() for d in trading_days]
