from datetime import datetime, date, time, UTC, tzinfo
from typing import Optional


def local_time_zone() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        return UTC
    else:
        return local_tz


def now() -> datetime:
    """
    Returns:
        A timestamp in UTC.
    """
    return datetime.now(UTC)


def ensure_date(obj: date, tz: Optional[tzinfo] = None) -> date:
    """
    Return a pure date (not a datetime).

    If obj is a datetime, and tz is provided, then it is converted to the specified timezone
    before extracting the date portion.
    """
    if isinstance(obj, datetime):
        if tz is not None:
            obj = obj.astimezone(tz)
        return obj.date()  # Extracts the date portion only
    elif isinstance(obj, date):
        return obj
    raise TypeError('Expected date or datetime object')


def date_to_datetime(obj: date) -> datetime:
    return datetime.combine(ensure_date(obj), time.min)
