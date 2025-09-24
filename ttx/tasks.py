# tt/tasks.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Tuple

from .db import connect, now_iso, DEFAULT_DB

# -------- basics --------
def add(title: str, db_path: Path = DEFAULT_DB, parent_id: Optional[int] = None) -> int:
    """Create a new task with title; returns new task id."""
    if not (title or '').strip():
        raise ValueError("title cannot be empty")
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO tasks(title, status, created_at, parent_id) VALUES (?, 'todo', ?, ?)",
            (title, now_iso(), parent_id),
        )
        return int(cur.lastrowid)

def get(task_id: int, db_path: Path = DEFAULT_DB):
    """Return full task row or None."""
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT id, title, status, created_at, completed_at, archived_at, priority, due_date, estimate_minutes, billable "
            "FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()

def get_title(task_id: int, db_path: Path = DEFAULT_DB) -> Optional[str]:
    row = get(task_id, db_path)
    return row[1] if row else None

def list_tasks(
    status: Optional[str] = None,
    db_path: Path = DEFAULT_DB,
    *,
    include_archived: bool = False,
    tags: Optional[List[str]] = None,
    limit: Optional[int] = None,
):
    """Return tasks. If tags specified, tasks must have ALL listed tags (AND)."""
    tags = tags or []
    q = [
        """SELECT t.id, t.title, t.status, t.created_at, t.completed_at, t.archived_at,
                   t.priority, t.due_date, t.estimate_minutes, t.billable
               FROM tasks t"""
    ]
    params: List[object] = []
    # join once per tag to enforce AND condition
    for i, tag in enumerate(tags):
        q.append(f"""
            JOIN task_tags tt{i} ON tt{i}.task_id = t.id
            JOIN tags tg{i} ON tg{i}.id = tt{i}.tag_id AND tg{i}.name = ?
        """)
        params.append(tag)
    q.append("WHERE 1=1")
    if status:
        q.append("AND t.status = ?"); params.append(status)
    if not include_archived:
        q.append("AND t.archived_at IS NULL")
    q.append("ORDER BY t.id DESC")
    if limit:
        q.append(f"LIMIT {int(limit)}")
    sql = "\n".join(q)
    with connect(db_path) as conn:
        return conn.execute(sql, tuple(params)).fetchall()

def mark_done(task_id: int, db_path: Path = DEFAULT_DB):
    """Set status=done and completed_at=now for task."""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE tasks SET status='done', completed_at=? WHERE id=?",
            (now_iso(), task_id),
        )

def edit_title(task_id: int, new_title: str, db_path: Path = DEFAULT_DB) -> bool:
    """Edit title; returns True if a row was updated."""
    if new_title is None:
        return True
    with connect(db_path) as conn:
        cur = conn.execute("UPDATE tasks SET title=? WHERE id=?", (new_title, task_id))
        return cur.rowcount > 0

def edit_fields(
    task_id: int,
    db_path: Path = DEFAULT_DB,
    *,
    priority: Optional[int] = None,
    due_date: Optional[str] = None,
    estimate_minutes: Optional[int] = None,
    billable: Optional[bool] = None,
) -> bool:
    """Edit priority/due_date/estimate_minutes/billable; returns True if updated or no-op."""
    sets: List[str] = []
    params: List[object] = []
    if priority is not None:
        sets.append("priority=?"); params.append(int(priority))
    if due_date is not None:
        sets.append("due_date=?"); params.append(due_date)
    if estimate_minutes is not None:
        sets.append("estimate_minutes=?"); params.append(int(estimate_minutes))
    if billable is not None:
        sets.append("billable=?"); params.append(1 if billable else 0)
    if not sets:
        return True
    params.append(task_id)
    with connect(db_path) as conn:
        cur = conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", tuple(params))
        return cur.rowcount > 0

def archive(task_id: int, db_path: Path = DEFAULT_DB) -> bool:
    """Set archived_at=now; returns True if a row was updated."""
    with connect(db_path) as conn:
        cur = conn.execute("UPDATE tasks SET archived_at=? WHERE id=?", (now_iso(), task_id))
        return cur.rowcount > 0

def unarchive(task_id: int, db_path: Path = DEFAULT_DB) -> bool:
    """Set archived_at=NULL; returns True if a row was updated."""
    with connect(db_path) as conn:
        cur = conn.execute("UPDATE tasks SET archived_at=NULL WHERE id=?", (task_id,))
        return cur.rowcount > 0

def delete_task(task_id: int, db_path: Path = DEFAULT_DB, *, force: bool = False) -> bool:
    """Delete task. If it has time entries, requires force=True. Returns True if deleted, False if not found."""
    with connect(db_path) as conn:
        row = conn.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return False
        cnt = conn.execute("SELECT COUNT(*) FROM time_entries WHERE task_id=?", (task_id,)).fetchone()[0]
        if cnt > 0 and not force:
            raise ValueError(f"task {task_id} has {cnt} time entries; use --force to delete")
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        return True

def merge_tasks(src_task_id: int, dst_task_id: int, db_path: Path = DEFAULT_DB) -> bool:
    """Move logs and tags from src → dst and delete src. Returns True if src was deleted."""
    if src_task_id == dst_task_id:
        return True
    with connect(db_path) as conn:
        # ensure dst exists
        dst = conn.execute("SELECT id FROM tasks WHERE id=?", (dst_task_id,)).fetchone()
        if not dst:
            return False
        # reassign entries
        conn.execute("UPDATE time_entries SET task_id=? WHERE task_id=?", (dst_task_id, src_task_id))
        # merge tags
        conn.execute(
            "INSERT OR IGNORE INTO task_tags(task_id, tag_id) "
            "SELECT ?, tag_id FROM task_tags WHERE task_id=?",
            (dst_task_id, src_task_id),
        )
        # delete src task
        cur = conn.execute("DELETE FROM tasks WHERE id=?", (src_task_id,))
        return cur.rowcount > 0

# -------- tags --------

def _ensure_tag_id(name: str, db_path: Path = DEFAULT_DB) -> int:
    name = (name or '').strip()
    if not name:
        raise ValueError("tag name cannot be empty")
    with connect(db_path) as conn:
        row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        if row:
            return int(row[0])
        cur = conn.execute("INSERT INTO tags(name) VALUES (?)", (name,))
        return int(cur.lastrowid)

def add_tag(task_id: int, name: str, db_path: Path = DEFAULT_DB) -> None:
    tag_id = _ensure_tag_id(name, db_path)
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO task_tags(task_id, tag_id) VALUES (?, ?)", (task_id, tag_id))

def remove_tag(task_id: int, name: str, db_path: Path = DEFAULT_DB) -> None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        if not row:
            return
        tag_id = int(row[0])
        conn.execute("DELETE FROM task_tags WHERE task_id=? AND tag_id=?", (task_id, tag_id))

def list_tags(task_id: int, db_path: Path = DEFAULT_DB) -> List[str]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT tg.name
                   FROM tags tg
                   JOIN task_tags ttx ON ttx.tag_id = tg.id
                  WHERE ttx.task_id = ?
               ORDER BY tg.name""",
            (task_id,),
        ).fetchall()
        return [r[0] for r in rows]

def list_subtasks(parent_id: int, db_path: Path = DEFAULT_DB) -> List[tuple]:
    """Return all direct sub-tasks of a given task."""
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT id, title, status, created_at, completed_at, archived_at, priority, due_date, estimate_minutes, billable, parent_id FROM tasks WHERE parent_id = ? ORDER BY created_at",
            (parent_id,),
        ).fetchall()


def get_children(parent_id: int, db_path: Path = DEFAULT_DB):
    """Return all non-archived sub-tasks for a given parent task."""
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT id, title, status, created_at, completed_at, priority, due_date "
            "FROM tasks WHERE parent_id=? AND archived_at IS NULL ORDER BY id",
            (parent_id,)
        ).fetchall()
