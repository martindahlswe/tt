# tt/db.py
from pathlib import Path
import sqlite3
from datetime import datetime

DEFAULT_DB = Path.home() / ".tt.sqlite3"

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
  billable         INTEGER NOT NULL DEFAULT 0
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
    """Bare connection with FK enforcement + WAL and helpful indexes."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time_task ON time_entries(task_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time_start ON time_entries(start);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
    except Exception:
        pass
    return conn

def init(db_path: Path = DEFAULT_DB) -> Path:
    """Create schema if missing, then run idempotent migrations."""
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA)
        _migrate(conn)
    return db_path

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None

def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    if not _table_exists(conn, table):
        return False
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return col in cols

def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent, safe migrations for older DBs."""
    # Ensure columns
    for col, ddl in [
        ("archived_at",  "ALTER TABLE tasks ADD COLUMN archived_at TEXT"),
        ("priority",     "ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"),
        ("due_date",     "ALTER TABLE tasks ADD COLUMN due_date TEXT"),
        ("estimate_minutes", "ALTER TABLE tasks ADD COLUMN estimate_minutes INTEGER NOT NULL DEFAULT 0"),
        ("billable",     "ALTER TABLE tasks ADD COLUMN billable INTEGER NOT NULL DEFAULT 0"),
    ]:
        if not _has_col(conn, "tasks", col):
            conn.execute(ddl)

    # Ensure note column on time_entries
    if not _has_col(conn, "time_entries", "note"):
        conn.execute("ALTER TABLE time_entries ADD COLUMN note TEXT")

    # Ensure tags tables
    if not _table_exists(conn, "tags"):
        conn.execute("CREATE TABLE tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    if not _table_exists(conn, "task_tags"):
        conn.execute("""CREATE TABLE task_tags(
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            UNIQUE(task_id, tag_id)
        )""")
