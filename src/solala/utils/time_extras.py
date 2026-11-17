from datetime import datetime, date, time, UTC, tzinfo, timedelta


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
        obj: an object of type `date` or `datetime` to convert.
        tz: Optional timezone, which is used when the input is a datetime.

    Returns:
        Date corresponding to `obj`.
    """
    if isinstance(obj, datetime):
        if tz is not None:
            obj = obj.astimezone(tz)
        return obj.date()  # Extracts the date portion only
    elif isinstance(obj, date):
        return obj


def date_to_datetime(obj: date, tz: tzinfo | None = None) -> datetime:
    """
    Convert a date to midnight in the specified timezone.

    The returned datetime is always timezone-aware. If no timezone is
    supplied, UTC is used. The date and midnight time are interpreted
    directly in the chosen timezone, rather than converted from the
    system's local timezone.

    Args:
        obj: Date to convert. If a datetime is supplied, its date is used.
        tz: Timezone for the result, defaulting to UTC.

    Returns:
        A timezone-aware datetime at midnight in the chosen timezone.
    """
    return datetime.combine(ensure_date(obj), time.min, tzinfo=tz or UTC)


def render_timedelta(value: timedelta) -> str:
    seconds_float: float = value.total_seconds()
    whole_seconds = int(seconds_float)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if whole_seconds != seconds_float:
        seconds += seconds_float - whole_seconds

    if hours > 0:
        if minutes == 0 and seconds == 0:
            if hours == 1:
                return '1 hour'
            return f'{hours} hours'
        else:
            return f'{hours}:{minutes}:{seconds} seconds'
    if minutes > 0:
        if seconds == 0:
            if minutes == 1:
                return f'1 minute'
            return f'{minutes} minutes'
        else:
            return f'{minutes}:{seconds} seconds'
    if seconds == 1:
        return f'1 second'
    return f'{seconds} seconds'
