# tt/timeparse.py
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, Tuple
from . import config as cfgmod

# ---------------- basics ----------------

def now_local() -> datetime:
    return datetime.now().astimezone()

def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

def start_of_week(dt: datetime) -> datetime:
    # Monday (ISO) start
    d0 = start_of_day(dt)
    return d0 - timedelta(days=d0.weekday())

def start_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

# ---------------- config ----------------

def _strict_iso_enabled() -> bool:
    try:
        cfg = cfgmod.load()
        return bool((cfg.get("input") or {}).get("strict_iso", False))
    except Exception:
        return False

# ---------------- parsing helpers ----------------

def _parse_iso_or_space(dt_str: str) -> datetime:
    """Parse ISO 8601; also accept 'YYYY-MM-DD HH:MM[:SS]' by replacing the space with 'T'.
    Raises ValueError with a helpful message on failure.
    """
    s = dt_str.strip()
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
    except Exception as e:
        raise ValueError(
            f"Invalid date/time {dt_str!r}. Expected ISO like 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DDTHH:MM', with optional timezone."
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now_local().tzinfo)
    return dt.astimezone()

def _parse_flexible_datetime(dt_str: str, now: Optional[datetime] = None) -> datetime:
    """Flexible parse:
    - 'YYYY-MM-DD HH:MM' (space) or ISO 8601
    - 'HH:MM' → today at that local time
    - ':MM'   → today at current hour and given minutes
    - 'today' → today 00:00
    - 'yesterday' → yesterday 00:00
    - 'now' → current timestamp
    """
    now = now or now_local()
    s = (dt_str or '').strip().lower()
    if s in ("today", ):
        return start_of_day(now)
    if s in ("yesterday", ):
        return start_of_day(now - timedelta(days=1))
    if s in ("now", ):
        return now

    # HH:MM or :MM (today)
    if s.startswith(":") and len(s) >= 2 and s[1:].isdigit():
        minute = int(s[1:])
        return now.replace(minute=minute, second=0, microsecond=0)
    if ":" in s and len(s) <= 5 and all(part.isdigit() for part in s.split(":", 1)):
        # '9:30', '09:05'
        h, m = s.split(":", 1)
        hour = int(h)
        minute = int(m)
        base = now
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # date-only: treat as midnight
    if len(s) == 10 and s.count("-") == 2 and s[4] == '-' and s[7] == '-':
        return _parse_iso_or_space(s)

    # ISO or 'YYYY-MM-DD HH:MM[:SS]'
    return _parse_iso_or_space(s)

def parse_dt(dt_str: str) -> datetime:
    """Parse a datetime string obeying the strict ISO toggle in config.

    Config:

      input.strict_iso: true|false (default false)

    """
    if _strict_iso_enabled():
        return _parse_iso_or_space(dt_str)
    return _parse_flexible_datetime(dt_str)

# ---------------- windows ----------------

def parse_point(name: str) -> datetime:
    """Accept common anchors: today, yesterday, week, last-week, month, now; or a datetime."""
    n = now_local()
    key = (name or '').strip().lower()
    if key == "today":
        return start_of_day(n)
    if key == "yesterday":
        return start_of_day(n - timedelta(days=1))
    if key == "week":
        return start_of_week(n)
    if key == "last-week":
        return start_of_week(n) - timedelta(days=7)
    if key == "month":
        return start_of_month(n)
    if key == "now":
        return n
    # otherwise parse datetime
    return parse_dt(name)

def window(since: Optional[str], until: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    s = parse_point(since) if since else None
    u = parse_point(until) if until else None
    return s, u

import re

def _parse_ago(s: str) -> int:
    """
    Parse human-readable duration strings like:
    '90m', '2h', '1h30m', '1d2h', etc., and return total seconds.
    """
    s = s.strip().lower()
    total_seconds = 0
    pattern = r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?"
    match = re.match(pattern, s)
    if not match:
        raise ValueError(f"Invalid duration format: {s}")
    days, hours, minutes = match.groups()
    if days:
        total_seconds += int(days) * 86400
    if hours:
        total_seconds += int(hours) * 3600
    if minutes:
        total_seconds += int(minutes) * 60
    if total_seconds == 0:
        raise ValueError(f"No valid duration found in: {s}")
    return total_seconds


def format_minutes(minutes: int) -> str:
    """Format total minutes as H:MM."""
    hours, mins = divmod(minutes, 60)
    return f"{hours}:{mins:02d}"
