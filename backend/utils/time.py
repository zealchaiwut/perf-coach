from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

_UTC = timezone.utc
_BKK = ZoneInfo("Asia/Bangkok")


def now_utc() -> datetime:
    return datetime.now(_UTC)


def now_bangkok() -> datetime:
    return datetime.now(_BKK)


def today_bangkok() -> date:
    return datetime.now(_BKK).date()


def to_bangkok(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("dt must be timezone-aware")
    return dt.astimezone(_BKK)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("dt must be timezone-aware")
    return dt.astimezone(_UTC)


def format_iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_iso(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Cannot parse ISO datetime: {s!r}") from exc
    if dt.tzinfo is None:
        raise ValueError(f"Parsed datetime is naive: {s!r}")
    return dt
