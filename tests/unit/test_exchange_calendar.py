from datetime import date, datetime
from unittest.mock import MagicMock, patch

import polars as pl

from traxon_core.exchange_calendar import ExchangeCalendar


class TestExchangeCalendar:
    def test_initialization(self):
        """Test that the calendar is initialized with the correct exchange name and starts unloaded."""
        exchange_name = "XNYS"
        calendar = ExchangeCalendar(exchange_name)

        assert calendar.exchange_name == exchange_name
        assert calendar._calendar is None

    def test_lazy_loading(self):
        """Test that the calendar is loaded only when accessed."""
        exchange_name = "XNYS"
        calendar = ExchangeCalendar(exchange_name)

        with patch("exchange_calendars.get_calendar") as mock_get_calendar:
            mock_cal_instance = MagicMock()
            mock_get_calendar.return_value = mock_cal_instance

            # Should trigger load
            _ = calendar.calendar

            mock_get_calendar.assert_called_once()
            assert mock_get_calendar.call_args[0][0] == exchange_name
            assert calendar._calendar == mock_cal_instance

            # Second access should not trigger load
            _ = calendar.calendar
            mock_get_calendar.assert_called_once()

    def test_get_month_trading_days(self):
        """Test that get_month_trading_days returns correct days for a given month."""
        exchange_name = "XNYS"
        calendar = ExchangeCalendar(exchange_name)

        # January 2024: 1st (New Year - Closed), 15th (MLK - Closed)
        test_date = date(2024, 1, 10)
        trading_days = calendar.get_month_trading_days(test_date)

        assert isinstance(trading_days, pl.Series)
        assert trading_days.dtype == pl.Date
        assert date(2024, 1, 1) not in trading_days.to_list()
        assert date(2024, 1, 2) in trading_days.to_list()
        assert date(2024, 1, 15) not in trading_days.to_list()
        assert len(trading_days) == 21  # 23 weekdays - 2 holidays

    def test_is_nth_trading_day(self):
        """Test is_nth_trading_day logic."""
        exchange_name = "XNYS"
        calendar = ExchangeCalendar(exchange_name)

        # Jan 2nd 2024 is the 1st trading day
        assert calendar.is_nth_trading_day(1, datetime(2024, 1, 2)) is True
        # Jan 3rd 2024 is the 2nd trading day
        assert calendar.is_nth_trading_day(2, datetime(2024, 1, 3)) is True
        # Jan 1st 2024 is NOT a trading day
        assert calendar.is_nth_trading_day(1, datetime(2024, 1, 1)) is False

    def test_n_trading_days_ago(self):
        """Test n_trading_days_ago logic."""
        exchange_name = "XNYS"
        calendar = ExchangeCalendar(exchange_name)

        # Tuesday, Jan 2nd 2024. 0 days ago is Jan 2nd.
        assert calendar.n_trading_days_ago(0, datetime(2024, 1, 2)) == date(2024, 1, 2)
        # 1 trading day ago from Jan 2nd is Friday, Dec 29th 2023
        assert calendar.n_trading_days_ago(1, datetime(2024, 1, 2)) == date(2023, 12, 29)

    def test_curr_trading_day(self):
        """Test curr_trading_day logic."""
        exchange_name = "XNYS"
        calendar = ExchangeCalendar(exchange_name)

        assert calendar.curr_trading_day(datetime(2024, 1, 2)) == date(2024, 1, 2)
        # Saturday Jan 6th 2024. Current trading day (last session) is Friday Jan 5th.
        assert calendar.curr_trading_day(datetime(2024, 1, 6)) == date(2024, 1, 5)

    def test_is_trading_day(self):
        """Test is_trading_day logic."""
        exchange_name = "XNYS"
        calendar = ExchangeCalendar(exchange_name)

        assert calendar.is_trading_day(datetime(2024, 1, 2)) is True
        assert calendar.is_trading_day(datetime(2024, 1, 1)) is False  # New Year
        assert calendar.is_trading_day(datetime(2024, 1, 6)) is False  # Saturday

    def test_dynamic_resizing(self):
        """Test that the calendar is reloaded when out of bounds."""
        exchange_name = "XNYS"
        calendar = ExchangeCalendar(exchange_name)

        # Load initially
        cal = calendar.calendar
        initial_last = cal.last_session

        # Request a date far in the future (Sunday, Jan 14th 2029)
        future_date = datetime(initial_last.year + 2, 1, 14)

        # This should trigger a reload
        assert calendar.is_trading_day(future_date) is False

        # Verify reload happened and bounds extended
        assert calendar.calendar.last_session.date() >= future_date.date()
        assert calendar.calendar is not cal  # New instance
