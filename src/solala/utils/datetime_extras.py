from datetime import datetime, date, time, UTC, tzinfo


def local_time_zone() -> tzinfo:
    """
    Get the system's current local timezone information.

    Returns:
        Local timezone information, or UTC if it is unavailable.
    """
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        return UTC
    else:
        return local_tz


def now() -> datetime:
    """
    Get the current timezone-aware UTC datetime.

    Returns:
        The current datetime in UTC.
    """
    return datetime.now(UTC)


def ensure_date(obj: date, tz: tzinfo | None = None) -> date:
    """
    Return a date without a time component.

    If the input is a datetime and a timezone is supplied, convert the
    datetime to that timezone before extracting its date. A date input is
    returned unchanged.

    Args:
        obj: Date or datetime to convert.
        tz: Optional timezone used when the input is a datetime.

    Returns:
        Date corresponding to the input.
    """
    if isinstance(obj, datetime):
        if tz is not None:
            obj = obj.astimezone(tz)
        return obj.date()  # Extracts the date portion only
    elif isinstance(obj, date):
        return obj


def date_to_datetime(obj: date, tz: tzinfo | None = None) -> datetime:
    """
    Convert a date to a datetime at midnight.

    The initial datetime is naive. If a timezone is provided, `astimezone()`
    converts it from the system's local timezone to the requested timezone.

    Args:
        obj: Date to convert.
        tz: Optional target timezone.

    Returns:
        Midnight as a naive datetime, or a timezone-aware converted datetime
        when `tz` is supplied.
    """
    result = datetime.combine(ensure_date(obj), time.min)
    if tz is not None:
        result = result.astimezone(tz)
    return result
