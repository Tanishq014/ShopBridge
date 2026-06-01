from __future__ import annotations

from datetime import datetime, timedelta, timezone


LOCAL_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="IST")


def local_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TIMEZONE)


def format_local_datetime(value: datetime | None, fmt: str = "%d-%m-%Y %H:%M") -> str:
    local_value = local_datetime(value)
    return local_value.strftime(fmt) if local_value else ""
