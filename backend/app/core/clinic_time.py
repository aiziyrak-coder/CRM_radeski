"""Clinic calendar: time zone and working hours (Mon–Sat 08:00–18:00, Asia/Tashkent)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings

OPEN = time(8, 0)
CLOSE = time(18, 0)
WORKDAYS = {0, 1, 2, 3, 4, 5}  # Sunday is a day off


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().tz)


def now() -> datetime:
    return datetime.now(UTC)


def local(dt: datetime) -> datetime:
    return dt.astimezone(tz())


def today() -> date:
    return local(now()).date()


def at(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tz())


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = at(day, time(0))
    return start, start + timedelta(days=1)


def is_open(dt: datetime) -> bool:
    d = local(dt)
    return d.weekday() in WORKDAYS and OPEN <= d.time() < CLOSE


def next_opening(dt: datetime) -> datetime:
    """dt itself if the clinic is open, else the next opening time."""
    d = local(dt)
    if is_open(d):
        return d
    day = d.date() if d.time() < OPEN else d.date() + timedelta(days=1)
    while day.weekday() not in WORKDAYS:
        day += timedelta(days=1)
    return at(day, OPEN)


def add_working_minutes(dt: datetime, minutes: int) -> datetime:
    """SLA arithmetic: count only minutes when the clinic is open (TZ 4.4)."""
    start = next_opening(dt)
    close = at(local(start).date(), CLOSE)
    candidate = start + timedelta(minutes=minutes)
    if candidate <= close:
        return candidate
    remaining = minutes - int((close - start).total_seconds() // 60)
    return add_working_minutes(close, remaining)


def next_workday_at(day: date, t: time) -> datetime:
    day += timedelta(days=1)
    while day.weekday() not in WORKDAYS:
        day += timedelta(days=1)
    return at(day, t)
