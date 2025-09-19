# tt/timeparse.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

def now_local() -> datetime:
    return datetime.now().astimezone()

def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

def start_of_week(dt: datetime) -> datetime:
    # Monday as start (ISO)
    d0 = start_of_day(dt)
    return d0 - timedelta(days=d0.weekday())

def start_of_month(dt: datetime) -> datetime:
    d0 = start_of_day(dt)
    return d0.replace(day=1)

def parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.lower() == "now":
        return now_local()
    # allow "YYYY-MM-DD HH:MM"
    if " " in s and "T" not in s:
        s = s.replace(" ", "T")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now_local().tzinfo)
    return dt.astimezone()

def parse_point(name: Optional[str]) -> Optional[datetime]:
    if not name:
        return None
    key = name.strip().lower()
    n = now_local()
    if key == "today":
        return start_of_day(n)
    if key == "yesterday":
        return start_of_day(n) - timedelta(days=1)
    if key == "monday":
        return start_of_week(n)
    if key == "week":
        return start_of_week(n)
    if key == "last-week":
        return start_of_week(n) - timedelta(days=7)
    if key == "month":
        return start_of_month(n)
    if key == "now":
        return n
    # otherwise ISO-ish
    return parse_dt(name)

def window(since: Optional[str], until: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    s = parse_point(since) if since else None
    u = parse_point(until) if until else None
    return s, u
