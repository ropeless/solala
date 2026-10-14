from datetime import datetime, date, time


def ensure_date(obj: date):
    if isinstance(obj, datetime):
        return obj.date()  # Extracts the date portion
    elif isinstance(obj, date):
        return obj
    raise TypeError('Expected date or datetime object')


def date_to_datetime(obj: date) -> datetime:
    return datetime.combine(ensure_date(obj), time.min)
