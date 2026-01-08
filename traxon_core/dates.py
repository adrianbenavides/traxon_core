from datetime import date, datetime, timedelta

from beartype import beartype

rfc3339_format: str = "%Y-%m-%dT%H:%M:%SZ"
date_format: str = "%Y-%m-%d"


@beartype
def as_ymd_str(ddate: date | datetime) -> str:
    return ddate.strftime(date_format)


@beartype
def to_datetime(ddate: str | date | datetime | None, fmt: str | None = None) -> datetime | None:
    if ddate is None:
        return None
    if isinstance(ddate, str):
        if fmt:
            return datetime.strptime(ddate, fmt)
        try:
            # Handle CCXT Z suffix and other ISO formats
            return datetime.fromisoformat(ddate.replace("Z", "+00:00"))
        except ValueError:
            # Fallback for simple date strings
            return datetime.strptime(ddate, date_format)
    elif isinstance(ddate, date) and not isinstance(ddate, datetime):
        return datetime.combine(ddate, datetime.min.time())
    else:
        return ddate


@beartype
def to_rfc3339(ddate: datetime) -> str:
    return ddate.strftime(rfc3339_format)


@beartype
def is_older_than(ddate: str | date | datetime | None, delta: timedelta) -> bool:
    ddate_dt = to_datetime(ddate)
    if ddate_dt is None:
        return True  # Or handle as needed; if no date, it's effectively "infinitely old"
    # Ensure timezone awareness if ddate_dt has it
    now = datetime.now(ddate_dt.tzinfo) if ddate_dt.tzinfo else datetime.now()
    return now - ddate_dt > delta
