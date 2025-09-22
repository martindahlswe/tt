from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, Union, Iterable, List, Tuple
from .timeparse import _parse_ago
from pathlib import Path

from .db import connect, now_iso, DEFAULT_DB
from . import timeparse as tparse
from . import config as cfgmod

# ---------------- time helpers ----------------

def _now_local() -> datetime:
    return datetime.now().astimezone()

def _to_dt_local(x: Optional[Union[str, datetime]]) -> Optional[datetime]:
    """Normalize strings or datetimes to tz-aware local datetimes."""
    if x is None:
        return None
    if isinstance(x, datetime):
        dt = x
    else:
        s = str(x).strip()
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_now_local().tzinfo)
    return dt.astimezone()

def _parse_local_datetime(s: str) -> datetime:
    """Delegate to central parser (honors strict/flexible config)."""
    return tparse.parse_dt(s)

# ---------------- durations & rounding ----------------

def _parse_duration_to_minutes(s: str) -> int:
    s = (s or '').strip().lower()
    # Accept ':30' → 30
    if s.startswith(':') and s[1:].isdigit():
        val = int(s[1:])
        if val <= 0:
            raise ValueError('duration must be > 0 minutes')
        return val
    # Pure number → minutes
    if s.isdigit():
        val = int(s)
        if val <= 0:
            raise ValueError('duration must be > 0 minutes')
        return val
    # h/m combos, e.g. 1h, 1h15, 2h5m, 45m
    num = ''
    days = hours = mins = 0
    for ch in s:
        if ch.isdigit():
            num += ch
            continue
        if ch in 'dhm':
            if not num:
                raise ValueError('missing number before unit')
            val = int(num)
            num = ''
            if ch == 'd':
                days += val
            elif ch == 'h':
                hours += val
            elif ch == 'm':
                mins += valal
        else:
            raise ValueError(f'bad char in duration: {ch!r}')
    if num:
        # trailing number without unit → minutes
        mins += int(num)
    total = days*24*60 + hours*60 + mins
    if total <= 0:
        raise ValueError('duration must be > 0 minutes')
    return total

def _round_seconds_to_minutes(sec: int) -> int:
    """Round seconds to minutes based on config rounding policy.
    For now, standard rounding to nearest minute. You can extend with
    per-entry or overall rounding minutes in config if desired.
    """
    # Future: cfg = cfgmod.load(); check for rounding granularity, etc.
    if sec <= 0:
        return 0
    return int(round(sec / 60.0))

# ---------------- overlap math ----------------

def _overlap_seconds(
    start_s: str,
    end_s: Optional[str],
    win_start: Optional[Union[str, datetime]],
    win_end: Optional[Union[str, datetime]],
) -> int:
    """Seconds of overlap between [start,end] and [win_start,win_end].
    Accepts ISO strings or datetimes for the window; normalizes to tz-aware.
    """
    start = _to_dt_local(start_s)
    end = _to_dt_local(end_s) or _now_local()
    ws = _to_dt_local(win_start)
    we = _to_dt_local(win_end)

    a = start if not ws else max(start, ws)
    b = end if not we else min(end, we)
    if b <= a:
        return 0
    return int((b - a).total_seconds())

# ---------------- queries ----------------

def entries_with_durations(task_id: int, db_path=DEFAULT_DB) -> List[Tuple[int, str, Optional[str], Optional[str], int]]:
    """Return (entry_id, start_iso, end_iso, note, minutes) for a task.
    Minutes are rounded using _round_seconds_to_minutes.
    """
    rows: List[Tuple[int, str, Optional[str], Optional[str], int]] = []
    with connect(db_path) as conn:
        cur = conn.execute(
            """SELECT id, start, end, note FROM time_entries
                   WHERE task_id = ?
                   ORDER BY start ASC""",
            (task_id,),
        )
        for eid, start_s, end_s, note in cur.fetchall():
            sec = _overlap_seconds(start_s, end_s, None, None)
            mins = _round_seconds_to_minutes(sec)
            rows.append((eid, start_s, end_s, note, mins))
    return rows


def entry_minutes_for_task(task_id: int, db_path=DEFAULT_DB) -> List[Tuple[str, int]]:
    """Return list of (note, minutes) tuples for a task, without a time window."""
    rows: List[Tuple[str, int]] = []
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT start, end, note FROM time_entries WHERE task_id = ? ORDER BY start ASC",
            (task_id,),
        )
        for start_s, end_s, note in cur.fetchall():
            sec = _overlap_seconds(start_s, end_s, None, None)
            m = _round_seconds_to_minutes(sec) if sec > 0 else 0
            rows.append(((note or ""), m))
    return rows

def minutes_by_task(
    db_path=DEFAULT_DB,
    rounding: str | None = None,
    win_start: Optional[Union[str, datetime]] = None,
    win_end: Optional[Union[str, datetime]] = None,
    task_ids: Optional[Iterable[int]] = None,
) -> dict[int, int]:
    """Return {task_id: minutes} totals.
    - rounding: 'entry' (default) rounds per entry; 'overall' rounds after summing seconds.
    - win_start/win_end: optional window bounds (str or datetime).
    - task_ids: optional whitelist of task ids.
    """
    rounding = (rounding or 'entry').lower()
    ws = _to_dt_local(win_start)
    we = _to_dt_local(win_end)

    totals_sec: dict[int, int] = {}
    with connect(db_path) as conn:
        if task_ids:
            # parameterize the IN clause safely
            qs = ",".join("?" for _ in task_ids)
            params = tuple(task_ids)
            cur = conn.execute(
                f"""SELECT task_id, start, end FROM time_entries
                       WHERE task_id IN ({qs})""", params
            )
        else:
            cur = conn.execute("SELECT task_id, start, end FROM time_entries")

        for tid, start_s, end_s in cur.fetchall():
            if ws or we:
                sec = _overlap_seconds(start_s, end_s, ws, we)
            else:
                sec = _overlap_seconds(start_s, end_s, None, None)
            if sec <= 0:
                continue
            totals_sec[tid] = totals_sec.get(tid, 0) + sec

    if rounding == 'overall':
        # Round after summing seconds per task
        return {tid: _round_seconds_to_minutes(sec) for tid, sec in totals_sec.items()}
    # Default: per-entry rounding approximation -> we already summed raw seconds; to approximate
    # per-entry rounding correctly we'd need per-entry minutes. Do a second pass when window is not set.
    if ws is None and we is None:
        # more accurate per-entry rounding without a window
        totals_min: dict[int, int] = {}
        with connect(db_path) as conn:
            cur = conn.execute("SELECT task_id, start, end FROM time_entries")
            for tid, start_s, end_s in cur.fetchall():
                sec = _overlap_seconds(start_s, end_s, None, None)
                m = _round_seconds_to_minutes(sec) if sec > 0 else 0
                if m > 0:
                    totals_min[tid] = totals_min.get(tid, 0) + m
        # merge any tasks that only appeared in totals_sec due to window filtering earlier
        for tid in totals_sec.keys():
            totals_min.setdefault(tid, 0)
        return totals_min

    # With a window set and 'entry' rounding requested, round the windowed seconds
    return {tid: _round_seconds_to_minutes(sec) for tid, sec in totals_sec.items()}


# ---------------- mutations ----------------

def delete_entry(entry_id: int, db_path=DEFAULT_DB) -> int:
    """Delete a single time entry by id. Returns number of rows deleted (0/1)."""
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
        conn.commit()
        return cur.rowcount

def delete_entries(entry_ids, db_path=DEFAULT_DB) -> int:
    """Bulk delete. Returns number of rows deleted."""
    entry_ids = list(entry_ids or [])
    if not entry_ids:
        return 0
    qmarks = ",".join("?" for _ in entry_ids)
    with connect(db_path) as conn:
        cur = conn.execute(f"DELETE FROM time_entries WHERE id IN ({qmarks})", tuple(entry_ids))
        conn.commit()
        return cur.rowcount

def adjust_entry_minutes(entry_id: int, delta_minutes: int, db_path=DEFAULT_DB) -> bool:
    """Adjust an entry's end time by +/- delta_minutes.
    Returns True if updated, False if no-op or not found.
    """
    if not delta_minutes:
        return False
    with connect(db_path) as conn:
        row = conn.execute("SELECT start, end FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return False
        start_s, end_s = row
        if not end_s:
            # Can't adjust a running entry safely; skip
            return False
        start_dt = _to_dt_local(start_s)
        end_dt = _to_dt_local(end_s)
        new_end = end_dt + timedelta(minutes=delta_minutes)
        # Prevent inverted ranges
        if new_end <= start_dt:
            return False
        conn.execute("UPDATE time_entries SET end = ? WHERE id = ?", (new_end.isoformat(), entry_id))
        conn.commit()
        return True


    if start is not None:
        fields.append("start = ?")
        values.append(start)
    if end is not None:
        fields.append("end = ?")
        values.append(end)
    if note is not None:
        fields.append("note = ?")
        values.append(note)

    if not fields:
        return

    values.append(entry_id)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE time_entries SET {', '.join(fields)} WHERE id = ?", values)


    if minutes is not None:
        with connect(db_path) as conn:
            row = conn.execute("SELECT start FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
            if not row:
                raise ValueError(f"Time entry {entry_id} not found")
            start_dt = datetime.fromisoformat(row[0])
            end_dt = start_dt + timedelta(minutes=minutes)
            end = end_dt.isoformat()

    if start is not None:
        fields.append("start = ?")
        values.append(start)
    if end is not None:
        fields.append("end = ?")
        values.append(end)
    if note is not None:
        fields.append("note = ?")
        values.append(note)

    if not fields:
        return

    values.append(entry_id)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE time_entries SET {', '.join(fields)} WHERE id = ?", values)

def edit_entry(entry_id: int, *args, start: Optional[str] = None, end: Optional[str] = None, note: Optional[str] = None, minutes: Optional[int] = None, db_path: Path = DEFAULT_DB) -> None:
    """
    Edit fields of a time entry by ID.

    Usage:
        edit_entry(123, note="New Note")
        edit_entry(123, minutes=30)
    """
    if args:
        raise TypeError("edit_entry() accepts only one positional argument (entry_id). Use keyword arguments for others.")

    fields = []
    values = []

    if minutes is not None:
        with connect(db_path) as conn:
            row = conn.execute("SELECT start FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
            if not row:
                raise ValueError(f"Time entry {entry_id} not found")
            start_dt = datetime.fromisoformat(row[0])
            end_dt = start_dt + timedelta(minutes=minutes)
            end = end_dt.isoformat()

    if start is not None:
        fields.append("start = ?")
        values.append(start)
    if end is not None:
        fields.append("end = ?")
        values.append(end)
    if note is not None:
        fields.append("note = ?")
        values.append(note)

    if not fields:
        return

    values.append(entry_id)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE time_entries SET {', '.join(fields)} WHERE id = ?", values)

def entry_minutes_for_task_window(task_id: int, win_start, win_end, db_path=DEFAULT_DB) -> List[Tuple[str, int]]:
    """Return list of (note, minutes) for a task within an optional window."""
    rows: List[Tuple[str, int]] = []
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT start, end, note FROM time_entries WHERE task_id = ? ORDER BY start ASC",
            (task_id,),
        )
        for start_s, end_s, note in cur.fetchall():
            sec = _overlap_seconds(start_s, end_s, win_start, win_end)
            if sec <= 0:
                continue
            rows.append(((note or ""), _round_seconds_to_minutes(sec)))
    return rows

def minutes_by_task_window(win_start, win_end, db_path=DEFAULT_DB, *, rounding: str | None = None) -> dict[int, int]:
    """Wrapper to minutes_by_task filtered by a window."""
    return minutes_by_task(db_path=db_path, rounding=rounding, win_start=win_start, win_end=win_end)

def current_running(db_path: Path) -> Optional[Tuple[int, int]]:
    """Return (entry_id, task_id) of currently running entry, or None."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, task_id FROM time_entries WHERE end IS NULL ORDER BY start DESC LIMIT 1"
        ).fetchone()
    return row if row else None

def start(task_id: int, db_path: Path, *, note: Optional[str] = None) -> int:
    """Stop any running entry, then start a new one for task_id. Returns new entry id.
    Raises ValueError if task does not exist."""
    with connect(db_path) as conn:
        t = conn.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not t:
            raise ValueError(f"task {task_id} not found")
        # stop any running
        conn.execute("UPDATE time_entries SET end=? WHERE end IS NULL", (now_iso(),))
        cur = conn.execute(
            "INSERT INTO time_entries(task_id, start, note) VALUES (?, ?, ?)",
            (task_id, now_iso(), note),
        )
        return cur.lastrowid

def stop(task_id: Optional[int] = None, db_path: Path = DEFAULT_DB) -> Optional[int]:
    """Stop the running entry (optionally for a specific task). Returns entry id or None."""
    with connect(db_path) as conn:
        if task_id is None:
            row = conn.execute("SELECT id FROM time_entries WHERE end IS NULL ORDER BY start DESC LIMIT 1").fetchone()
        else:
            row = conn.execute("SELECT id FROM time_entries WHERE end IS NULL AND task_id=? ORDER BY start DESC LIMIT 1", (task_id,)).fetchone()
        if not row:
            return None
        eid = int(row[0])
        conn.execute("UPDATE time_entries SET end=? WHERE id=?", (now_iso(), eid))
        return eid

def add_manual_entry(task_id: int, db_path: Path, *, minutes=None, start=None, end=None, ago=None, note=None) -> int:
    """Add a manual time entry. Requires one of: minutes, ago, or start+end.
    Raises ValueError on invalid inputs or if task is missing."""
    with connect(db_path) as conn:
        t = conn.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not t:
            raise ValueError(f"task {task_id} not found")
    now = datetime.now().astimezone()
    if ago:
        seconds = _parse_ago(str(ago))
        s_dt = now - timedelta(seconds=seconds)
        e_dt = now
    elif minutes is not None:
        try:
            m = int(minutes)
        except Exception:
            raise ValueError("minutes must be an integer")
        if m <= 0:
            raise ValueError("minutes must be > 0")
        s_dt = now - timedelta(minutes=m)
        e_dt = now
    elif start and end:
        s_dt = _to_dt_local(start)
        e_dt = _to_dt_local(end)
        if e_dt is not None and s_dt is not None and e_dt <= s_dt:
            raise ValueError("end must be after start")
    else:
        raise ValueError("provide one of: --minutes, --ago, or both --start and --end")
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO time_entries(task_id, start, end, note) VALUES (?, ?, ?, ?)",
            (task_id, s_dt.isoformat(), e_dt.isoformat(), note),
        )
        return cur.lastrowid

def split_entry(entry_id: int, at: str, db_path: Path) -> tuple[int, int]:
    """Split an entry at the given ISO/local time, returning (left_id, right_id)."""
    at_dt = _to_dt_local(at)
    with connect(db_path) as conn:
        row = conn.execute("SELECT task_id, start, end, note FROM time_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise ValueError(f"entry {entry_id} not found")
        task_id, s, e, note = row
        s_dt = _to_dt_local(s); e_dt = _to_dt_local(e)
        if e_dt is None:
            raise ValueError("cannot split a running entry")
        if not (s_dt < at_dt < e_dt):
            raise ValueError("split time must be between start and end")
        conn.execute("DELETE FROM time_entries WHERE id=?", (entry_id,))
        cur1 = conn.execute(
            "INSERT INTO time_entries(task_id, start, end, note) VALUES (?, ?, ?, ?)",
            (task_id, s_dt.isoformat(), at_dt.isoformat(), note),
        )
        cur2 = conn.execute(
            "INSERT INTO time_entries(task_id, start, end, note) VALUES (?, ?, ?, ?)",
            (task_id, at_dt.isoformat(), e_dt.isoformat(), note),
        )
        return cur1.lastrowid, cur2.lastrowid

def trim_entry(entry_id: int, start: Optional[str], end: Optional[str], db_path: Path) -> bool:
    """Trim entry start/end. Returns True if updated. Raises on invalid ranges."""
    if not (start or end):
        raise ValueError("provide --start and/or --end")
    with connect(db_path) as conn:
        row = conn.execute("SELECT start, end FROM time_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return False
        s, e = row
        s_dt = _to_dt_local(start) if start else _to_dt_local(s)
        e_dt = _to_dt_local(end) if end else _to_dt_local(e)
        if e_dt is not None and s_dt is not None and e_dt <= s_dt:
            raise ValueError("end must be after start")
        conn.execute("UPDATE time_entries SET start=?, end=? WHERE id=?", (s_dt.isoformat(), e_dt.isoformat() if e_dt else None, entry_id))
        return True

def reassign_entry(entry_id: int, new_task_id: int, db_path: Path) -> bool:
    """Move entry to another task. Returns True if updated; raises if new task missing."""
    with connect(db_path) as conn:
        t = conn.execute("SELECT id FROM tasks WHERE id=?", (new_task_id,)).fetchone()
        if not t:
            raise ValueError(f"task {new_task_id} not found")
        cur = conn.execute("UPDATE time_entries SET task_id=? WHERE id=?", (new_task_id, entry_id))
        return cur.rowcount > 0
