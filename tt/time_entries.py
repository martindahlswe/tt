# tt/time_entries.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Iterable
from datetime import datetime, timedelta
from .db import connect, now_iso, DEFAULT_DB
from . import timeparse as tparse

# ---------- note + status helpers ----------

def _clean_note(note: Optional[str]) -> Optional[str]:
    if note is None:
        return None
    return " ".join(note.replace("\n", " ").replace("\r", " ").replace("\t", " ").split()) or None

def _set_task_back_to_todo_if_idle(conn, task_id: int) -> None:
    running = conn.execute(
        "SELECT 1 FROM time_entries WHERE task_id=? AND end IS NULL LIMIT 1",
        (task_id,),
    ).fetchone()
    if not running:
        conn.execute("UPDATE tasks SET status='todo' WHERE id=? AND status='doing'", (task_id,))

# ---------- time helpers ----------

def _now_local() -> datetime:
    return datetime.now().astimezone()

def _parse_local_datetime(s: str) -> datetime:
    return tparse.parse_dt(s)

def _overlap_seconds(start_s: str, end_s: Optional[str], win_start: Optional[datetime], win_end: Optional[datetime]) -> int:
    start = datetime.fromisoformat(start_s)
    if start.tzinfo is None:
        start = start.replace(tzinfo=_now_local().tzinfo)
    end = datetime.fromisoformat(end_s) if end_s else _now_local()
    if end.tzinfo is None:
        end = end.replace(tzinfo=_now_local().tzinfo)
    a = start if not win_start else max(start, win_start)
    b = end if not win_end else min(end, win_end)
    if b <= a:
        return 0
    return int((b - a).total_seconds())

# ---------- core timer ops ----------

def current_running(db_path: Path = DEFAULT_DB) -> Optional[Tuple[int, int]]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, task_id FROM time_entries WHERE end IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return (row[0], row[1]) if row else None

def start(task_id: int, db_path: Path = DEFAULT_DB, note: Optional[str] = None) -> int:
    note = _clean_note(note)
    running = current_running(db_path)
    if running:
        stop(db_path=db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO time_entries(task_id, start, note) VALUES (?, ?, ?)",
            (task_id, now_iso(), note),
        )
        conn.execute("UPDATE tasks SET status='doing' WHERE id=?", (task_id,))
        return cur.lastrowid

def stop(task_id: Optional[int] = None, db_path: Path = DEFAULT_DB) -> Optional[int]:
    with connect(db_path) as conn:
        if task_id is None:
            row = conn.execute(
                "SELECT id, task_id FROM time_entries WHERE end IS NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            entry_id, t_id = row
            conn.execute("UPDATE time_entries SET end=? WHERE id=?", (now_iso(), entry_id))
            _set_task_back_to_todo_if_idle(conn, t_id)
            return entry_id
        else:
            row = conn.execute(
                "SELECT id FROM time_entries WHERE end IS NULL AND task_id=? ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if not row:
                return None
            entry_id = row[0]
            conn.execute("UPDATE time_entries SET end=? WHERE id=?", (now_iso(), entry_id))
            _set_task_back_to_todo_if_idle(conn, task_id)
            return entry_id

# ---------- rounding & totals ----------

def _round_seconds_to_minutes(seconds: int) -> int:
    if seconds <= 0:
        return 0
    minutes = int((seconds + 30) // 60)
    return minutes if minutes > 0 else 1

def minutes_by_task(db_path: Path = DEFAULT_DB, *, rounding: str = "entry") -> Dict[int, int]:
    """
    Return {task_id: minutes} overall.
    rounding:
      - 'entry': sum of each entry's rounded minutes (matches per-entry breakdown)
      - 'overall': round once after summing seconds per task
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT task_id, start, end FROM time_entries"
        ).fetchall()

    if rounding == "overall":
        acc: Dict[int, int] = {}
        for task_id, start_s, end_s in rows:
            sec = _overlap_seconds(start_s, end_s, None, None)
            acc[task_id] = acc.get(task_id, 0) + sec
        return {tid: _round_seconds_to_minutes(sec) for tid, sec in acc.items()}

    # entry
    totals: Dict[int, int] = {}
    for task_id, start_s, end_s in rows:
        sec = _overlap_seconds(start_s, end_s, None, None)
        minutes = _round_seconds_to_minutes(sec) if sec > 0 else 0
        totals[task_id] = totals.get(task_id, 0) + minutes
    return totals

def minutes_by_task_window(
    win_start: Optional[datetime], win_end: Optional[datetime],
    db_path: Path = DEFAULT_DB, *, rounding: str = "entry"
) -> Dict[int, int]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT task_id, start, end FROM time_entries").fetchall()

    if rounding == "overall":
        acc: Dict[int, int] = {}
        for task_id, start_s, end_s in rows:
            sec = _overlap_seconds(start_s, end_s, win_start, win_end)
            acc[task_id] = acc.get(task_id, 0) + sec
        return {tid: _round_seconds_to_minutes(sec) for tid, sec in acc.items()}

    totals: Dict[int, int] = {}
    for task_id, start_s, end_s in rows:
        sec = _overlap_seconds(start_s, end_s, win_start, win_end)
        minutes = _round_seconds_to_minutes(sec) if sec > 0 else 0
        totals[task_id] = totals.get(task_id, 0) + minutes
    return totals

def entry_minutes_for_task(task_id: int, db_path: Path = DEFAULT_DB) -> List[tuple]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT note, start, end FROM time_entries WHERE task_id=? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
    out: List[tuple] = []
    for note, start_s, end_s in rows:
        sec = _overlap_seconds(start_s, end_s, None, None)
        mins = _round_seconds_to_minutes(sec) if sec > 0 else 0
        out.append((_clean_note(note) or "", mins))
    return out

def entry_minutes_for_task_window(task_id: int, win_start, win_end, db_path: Path = DEFAULT_DB) -> List[tuple]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT note, start, end FROM time_entries WHERE task_id=? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
    out: List[tuple] = []
    for note, start_s, end_s in rows:
        sec = _overlap_seconds(start_s, end_s, win_start, win_end)
        mins = _round_seconds_to_minutes(sec) if sec > 0 else 0
        if mins > 0:
            out.append((_clean_note(note) or "", mins))
    return out

# ---------- entry management ----------

def entries_with_durations(task_id: int, db_path: Path = DEFAULT_DB) -> List[tuple]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, start, end, note,
                   (strftime('%s', COALESCE(end, 'now')) - strftime('%s', start)) AS seconds
            FROM time_entries
            WHERE task_id=?
            ORDER BY id ASC
            """,
            (task_id,),
        ).fetchall()
    out: List[tuple] = []
    for eid, start_s, end_s, note, seconds in rows:
        sec = int(seconds or 0)
        mins = _round_seconds_to_minutes(sec) if sec > 0 else 0
        out.append((eid, start_s, end_s, _clean_note(note) or "", mins))
    return out

def add_manual_entry(
    task_id: int,
    db_path: Path = DEFAULT_DB,
    *,
    minutes: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    ago: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    note = _clean_note(note)
    if start is not None:
        start_dt = _parse_local_datetime(start)
        if end is not None and minutes is not None:
            raise ValueError("provide either --end or --minutes with --start, not both")
        if end is not None:
            end_dt = _parse_local_datetime(end)
        elif minutes is not None:
            if minutes <= 0:
                raise ValueError("minutes must be > 0")
            end_dt = start_dt + timedelta(minutes=minutes)
        else:
            raise ValueError("when using --start, specify either --end or --minutes")
    elif ago is not None:
        mins = _parse_duration_to_minutes(ago)
        now = _now_local()
        start_dt = now - timedelta(minutes=mins)
        end_dt = now
    elif minutes is not None:
        if minutes <= 0:
            raise ValueError("minutes must be > 0")
        now = _now_local()
        start_dt = now - timedelta(minutes=minutes)
        end_dt = now
    else:
        raise ValueError("specify one of: --minutes, --ago, or --start (+ --end | --minutes)")

    if end_dt <= start_dt:
        raise ValueError("end must be after start")

    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO time_entries(task_id, start, end, note) VALUES (?, ?, ?, ?)",
            (task_id, start_dt.isoformat(timespec="seconds"), end_dt.isoformat(timespec="seconds"), note),
        )
        return cur.lastrowid

def delete_entry(entry_id: int, db_path: Path = DEFAULT_DB) -> bool:
    with connect(db_path) as conn:
        row = conn.execute("SELECT task_id, end FROM time_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return False
        task_id, end_val = row
        conn.execute("DELETE FROM time_entries WHERE id=?", (entry_id,))
        if end_val is None:
            _set_task_back_to_todo_if_idle(conn, task_id)
        return True

def edit_entry(entry_id: int, db_path: Path = DEFAULT_DB, *, minutes: Optional[int] = None, note: Optional[str] = None) -> bool:
    with connect(db_path) as conn:
        row = conn.execute("SELECT task_id, start, end, note FROM time_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return False
        task_id, start_s, end_s, _ = row

        updates = []
        params: List[object] = []

        if note is not None:
            updates.append("note=?"); params.append(_clean_note(note))

        if minutes is not None:
            if minutes < 0:
                raise ValueError("minutes must be >= 0")
            if end_s is None:
                raise ValueError("cannot edit duration of a running entry; stop it first")
            start_dt = datetime.fromisoformat(start_s)
            new_end = start_dt + timedelta(minutes=minutes)
            updates.append("end=?"); params.append(new_end.astimezone().isoformat(timespec="seconds"))

        if not updates:
            return True

        params.append(entry_id)
        conn.execute(f"UPDATE time_entries SET {', '.join(updates)} WHERE id=?", tuple(params))
        _set_task_back_to_todo_if_idle(conn, task_id)
        return True

def reassign_entry(entry_id: int, new_task_id: int, db_path: Path = DEFAULT_DB) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute("UPDATE time_entries SET task_id=? WHERE id=?", (new_task_id, entry_id))
        return cur.rowcount > 0

def split_entry(entry_id: int, at_iso: str, db_path: Path = DEFAULT_DB) -> Tuple[int, int]:
    """Split a finished entry into two at 'at_iso'. Returns (left_id, right_id)."""
    at_dt = _parse_local_datetime(at_iso)
    with connect(db_path) as conn:
        row = conn.execute("SELECT task_id, start, end, note FROM time_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise ValueError("entry not found")
        task_id, start_s, end_s, note = row
        if end_s is None:
            raise ValueError("cannot split a running entry")
        start_dt = datetime.fromisoformat(start_s); end_dt = datetime.fromisoformat(end_s)
        if not (start_dt < at_dt < end_dt):
            raise ValueError("split point must be strictly inside the entry interval")
        note = _clean_note(note)
        # update left
        conn.execute("UPDATE time_entries SET end=? WHERE id=?", (at_dt.isoformat(timespec="seconds"), entry_id))
        # insert right
        cur = conn.execute(
            "INSERT INTO time_entries(task_id, start, end, note) VALUES (?, ?, ?, ?)",
            (task_id, at_dt.isoformat(timespec="seconds"), end_dt.isoformat(timespec="seconds"), note),
        )
        return entry_id, cur.lastrowid

def trim_entry(entry_id: int, new_start: Optional[str], new_end: Optional[str], db_path: Path = DEFAULT_DB) -> bool:
    """Trim edges of a finished entry. You can set one or both. Must keep start < end."""
    with connect(db_path) as conn:
        row = conn.execute("SELECT start, end FROM time_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return False
        start_s, end_s = row
        if end_s is None:
            raise ValueError("cannot trim a running entry")
        start_dt = datetime.fromisoformat(start_s)
        end_dt = datetime.fromisoformat(end_s)
        if new_start:
            start_dt = _parse_local_datetime(new_start)
        if new_end:
            end_dt = _parse_local_datetime(new_end)
        if not (start_dt < end_dt):
            raise ValueError("trim results in non-positive duration")
        conn.execute(
            "UPDATE time_entries SET start=?, end=? WHERE id=?",
            (start_dt.isoformat(timespec="seconds"), end_dt.isoformat(timespec="seconds"), entry_id),
        )
        return True

# ---------- duration parsing ----------

def _parse_duration_to_minutes(s: str) -> int:
    s = (s or '').strip().lower()
    # Accept ':30' style shorthand → 30 minutes
    if s.startswith(':') and s[1:].isdigit():
        val = int(s[1:])
        if val <= 0:
            raise ValueError('duration must be > 0 minutes')
        return val
    if s.isdigit():
        val = int(s)
        if val <= 0:
            raise ValueError('duration must be > 0 minutes')
        return val
    num = ''
    days = hours = mins = 0
    for ch in s:
        if ch.isdigit():
            num += ch
            continue
        if ch in ('d', 'h', 'm'):
            if not num:
                raise ValueError(f"missing number before {ch} in {s!r}")
            val = int(num); num = ''
            if ch == 'd': days += val
            elif ch == 'h': hours += val
            else: mins += val
        elif ch.isspace():
            continue
        else:
            raise ValueError(f"invalid char {ch!r} in duration {s!r}")
    if num:
        # Trailing number without unit → minutes
        mins += int(num)
    total = days*24*60 + hours*60 + mins
    if total <= 0:
        raise ValueError('duration must be > 0 minutes')
    return total

    s = s.strip().lower()
    if s.isdigit():
        val = int(s)
        if val <= 0:
            raise ValueError("duration must be > 0 minutes")
        return val
    num = ""
    days = hours = mins = 0
    for ch in s:
        if ch.isdigit():
            num += ch
            continue
        if ch in ("d", "h", "m"):
            if not num:
                raise ValueError(f"missing number before {ch} in {s!r}")
            val = int(num); num = ""
            if ch == "d": days += val
            elif ch == "h": hours += val
            else: mins += val
        elif ch.isspace():
            continue
        else:
            raise ValueError(f"invalid char {ch!r} in duration {s!r}")
    if num:
        mins += int(num)
    total = days * 24 * 60 + hours * 60 + mins
    if total <= 0:
        raise ValueError("duration must be > 0 minutes")
    return total
