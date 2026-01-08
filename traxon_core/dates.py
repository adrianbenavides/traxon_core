from datetime import date, datetime, timedelta

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
