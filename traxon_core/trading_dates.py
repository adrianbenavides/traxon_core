from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional, cast

import exchange_calendars as ecals
import pandas as pd
import polars as pl
from beartype import beartype


class ExchangeCalendar:
    def __init__(self, exchange_name: str) -> None:
        self.exchange_name = exchange_name
        self._calendar: Optional[Any] = None
        self._first_session: Optional[date] = None
        self._last_session: Optional[date] = None

    @property
    def calendar(self) -> Any:
        if self._calendar is None:
            self._calendar = ecals.get_calendar(self.exchange_name)
            self._first_session = self._calendar.first_session.date()
            self._last_session = self._calendar.last_session.date()
        return self._calendar

    def _ensure_bounds(self, target_date: date) -> None:
        """Reload calendar if target_date is out of bounds."""
        # Trigger initial load if needed
        _ = self.calendar

        if (
            self._first_session
            and self._last_session
            and (target_date < self._first_session or target_date > self._last_session)
        ):
            # Extend with a small buffer to ensure is_session works even for non-session days
            start = min(target_date - timedelta(days=7), self._first_session)
            end = max(target_date + timedelta(days=7), self._last_session)
            self._calendar = ecals.get_calendar(self.exchange_name, start=start, end=end)
            self._first_session = self._calendar.first_session.date()
            self._last_session = self._calendar.last_session.date()

    @beartype
    def get_month_trading_days(self, today: date) -> pl.Series:
        start_of_month: date = today.replace(day=1)
        end_of_month: date = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        self._ensure_bounds(start_of_month)
        self._ensure_bounds(end_of_month)

        trading_days_pd: pd.DatetimeIndex = self.calendar.sessions_in_range(
            pd.Timestamp(start_of_month), pd.Timestamp(end_of_month)
        )
        return pl.from_pandas(trading_days_pd.to_series()).dt.date().rename("trading_days")

    @beartype
    def is_nth_trading_day(self, n: int, today: datetime) -> bool:
        today_date: date = today.date()
        trading_days = self.get_month_trading_days(today_date)
        matches = (trading_days == today_date).arg_true()
        if len(matches) == 0:
            return False
        return bool(matches.item() == n - 1)

    @beartype
    def n_trading_days_ago(self, n: int, today: datetime) -> date:
        today_date: date = today.date()
        # Look back far enough to find n sessions
        start: date = today_date - timedelta(days=10 + max(max(1, n), n))

        self._ensure_bounds(start)
        self._ensure_bounds(today_date)

        trading_days_pd: pd.DatetimeIndex = self.calendar.sessions_in_range(
            pd.Timestamp(start), pd.Timestamp(today_date)
        )
        trading_days = pl.from_pandas(trading_days_pd.to_series()).dt.date()
        return cast(date, trading_days.gather(len(trading_days) - (n + 1)).item())

    @beartype
    def curr_trading_day(self, today: datetime) -> date:
        return self.n_trading_days_ago(0, today)

    @beartype
    def is_trading_day(self, today: datetime) -> bool:
        today_date = today.date()
        self._ensure_bounds(today_date)
        return bool(self.calendar.is_session(pd.Timestamp(today_date)))

    @beartype
    def get_market_close_time(self, today: datetime) -> Optional[datetime]:
        today_date = today.date()
        self._ensure_bounds(today_date)
        if not self.is_trading_day(today):
            return None
        return cast(datetime, self.calendar.session_close(pd.Timestamp(today_date)).to_pydatetime())

    @beartype
    def last_nth_trading_day(self, n: int, today: datetime) -> date:
        today_trading_day: date = self.curr_trading_day(today)
        today_date: date = today.date()
        trading_days = self.get_month_trading_days(today_date)
        last_nth_day: date = trading_days.gather(n - 1).item()

        # If the nth trading day is in the future, get the nth trading day of last month
        if last_nth_day > today_trading_day:
            last_day_last_month: date = today_date.replace(day=1) - timedelta(days=1)
            trading_days = self.get_month_trading_days(last_day_last_month)
            last_nth_day = trading_days.gather(n - 1).item()

        return last_nth_day

    @beartype
    def prev_trading_day(self, today: datetime) -> date:
        n: Literal[0, 1] = 1 if self.is_trading_day(today) else 0
        return self.n_trading_days_ago(n, today)

    @beartype
    def is_eom(self, today: datetime) -> bool:
        today_date: date = today.date()
        trading_days = self.get_month_trading_days(today_date)
        if len(trading_days) == 0:
            return False
        return bool(today_date == trading_days.gather(len(trading_days) - 1).item())

    @beartype
    def last_eom(self, today: datetime) -> date:
        today_date: date = today.date()
        last_day_last_month: date = today_date.replace(day=1) - timedelta(days=1)
        trading_days = self.get_month_trading_days(last_day_last_month)
        return cast(date, trading_days.gather(len(trading_days) - 1).item())
