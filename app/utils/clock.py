"""Time helpers. All timestamps are stored as naive UTC; 'days' use APP_TIMEZONE.

Tests monkeypatch ``_now`` to control the clock.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def now_utc() -> datetime:
    """Naive UTC datetime."""
    return _now().astimezone(timezone.utc).replace(tzinfo=None)


def get_tz(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def local_today(tzname: str) -> date:
    return _now().astimezone(get_tz(tzname)).date()


def to_local(dt: datetime, tzname: str) -> datetime:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(get_tz(tzname))


def local_day_start_utc(d: date, tzname: str) -> datetime:
    """UTC (naive) instant at which local calendar day ``d`` begins."""
    start = datetime(d.year, d.month, d.day, tzinfo=get_tz(tzname))
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def range_start_utc(name: str, tzname: str):
    """Start of 'today' / 'week' (Monday) / 'month' / 'all' (None) as naive UTC."""
    today = local_today(tzname)
    if name == "all":
        return None
    if name == "today":
        return local_day_start_utc(today, tzname)
    if name == "week":
        return local_day_start_utc(today - timedelta(days=today.weekday()), tzname)
    if name == "month":
        return local_day_start_utc(today.replace(day=1), tzname)
    raise ValueError("invalid range")


def format_duration(seconds) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
