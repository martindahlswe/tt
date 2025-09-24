from __future__ import annotations
import json
import typing
import os
import platform
import subprocess
from datetime import datetime, timedelta
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import typer
from rich.console import Console
from rich.table import Table
from rich import box

from . import db as dbmod
from . import config as cfgmod
from . import timeparse as tparse
from . import tasks
from . import time_entries as logs
from .tui import run_tui
import yaml
import sqlite3
import functools

console = Console()
# Show help when no args; disable shell-completion noise
app = typer.Typer(add_completion=False, no_args_is_help=True)
app.info.help = "Tiny tasks + time tracker (CLI + TUI). Run `ttx init` once; see `ttx examples` for working commands."

def _version_callback(value: bool):
    if value:
        try:
            from importlib.metadata import version, PackageNotFoundError  # type: ignore
            v = version("ttx")
        except Exception:
            v = "0.0.0+local"
        typer.echo(f"ttx {v}")
        raise typer.Exit()

@app.callback()
def _main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
):
    """Top-level command options. Run with no args to see help."""
    if getattr(ctx, "obj", None) is None:
        class _Obj: ...
        ctx.obj = _Obj()

# Enhanced help text



@app.command("examples")
def show_examples():
    """Show common usage examples."""
    from rich.console import Console
    from rich.panel import Panel

    examples_text = """[bold cyan]Examples:[/bold cyan]

• First-time setup:
  [green]ttx init[/green]

• Create a task and list tasks (note the ID in the first column):
  [green]ttx task add "Finances"[/green]
  [green]ttx task ls[/green]

• Start/stop timing (replace 1 with the ID you saw in 'task ls'):
  [green]ttx start 1[/green]
  [green]ttx stop[/green]

• Add a manual log (positional TASK_ID, not --task):
  [green]ttx log add 1 --start "2025-09-20 09:00" --end "2025-09-20 10:15"[/green]
  [green]ttx log add 1 --minutes 30[/green]
  [green]ttx log add 1 --ago 90m[/green]

• Show logs:
  [green]ttx log ls 1 --week[/green]        # for one task, this week
  [green]ttx log ls --all --week[/green]    # across all tasks

• Summaries:
  [green]ttx report --group day --since week[/green]

• Config helpers:
  [green]ttx config validate[/green]
  [green]ttx config path[/green]

• Launch the TUI:
  [green]ttx tui[/green]
"""
    Console().print(Panel(examples_text, title="ttx Examples", expand=False))

config_app = typer.Typer(help="Config utilities")

@config_app.command("validate")
def config_validate_cmd():
    """Validate config keys and show merged defaults."""
    cfg = cfgmod.load()
    allowed = {"db", "rounding", "default_status", "list"}
    list_allowed = {"compact", "limit"}
    unknown = [k for k in cfg.keys() if k not in allowed]
    list_unknown = [k for k in (cfg.get("list") or {}).keys() if k not in list_allowed]
    if unknown or list_unknown:
        console.print("[yellow]Unknown keys:[/yellow] " + ", ".join(unknown + [f"list.{k}" for k in list_unknown]))
    console.print_json(data=cfg)

@config_app.command("path")
def config_path_cmd():
    """Print resolved XDG config path."""
    print(cfgmod.xdg_config_path())

@config_app.command("edit")
def config_edit_cmd():
    """Open config in $EDITOR (or default editor on macOS). Creates file if missing."""
    path = cfgmod.xdg_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        cfgmod.write_yaml_config(path, cfgmod.load())
    editor = (os.environ.get("EDITOR") or "").strip()
    if platform.system() == "Darwin" and not editor:
        # open in default text editor (TextEdit) via 'open -t'
        subprocess.run(["open", "-t", str(path)])
    elif editor:
        subprocess.run([editor, str(path)])
    else:
        # fall back to vi
        subprocess.run(["vi", str(path)])


# ---------- global context & config ----------

class Ctx:
    db_path: Path
    rounding: str
    list_compact: bool
    list_limit: Optional[int]

def _load_ctx(db_opt: Optional[Path]) -> Ctx:
    cfg = cfgmod.load()
    rounding = (cfg.get("rounding") or "entry").lower()
    if rounding not in ("entry", "overall"):
        rounding = "entry"
    db_path = Path(cfg.get("db") or dbmod.DEFAULT_DB)
    if db_opt:
        db_path = Path(db_opt)
    ctx = Ctx()
    ctx.db_path = db_path
    ctx.rounding = rounding
    lst = cfg.get("list", {}) or {}
    ctx.list_compact = bool(lst.get("compact", False))
    ctx.list_limit = lst.get("limit")
    return ctx

@app.callback(invoke_without_command=True)

def main(
    ctx: typer.Context,
    db: Path = typer.Option(None, "--db", help="DB path (from config or ~/.tt.sqlite3)"),
):
    """Initialize context + config; print help when no subcommand."""
    c = _load_ctx(db)
    ctx.obj = c
    # no_args_is_help handles plain “no args” help

# ---------- helpers ----------

def _fail(msg: str, code: int = 2) -> None:
    """Print a user-friendly error and exit with code (default 2)."""
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(code)


def _guard_db_errors(fn):
    """Decorator mapping common exceptions to friendly errors without traces."""
    @functools.wraps(fn)
    def _wrap(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except sqlite3.IntegrityError as e:
            _fail(f"Database constraint error: {e}", code=1)
        except ValueError as e:
            _fail(str(e), code=2)
    return _wrap


def fmt_minutes(m: int) -> str:
    if m <= 0:
        return "0m"
    h, rem = divmod(m, 60)
    return f"{h}h {rem:02d}m" if h else f"{rem}m"

def _print_tasks_table(
    rows,
    totals_map: Dict[int, int],
    show_tags: bool,
    db_path: Path,
    entries_map: Dict[int, List[Tuple[str, int]]] | None = None,
):
    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("ID", justify="right")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Pri", justify="right")
    table.add_column("Due")
    table.add_column("Est", justify="right")
    table.add_column("Bill")
    table.add_column("Total")

    for r in rows:
        tid, title, st, created, completed, archived_at, prio, due, est, billable = r
        total_m = totals_map.get(tid, 0)
        bill = "✓" if billable else "•"
        # main task row
        table.add_row(
            str(tid),
            title,
            st,
            str(prio or 0),
            due or "",
            f"{est or 0}m" if est else "",
            bill,
            fmt_minutes(total_m),
        )
        # optional tags row
        if show_tags:
            tg = tasks.list_tags(tid, db_path)
            if tg:
                table.add_row("", f"[dim]tags: {', '.join(tg)}[/dim]", "", "", "", "", "", "")
        # per-entry bullets INSIDE the table
        if entries_map is not None:
            for note, m in entries_map.get(tid, []):
                if m <= 0:
                    continue
                label = (note or "").strip() or "(no note)"
                table.add_row("", f"[dim]  - {label} - {fmt_minutes(m)}[/dim]", "", "", "", "", "", "")

    console.print(table)

def _entries_for_task_md(task_id: int, win_start, win_end, db_path: Path) -> List[Tuple[str, int]]:
        return logs.entry_minutes_for_task_window(task_id, win_start, win_end, db_path)

# ---------- init / backup / doctor ----------

@app.command()
def init(ctx: typer.Context):
    """Initialize the database file and tables."""
    used = dbmod.init(ctx.obj.db_path)
    console.print(f"[green]initialized database at[/green] {used}")

    # Ensure XDG config exists at $XDG_CONFIG_HOME/tt/config.yml (or ~/.config/tt/config.yml)
    cfg_path = cfgmod.config_path()
    if not cfg_path.exists():
        # Build initial config using current context defaults
        current = cfgmod.load()
        init_cfg = {
            "db": str(ctx.obj.db_path),
            "rounding": (current.get("rounding") or "entry"),
            "default_status": current.get("default_status"),
            "list": current.get("list") or {"compact": False, "limit": None},
        }
        cfgmod.save(init_cfg, path=cfg_path, overwrite=False)
        console.print(f"[green]created config at[/green] {cfg_path}")
    else:
        console.print(f"[yellow]config already exists at[/yellow] {cfg_path}")

@app.command()
def backup(ctx: typer.Context, out: Path = typer.Option(None, "--out", help="Write SQL dump to file (otherwise stdout)")):
    """Dump database as SQL."""
    with dbmod.connect(ctx.obj.db_path) as conn:
        dump = "\n".join(conn.iterdump())
    if out:
        out.write_text(dump)
        console.print(f"[green]wrote[/green] {out}")
    else:
        typer.echo(dump)

@app.command()
def doctor(ctx: typer.Context):
    """Basic health checks."""
    issues: List[str] = []
    with dbmod.connect(ctx.obj.db_path) as conn:
        nrun = conn.execute("SELECT COUNT(*) FROM time_entries WHERE end IS NULL").fetchone()[0]
        if nrun > 1:
            issues.append(f"{nrun} running entries exist (expected ≤ 1).")
        # dangling entries (FK should prevent, but check anyway)
        d = conn.execute("""
            SELECT COUNT(*) FROM time_entries e
            LEFT JOIN tasks t ON t.id = e.task_id
            WHERE t.id IS NULL
        """).fetchone()[0]
        if d:
            issues.append(f"{d} time entries without a task.")
    if not issues:
        console.print("[green]No issues found.[/green]")
    else:
        for i in issues:
            console.print(f"[red]{i}[/red]")

# ---------- status / start / stop / switch / resume ----------

@app.command()
def status(ctx: typer.Context):
    """Show the currently running entry (if any) and live elapsed time."""
    run = logs.current_running(ctx.obj.db_path)
    if not run:
        console.print("[yellow]No entry running.[/yellow]")
        raise typer.Exit(0)
    entry_id, task_id = run
    with dbmod.connect(ctx.obj.db_path) as conn:
        row = conn.execute("SELECT start, note FROM time_entries WHERE id=?", (entry_id,)).fetchone()
    start_s, note = row
    start = datetime.fromisoformat(start_s)
    elapsed = int((datetime.now().astimezone() - start).total_seconds())
    title = tasks.get_title(task_id, ctx.obj.db_path) or f"#{task_id}"
    label = (note or "").strip() or "(no note)"
    console.print(f"[bold]Running[/bold] task {task_id} — {title}")
    console.print(f"  note: {label}")
    console.print(f"  elapsed: {fmt_minutes(logs._round_seconds_to_minutes(elapsed))}")

@app.command()
@_guard_db_errors
def start(
    ctx: typer.Context,
    task_id: int = typer.Argument(..., help="Task ID to start timing on"),
    note: str = typer.Option("", "--note", help="Optional note for this time entry"),
):
    """Start a time entry on the task. If another is running, it will be stopped."""
    # Validate task exists
    if not tasks.get(task_id, ctx.obj.db_path):
        _fail(f"task {task_id} not found")
    eid = logs.start(task_id, ctx.obj.db_path, note=note or None)
    suffix = f" — {note}" if note else ""
    console.print(f"[green]started[/green] entry {eid} on task {task_id}{suffix}")

@app.command()
@_guard_db_errors
def stop(ctx: typer.Context, task_id: int = typer.Argument(None)):
    """Stop the running entry. If task_id is given, stops the running entry on that task."""
    eid = logs.stop(task_id, ctx.obj.db_path)
    console.print("[yellow]nothing running[/yellow]" if eid is None else f"[green]stopped[/green] entry {eid}")

@app.command()
def switch(
    ctx: typer.Context,
    task_id: int = typer.Argument(..., help="Task ID to start timing on"),
    note: str = typer.Option("", "--note", help="Optional new note"),
):
    """Stop current (if any) and start timing another task."""
    if logs.current_running(ctx.obj.db_path):
        logs.stop(db_path=ctx.obj.db_path)
    # Validate task exists
    if not tasks.get(task_id, ctx.obj.db_path):
        _fail(f"task {task_id} not found")
    eid = logs.start(task_id, ctx.obj.db_path, note=note or None)
    console.print(f"[green]switched[/green] to task {task_id}, entry {eid}")

@app.command()
def resume(ctx: typer.Context, note: str = typer.Option("", "--note", help="Override note (optional)")):
    """Start a new entry on the most recently worked-on task."""
    with dbmod.connect(ctx.obj.db_path) as conn:
        row = conn.execute(
            "SELECT task_id, note FROM time_entries WHERE end IS NOT NULL ORDER BY end DESC LIMIT 1"
        ).fetchone()
    if not row:
        console.print("[yellow]No previous entry to resume.[/yellow]")
        raise typer.Exit(1)
    task_id, prev_note = row
    eid = logs.start(task_id, ctx.obj.db_path, note=(note or prev_note))
    console.print(f"[green]resumed[/green] task {task_id}, entry {eid}")

# ---------------- TUI launcher ----------------

@app.command()
def tui(ctx: typer.Context):
    """Launch interactive TUI (Textual)."""
    run_tui(ctx.obj.db_path, ctx.obj.rounding)

# ---------- task subcommands ----------

task_app = typer.Typer(help="Task commands")
app.add_typer(task_app, name="task")

@task_app.command("add")
def task_add(ctx: typer.Context, title: str):
    tid = tasks.add(title, ctx.obj.db_path)
    console.print(f"[green]task {tid} added[/green]: {title}")

@task_app.command("edit")
@_guard_db_errors
def task_edit(
    ctx: typer.Context,
    task_id: int = typer.Argument(..., help="Task ID to start timing on"),
    title: str = typer.Option(None, "--title"),
    priority: int = typer.Option(None, "--priority"),
    due: str = typer.Option(None, "--due", help="ISO date/time, e.g. 2025-09-19 or 2025-09-19 14:00"),
    estimate: int = typer.Option(None, "--estimate", help="Estimated minutes"),
    billable: bool = typer.Option(None, "--billable/--no-billable"),
):
    ok_title = True
    if title is not None:
        ok_title = tasks.edit_title(task_id, title, ctx.obj.db_path)
    ok_fields = tasks.edit_fields(task_id, ctx.obj.db_path, priority=priority, due_date=due, estimate_minutes=estimate, billable=billable)
    if not (ok_title and ok_fields):
        console.print(f"[red]task {task_id} not found[/red]")
        raise typer.Exit(1)
    console.print(f"[green]task {task_id} updated[/green]")

@task_app.command("done")
@_guard_db_errors
def task_done(ctx: typer.Context, task_id: int = typer.Argument(..., help="Task ID")):
    tasks.mark_done(task_id, ctx.obj.db_path)
    console.print(f"[green]task {task_id} marked done[/green]")

@task_app.command("archive")
@_guard_db_errors
def task_archive(ctx: typer.Context, task_id: int = typer.Argument(..., help="Task ID")):
    if tasks.archive(task_id, ctx.obj.db_path):
        console.print(f"[green]task {task_id} archived[/green]")
    else:
        console.print(f"[red]task {task_id} not found[/red]"); raise typer.Exit(1)

@task_app.command("unarchive")
@_guard_db_errors
def task_unarchive(ctx: typer.Context, task_id: int = typer.Argument(..., help="Task ID")):
    if tasks.unarchive(task_id, ctx.obj.db_path):
        console.print(f"[green]task {task_id} unarchived[/green]")
    else:
        console.print(f"[red]task {task_id} not found[/red]"); raise typer.Exit(1)

@task_app.command("rm")
@_guard_db_errors
def task_rm(ctx: typer.Context, task_id: int = typer.Argument(..., help="Task ID to start timing on"), force: bool = typer.Option(False, "--force")):
    try:
        ok = tasks.delete_task(task_id, ctx.obj.db_path, force=force)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
    if not ok:
        console.print(f"[red]task {task_id} not found[/red]"); raise typer.Exit(1)
    console.print(f"[green]task {task_id} deleted[/green]")

@task_app.command("merge")
@_guard_db_errors
def task_merge(ctx: typer.Context, src: int = typer.Argument(..., help="Source task ID"), dst: int = typer.Argument(..., help="Destination task ID")):
    if tasks.merge_tasks(src, dst, ctx.obj.db_path):
        console.print(f"[green]merged[/green] task {src} → {dst}")
    else:
        console.print(f"[red]source task not found[/red]"); raise typer.Exit(1)

@task_app.command("tag")
@_guard_db_errors
def task_tag(
    ctx: typer.Context,
    task_id: int = typer.Argument(..., help="Task ID to start timing on"),
    add: List[str] = typer.Option(None, "--add", help="Add tag (repeatable)"),
    remove: List[str] = typer.Option(None, "--remove", help="Remove tag (repeatable)"),
    list_tags: bool = typer.Option(False, "--ls", help="List tags"),
):
    if list_tags:
        tg = tasks.list_tags(task_id, ctx.obj.db_path)
        console.print(", ".join(tg) if tg else "(no tags)")
        return
    for t in (add or []):
        tasks.add_tag(task_id, t, ctx.obj.db_path)
    for t in (remove or []):
        tasks.remove_tag(task_id, t, ctx.obj.db_path)
    console.print("[green]ok[/green]")

@task_app.command("ls")
def task_ls(
    ctx: typer.Context,
    status: str = typer.Option(None, "--status", help="todo|doing|done"),
    tag: List[str] = typer.Option(None, "--tag", help="Filter by tag (AND, repeatable)"),
    since: str = typer.Option(None, "--since", help="today|yesterday|monday|week|last-week|month|ISO"),
    until: str = typer.Option(None, "--until", help="now|ISO"),
    all_: bool = typer.Option(False, "--all", help="Include archived"),
    compact: bool = typer.Option(None, "--compact", help="Compact view (hide per-entry lines)"),
    limit: int = typer.Option(None, "--limit"),
    json_out: bool = typer.Option(False, "--json"),
    parent_id: int = typer.Option(None, '--parent-id', help='Show sub-tasks of this task ID'),
):
    from .tasks import list_tasks, get_children
    from rich.table import Table
    import typer
    if parent_id is not None:
        tasks = get_children(parent_id)
    else:
        tasks = list_tasks()
        child_ids = set()
        for task in tasks:
            for child in get_children(task[0]):
                child_ids.add(child[0])
        tasks = [t for t in tasks if t[0] not in child_ids]  # filter out sub-tasks
    table = Table(title=None)
    table.add_column("ID", style="dim", width=4)
    table.add_column("Title", width=80)
    table.add_column("Status", width=8)
    table.add_column("Pri", width=5)
    table.add_column("Due")
    def add_task_row(task, indent=''):
        title = indent + task[1]
        pri = str(task[5]) if len(task) > 5 else ''
        due = str(task[6]) if len(task) > 6 else ''
        table.add_row(str(task[0]), title, task[2], pri, due)
        for child in get_children(task[0]):
            add_task_row(child, indent=indent + '  ↳ ')
    for task in tasks:
        add_task_row(task)
    from rich.console import Console
    Console().print(table)
    return
    used_compact = ctx.obj.list_compact if compact is None else compact
    used_limit = limit or ctx.obj.list_limit
    rows = tasks.list_tasks(status, ctx.obj.db_path, include_archived=all_, tags=tag or [], limit=used_limit)

    s, u = tparse.window(since, until)
    totals = (logs.minutes_by_task_window(s, u, ctx.obj.db_path, rounding=ctx.obj.rounding)
              if (s or u) else logs.minutes_by_task(ctx.obj.db_path, rounding=ctx.obj.rounding))

    if json_out:
        out = []
        for r in rows:
            tid, title, st, created, completed, archived_at, prio, due, est, billable = r
            item = {
                "id": tid, "title": title, "status": st, "priority": prio, "due": due,
                "estimate": est, "billable": bool(billable), "total_minutes": totals.get(tid, 0),
                "tags": tasks.list_tags(tid, ctx.obj.db_path),
            }
            if not used_compact:
                item["entries"] = [{"note": note, "minutes": mins}
                                   for note, mins in (logs.entry_minutes_for_task_window(tid, s, u, ctx.obj.db_path) if (s or u)
                                                      else logs.entry_minutes_for_task(tid, ctx.obj.db_path))]
            out.append(item)
        typer.echo(json.dumps(out, indent=2))
        return

    entries_map = None
    if not used_compact:
        entries_map = {}
        for r in rows:
            tid = r[0]
            entries_map[tid] = (
                logs.entry_minutes_for_task_window(tid, s, u, ctx.obj.db_path)
                if (s or u)
                else logs.entry_minutes_for_task(tid, ctx.obj.db_path)
            )

    _print_tasks_table(rows, totals, show_tags=True, db_path=ctx.obj.db_path, entries_map=entries_map)

# ---------- logs subcommands ----------

log_app = typer.Typer(help="Time entry (log) commands")
app.add_typer(log_app, name="log")
app.add_typer(config_app, name="config")
@log_app.command("ls")
def log_ls(
    ctx: typer.Context,
    task_id: typing.Optional[int] = typer.Argument(None, help="Task ID to list logs for"),
    all_tasks: bool = typer.Option(False, "--all", help="Show logs across all tasks"),
    since: typing.Optional[str] = typer.Option(None, "--since", help="Filter: start >= ISO (e.g. 2025-09-01)"),
    until: typing.Optional[str] = typer.Option(None, "--until", help="Filter: end <= ISO"),
    grouped: bool = typer.Option(False, "--grouped", help="Group by task (only with --all)"),
    csv_out: bool = typer.Option(False, "--csv", help="CSV output"),
    json_out: bool = typer.Option(False, "--json", help="JSON output"),
    today: bool = typer.Option(False, "--today", help="Only logs from today"),
    week: bool = typer.Option(False, "--week", help="Only logs from the current week (Mon–Sun)"),
    running: bool = typer.Option(False, "--running", help="Only running entries (no end)"),
):
    """
    List logs. Either provide TASK_ID or use --all.
    """
    used_db = ctx.obj.db_path

    # Determine task ids
    if all_tasks:
        task_rows = tasks.list_tasks(db_path=used_db, include_archived=True)
        tids = [int(r[0]) for r in task_rows]
    elif task_id is not None:
        tids = [int(task_id)]
    else:
        console.print("[red]Error:[/red] provide TASK_ID or use --all")
        raise typer.Exit(2)

    # Compute window
    s, u = tparse.window(since, until)
    if today and not since and not until:
        now = datetime.now()
        s = now.strftime("%Y-%m-%dT00:00:00")
        u = now.strftime("%Y-%m-%dT23:59:59")
    if week and not since and not until:
        now = datetime.now()
        start_w = now - timedelta(days=now.weekday())
        end_w = start_w + timedelta(days=6)
        s = start_w.strftime("%Y-%m-%dT00:00:00")
        u = end_w.strftime("%Y-%m-%dT23:59:59")

    # Collect rows
    rows = []  # (eid, tid, start, end, note, minutes)
    for tid in tids:
        for eid, start_s, end_s, note, mins in logs.entries_with_durations(tid, used_db):
            if running and (end_s or ""):
                continue
            # Apply window overlap if set
            if s or u:
                sec = logs._overlap_seconds(start_s, end_s, s, u)
                m2 = logs._round_seconds_to_minutes(sec) if sec > 0 else 0
                if m2 <= 0:
                    continue
                mins = m2
            rows.append((int(eid), int(tid), start_s or "", end_s or "", note, int(mins or 0)))

    # Output
    if csv_out:
        import csv as _csv
        w = _csv.writer(sys.stdout)
        w.writerow(["id", "task_id", "start", "end", "minutes", "note"])
        for eid, tid, start_s, end_s, note, mins in rows:
            w.writerow([eid, tid, start_s, end_s, mins, note or ""])
        return

    if json_out:
        import json as _json
        print(_json.dumps([
            {"id": eid, "task_id": tid, "start": s, "end": e, "minutes": mins, "note": note}
            for (eid, tid, s, e, note, mins) in rows
        ], indent=2))
        return

    # Pretty rich table
    if grouped and all_tasks:
        by_task = {}
        for eid, tid, s1, e1, note, mins in rows:
            by_task.setdefault(tid, []).append((eid, s1, e1, note, mins))
        for tid, logs_ in sorted(by_task.items(), key=lambda kv: kv[0], reverse=True):
            title = tasks.get_title(tid, used_db) or f"(task {tid})"
            total = sum(m for _eid, _s, _e, _n, m in logs_)
            console.print(f"\n[bold]Task {tid}:[/bold] {title} — total {fmt_minutes(total)}")
            table = Table(box=box.SIMPLE_HEAVY)
            table.add_column("ID", justify="right")
            table.add_column("Start")
            table.add_column("End")
            table.add_column("Min", justify="right")
            table.add_column("Note")
            for eid, s1, e1, note, mins in logs_:
                table.add_row(str(eid), s1, e1 or "(running)", str(mins), (note or "")[:80])
            console.print(table)
        return
    else:
        table = Table(box=box.SIMPLE_HEAVY)
        table.add_column("ID", justify="right")
        table.add_column("Task", justify="right")
        table.add_column("Start")
        table.add_column("End")
        table.add_column("Min", justify="right")
        table.add_column("Note")
        for eid, tid, s1, e1, note, mins in rows:
            table.add_row(str(eid), str(tid), s1, e1 or "(running)", str(mins), (note or "")[:80])
        console.print(table)
        return
@log_app.command("add")
@_guard_db_errors
def log_add(
    ctx: typer.Context,
    task_id: int = typer.Argument(..., help="Task ID to start timing on"),
    minutes: int = typer.Option(None, "--minutes", help="Duration in minutes; creates 'now - minutes' → now"),
    start: str = typer.Option(None, "--start", help="Start datetime (ISO or 'YYYY-MM-DD HH:MM'); requires --end or --minutes"),
    end: str = typer.Option(None, "--end", help="End datetime (ISO or 'YYYY-MM-DD HH:MM')"),
    ago: str = typer.Option(None, "--ago", help="Human duration like '90m', '2h', '1h30m', '1d2h'; creates 'now - ago' → now"),
    note: str = typer.Option("", "--note", help="Optional note for this entry"),
):
    if not tasks.get(task_id, ctx.obj.db_path):
        _fail(f"task {task_id} not found")
    if minutes is None and ago is None and not (start and end):
        _fail("Provide one of: --minutes, --ago, or both --start and --end")
    try:
        eid = logs.add_manual_entry(task_id, ctx.obj.db_path, minutes=minutes, start=start, end=end, ago=ago, note=note or None)
    except ValueError as e:
        _fail(str(e), code=2)
    console.print(f"[green]entry {eid} added[/green]")

@log_app.command("rm")
@_guard_db_errors
def log_rm(ctx: typer.Context, entry_id: int):
    ok = logs.delete_entry(entry_id, ctx.obj.db_path)
    if not ok:
        console.print(f"[red]entry {entry_id} not found[/red]"); raise typer.Exit(1)
    console.print(f"[green]entry {entry_id} deleted[/green]")

@log_app.command("edit")
@_guard_db_errors
def log_edit(
    ctx: typer.Context,
    entry_id: int,
    minutes: int = typer.Option(None, "--minutes", help="Set duration in whole minutes (entry must be stopped)"),
    note: str = typer.Option(None, "--note", help="Set/replace the note"),
):
    try:
        ok = logs.edit_entry(entry_id, ctx.obj.db_path, minutes=minutes, note=note)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
    if not ok:
        console.print(f"[red]entry {entry_id} not found[/red]"); raise typer.Exit(1)
    console.print(f"[green]entry {entry_id} updated[/green]")

@log_app.command("move")
@_guard_db_errors
def log_move(ctx: typer.Context, entry_id: int, new_task_id: int):
    if logs.reassign_entry(entry_id, new_task_id, ctx.obj.db_path):
        console.print(f"[green]moved[/green] entry {entry_id} → task {new_task_id}")
    else:
        console.print(f"[red]entry {entry_id} not found[/red]"); raise typer.Exit(1)

@log_app.command("split")
@_guard_db_errors
def log_split(ctx: typer.Context, entry_id: int, at: str = typer.Option(..., "--at", help="Split point (ISO or 'YYYY-MM-DD HH:MM')")):
    try:
        left, right = logs.split_entry(entry_id, at, ctx.obj.db_path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
    console.print(f"[green]split[/green] entry {entry_id} into [{left}] + [{right}]")

@log_app.command("trim")
@_guard_db_errors
def log_trim(
    ctx: typer.Context,
    entry_id: int,
    start: str = typer.Option(None, "--start", help="New start"),
    end: str = typer.Option(None, "--end", help="New end"),
):
    try:
        ok = logs.trim_entry(entry_id, start, end, ctx.obj.db_path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
    if not ok:
        console.print(f"[red]entry {entry_id} not found[/red]"); raise typer.Exit(1)
    console.print(f"[green]trimmed[/green] entry {entry_id}")

# ---------- reports & export ----------

@app.command()
def report(
    ctx: typer.Context,
    since: str = typer.Option(None, "--since"),
    until: str = typer.Option(None, "--until"),
    group: str = typer.Option("task", "--group", help="task|tag|day"),
    billable_only: bool = typer.Option(False, "--billable-only"),
    json_out: bool = typer.Option(False, "--json"),
    csv_out: Path = typer.Option(None, "--csv", help="Write CSV to file"),
):
    """Summaries grouped by task|tag|day. Respects rounding policy from config/env."""
    s, u = tparse.window(since, until)
    used_db = ctx.obj.db_path
    # Fetch all needed rows once
    with dbmod.connect(used_db) as conn:
        rows = conn.execute("""
            SELECT e.task_id, e.start, e.end, t.title, t.billable,
                   (SELECT GROUP_CONCAT(g.name, ',')
                      FROM task_tags x JOIN tags g ON g.id = x.tag_id
                     WHERE x.task_id = e.task_id)
            FROM time_entries e
            JOIN tasks t ON t.id = e.task_id
        """).fetchall()

    # accumulate
    if group not in ("task", "tag", "day"):
        console.print("[red]invalid --group (use task|tag|day)[/red]"); raise typer.Exit(1)

    sec_acc: Dict[str, int] = {}
    entry_acc: Dict[str, int] = {}
    for task_id, start_s, end_s, title, billable, tag_csv in rows:
        if billable_only and not billable:
            continue
        sec = logs._overlap_seconds(start_s, end_s, s, u)
        if sec <= 0:
            continue
        if group == "task":
            key = f"{task_id}:{title}"
            sec_acc[key] = sec_acc.get(key, 0) + sec
            entry_acc[key] = entry_acc.get(key, 0) + logs._round_seconds_to_minutes(sec)
        elif group == "day":
            day = start_s[:10]  # YYYY-MM-DD
            sec_acc[day] = sec_acc.get(day, 0) + sec
            entry_acc[day] = entry_acc.get(day, 0) + logs._round_seconds_to_minutes(sec)
        else:  # tag
            tags_list = [t for t in (tag_csv or "").split(",") if t]
            if not tags_list:
                tags_list = ["(untagged)"]
            for tg in tags_list:
                sec_acc[tg] = sec_acc.get(tg, 0) + sec
                entry_acc[tg] = entry_acc.get(tg, 0) + logs._round_seconds_to_minutes(sec)

    totals = {k: logs._round_seconds_to_minutes(v) for k, v in sec_acc.items()} if ctx.obj.rounding == "overall" else entry_acc

    # output
    items = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    if json_out:
        typer.echo(json.dumps([{"key": k, "minutes": m} for k, m in items], indent=2))
        return

    if csv_out:
        import csv
        with open(csv_out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "minutes"])
            for k, m in items:
                w.writerow([k, m])
        console.print(f"[green]wrote[/green] {csv_out}")
        return

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Group"); table.add_column("Minutes", justify="right")
    for k, m in items:
        table.add_row(k, str(m))
    console.print(table)

@app.command()
@app.command()
@app.command()
def export(
    ctx: typer.Context,
    format: str = typer.Option("md", "--format", help="Output format: md or csv"),
    since: str = typer.Option("today", "--since"),
    until: str = typer.Option("now", "--until"),
    out: Optional[Path] = typer.Option(None, "--out", help="Output file path (for CSV only)"),
):
    """
    Export data in markdown or CSV format.
    - Markdown: grouped by task, printed to console
    - CSV: raw entries with columns: task_id, title, start, end, minutes, note
    """
    from . import time_entries as logs, tasks
    from .time_entries import _round_seconds_to_minutes, _overlap_seconds
    from . import timeparse as tparse

    s, u = tparse.window(since, until)

    if format == "md":
        rows = tasks.list_tasks(None, ctx.obj.db_path, include_archived=False)
        lines: List[str] = []
        for r in rows:
            tid, title, *_ = r
            per = logs.entry_minutes_for_task_window(tid, s, u, ctx.obj.db_path)
            if not per:
                continue
            total = sum(m for _, m in per)
            lines.append(f"- {title} — {fmt_minutes(total)}")
            for note, m in per:
                lines.append(f"  - {note or '(no note)'} — {fmt_minutes(m)}")
        typer.echo("\n".join(lines) if lines else "(no data)")

    elif format == "csv":
        if out is None:
            console.print("[red]--out is required when using --format csv[/red]")
            raise typer.Exit(1)
        import csv
        with dbmod.connect(ctx.obj.db_path) as conn, open(out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["task_id", "task_title", "start", "end", "minutes", "note"])
            rows = conn.execute("""
                SELECT e.task_id, t.title, e.start, e.end, e.note
                FROM time_entries e JOIN tasks t ON t.id = e.task_id
                ORDER BY e.start
            """).fetchall()
            for task_id, title, start_s, end_s, note in rows:
                sec = _overlap_seconds(start_s, end_s, s, u)
                if sec <= 0:
                    continue
                w.writerow([task_id, title, start_s, end_s or "", _round_seconds_to_minutes(sec), (note or "").strip()])
        console.print(f"[green]wrote[/green] {out}")

    else:
        console.print("[red]Invalid format. Use --format md or csv[/red]")
        raise typer.Exit(1)

@task_app.command("tree")
@_guard_db_errors
def task_tree(
    ctx: typer.Context,
    status: str = typer.Option(None, "--status", help="todo|doing|done"),
    tag: List[str] = typer.Option(None, "--tag", help="Filter by tag (AND, repeatable)"),
    since: str = typer.Option(None, "--since", help="today|yesterday|monday|week|last-week|month|ISO"),
    until: str = typer.Option(None, "--until", help="now|ISO"),
    all_: bool = typer.Option(False, "--all", help="Include archived"),
    compact: bool = typer.Option(None, "--compact", help="Compact view (hide per-entry lines)"),
    limit: int = typer.Option(None, "--limit"),
):
    """Show tasks as a tree with subtasks and (optionally) per-entry log lines."""
    from rich.table import Table
    from rich.console import Console
    from .tasks import list_tasks, get_children, list_tags
    used_compact = ctx.obj.list_compact if compact is None else compact
    used_limit = limit or ctx.obj.list_limit

    # Base rows and totals in the same way as task ls
    rows = list_tasks(status, ctx.obj.db_path, include_archived=all_, tags=tag or [], limit=used_limit)
    s, u = tparse.window(since, until)
    totals = (logs.minutes_by_task_window(s, u, ctx.obj.db_path, rounding=ctx.obj.rounding)
              if (s or u) else logs.minutes_by_task(ctx.obj.db_path, rounding=ctx.obj.rounding))

    # Index rows and build child map
    rows_by_id = {r[0]: r for r in rows}
    order_ids = [r[0] for r in rows]
    child_ids = set()
    child_map: Dict[int, List[int]] = {tid: [] for tid in order_ids}
    for tid in order_ids:
        try:
            children = get_children(tid, db_path=ctx.obj.db_path) or []
        except Exception:
            children = []
        for c in children:
            cid = c[0]
            child_ids.add(cid)
            child_map.setdefault(tid, []).append(cid)
            if cid not in rows_by_id:
                padded = tuple(c) + (None,) * (10 - len(c))
                rows_by_id[cid] = padded

    top_level_ids = [tid for tid in order_ids if tid not in child_ids]

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("ID", justify="right")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Pri", justify="right")
    table.add_column("Due")
    table.add_column("Est", justify="right")
    table.add_column("Bill")
    table.add_column("Total")

    def add_task_rows(tid: int, indent: str = "") -> None:
        r = rows_by_id.get(tid)
        if not r:
            return
        r = tuple(r) + (None,) * (10 - len(r))
        _, title, st, _, _, _, prio, due, est, billable = r[:10]
        bill = "✓" if billable else "•"
        total = totals.get(tid, 0)
        title_with_tags = title
        tags = list_tags(tid, ctx.obj.db_path)
        if tags:
            title_with_tags += f"\n    tags: {', '.join(tags)}"
        table.add_row(str(tid), indent + title_with_tags, st, str(prio or 0), due or "", f"{est or 0}", bill, fmt_minutes(total))

        # Per-entry lines (like task ls) when not compact
        if not used_compact:
            entries = (logs.entry_minutes_for_task_window(tid, s, u, ctx.obj.db_path)
                       if (s or u) else logs.entry_minutes_for_task(tid, ctx.obj.db_path))
            for note, minutes in entries:
                table.add_row("", indent + f"  - {note} - {fmt_minutes(minutes)}", "", "", "", "", "", "")

        # Recurse
        for cid in sorted(child_map.get(tid, [])):
            add_task_rows(cid, indent + "  ↳ ")

    for tid in sorted(top_level_ids):
        add_task_rows(tid)

    Console().print(table)
