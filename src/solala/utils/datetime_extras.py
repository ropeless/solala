from datetime import datetime, date, time, UTC


def now() -> datetime:
    """
    Returns:
        A timestamp in UTC.
    """
    return datetime.now(UTC)


def ensure_date(obj: date) -> date:
    if isinstance(obj, datetime):
        return obj.date()  # Extracts the date portion
    elif isinstance(obj, date):
        return obj
    raise TypeError('Expected date or datetime object')


def date_to_datetime(obj: date) -> datetime:
    return datetime.combine(ensure_date(obj), time.min)
