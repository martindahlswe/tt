# tt/db.py
from __future__ import annotations
from pathlib import Path
import sqlite3
from datetime import datetime

DEFAULT_DB: Path = Path.home() / ".tt.sqlite3"

# Base schema (idempotent). Migrations below may extend it.
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tasks(
  id               INTEGER PRIMARY KEY,
  title            TEXT NOT NULL,
  status           TEXT NOT NULL CHECK(status IN ('todo','doing','done')) DEFAULT 'todo',
  created_at       TEXT NOT NULL,
  completed_at     TEXT,
  archived_at      TEXT,
  priority         INTEGER NOT NULL DEFAULT 0,
  due_date         TEXT,
  estimate_minutes INTEGER NOT NULL DEFAULT 0,
  billable         INTEGER NOT NULL DEFAULT 0,
  parent_id        INTEGER REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS time_entries(
  id       INTEGER PRIMARY KEY,
  task_id  INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  start    TEXT NOT NULL,
  end      TEXT,
  note     TEXT
);

CREATE TABLE IF NOT EXISTS tags(
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS task_tags(
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  UNIQUE(task_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_time_task ON time_entries(task_id);
CREATE INDEX IF NOT EXISTS idx_time_start ON time_entries(start);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    """Return a SQLite connection with FK enforcement and sensible pragmas.
    The caller is responsible for closing/using context manager.
    """
    db_path = Path(db_path)
    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA)
        apply_migrations(conn)
    except sqlite3.Error as e:
        # propagate with clearer context
        raise sqlite3.OperationalError(f"Could not open database at '{db_path}': {e}") from e

    # Best-effort pragmas (ignore if not supported)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    # Helpful indexes may not exist yet (no-op if tables missing)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time_task ON time_entries(task_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time_start ON time_entries(start);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
    except Exception:
        pass
    return conn


def init(db_path: Path = DEFAULT_DB) -> Path:
    """Initialize the database file if missing and run idempotent migrations.
    Returns the path actually used.
    """
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA)
        apply_migrations(conn)
        _migrate(conn)
        conn.commit()
    return db_path


def now_iso() -> str:
    """Current local time as ISO8601 with seconds and timezone."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------- migrations & helpers ---------------

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        return col in cols
    except sqlite3.Error:
        return False


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent migrations to keep older DBs compatible.
    This should be safe to run many times.
    """
    # Ensure tasks columns
    for col, ddl in [
        ("archived_at",      "ALTER TABLE tasks ADD COLUMN archived_at TEXT"),
        ("priority",         "ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"),
        ("due_date",         "ALTER TABLE tasks ADD COLUMN due_date TEXT"),
        ("estimate_minutes", "ALTER TABLE tasks ADD COLUMN estimate_minutes INTEGER NOT NULL DEFAULT 0"),
        ("billable",         "ALTER TABLE tasks ADD COLUMN billable INTEGER NOT NULL DEFAULT 0"),
    ]:
        if _table_exists(conn, "tasks") and not _has_col(conn, "tasks", col):
            conn.execute(ddl)

    # Ensure note column on time_entries
    if _table_exists(conn, "time_entries") and not _has_col(conn, "time_entries", "note"):
        conn.execute("ALTER TABLE time_entries ADD COLUMN note TEXT")

    # Ensure tags tables
    if not _table_exists(conn, "tags"):
        conn.execute("CREATE TABLE tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    if not _table_exists(conn, "task_tags"):
        conn.execute(
            """CREATE TABLE task_tags(
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                UNIQUE(task_id, tag_id)
            )"""
        )

    # Ensure helpful indexes
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time_task ON time_entries(task_id);")
    except sqlite3.Error:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time_start ON time_entries(start);")
    except sqlite3.Error:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
    except sqlite3.Error:
        pass

def apply_migrations(conn: sqlite3.Connection):
    """
    Apply post-schema migrations safely (idempotent).
    - Add parent_id to tasks if not already present.
    """
    cursor = conn.execute("PRAGMA table_info(tasks);")
    columns = [row[1] for row in cursor.fetchall()]
    if "parent_id" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN parent_id INTEGER REFERENCES tasks(id);")


from pathlib import Path
import os

def get_db_path() -> Path:
    """
    Returns the path to the default SQLite database.
    """
    return Path(os.getenv("TTX_DB_PATH", Path.home() / ".tt.sqlite3"))
