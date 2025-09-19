# tt/cli.py
from __future__ import annotations
import json
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
from .pomodoro import run_pomodoro, parse_pom_config

console = Console()
# Show help when no args; disable shell-completion noise
app = typer.Typer(help="Tiny tasks + time tracker", add_completion=False, no_args_is_help=True)

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
def start(
    ctx: typer.Context,
    task_id: int,
    note: str = typer.Option("", "--note", help="Optional note for this time entry"),
):
    """Start a time entry on the task. If another is running, it will be stopped."""
    eid = logs.start(task_id, ctx.obj.db_path, note=note or None)
    suffix = f" — {note}" if note else ""
    console.print(f"[green]started[/green] entry {eid} on task {task_id}{suffix}")

@app.command()
def stop(ctx: typer.Context, task_id: int = typer.Argument(None)):
    """Stop the running entry. If task_id is given, stops the running entry on that task."""
    eid = logs.stop(task_id, ctx.obj.db_path)
    console.print("[yellow]nothing running[/yellow]" if eid is None else f"[green]stopped[/green] entry {eid}")

@app.command()
def switch(
    ctx: typer.Context,
    task_id: int,
    note: str = typer.Option("", "--note", help="Optional new note"),
):
    """Stop current (if any) and start timing another task."""
    if logs.current_running(ctx.obj.db_path):
        logs.stop(db_path=ctx.obj.db_path)
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

# ---------------- Pomodoro commands -----------

pom_app = typer.Typer(help="Pomodoro timer")
app.add_typer(pom_app, name="pom")

@pom_app.command("start")
def pom_start(
    ctx: typer.Context,
    task_id: int,
    length: str = typer.Option("25m", "--length", help="Work length (e.g., 25m, 1h)"),
    short_break: str = typer.Option("5m", "--short-break"),
    long_break: str = typer.Option("15m", "--long-break"),
    cycles: int = typer.Option(4, "--cycles", help="Number of work blocks"),
    long_every: int = typer.Option(4, "--long-every", help="Long break every N cycles"),
    auto_breaks: bool = typer.Option(True, "--auto-breaks/--no-auto-breaks"),
    note_prefix: str = typer.Option("Pomodoro", "--note-prefix"),
):
    """
    Runs a blocking Pomodoro session that starts/stops real logs.
    Ctrl+C to abort; current entry will stop.
    """
    cfg = parse_pom_config(task_id, length, short_break, long_break, cycles, long_every, auto_breaks, note_prefix)
    run_pomodoro(ctx.obj.db_path, cfg)

# ---------- task subcommands ----------

task_app = typer.Typer(help="Task commands")
app.add_typer(task_app, name="task")

@task_app.command("add")
def task_add(ctx: typer.Context, title: str):
    tid = tasks.add(title, ctx.obj.db_path)
    console.print(f"[green]task {tid} added[/green]: {title}")

@task_app.command("edit")
def task_edit(
    ctx: typer.Context,
    task_id: int,
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
def task_done(ctx: typer.Context, task_id: int):
    tasks.mark_done(task_id, ctx.obj.db_path)
    console.print(f"[green]task {task_id} marked done[/green]")

@task_app.command("archive")
def task_archive(ctx: typer.Context, task_id: int):
    if tasks.archive(task_id, ctx.obj.db_path):
        console.print(f"[green]task {task_id} archived[/green]")
    else:
        console.print(f"[red]task {task_id} not found[/red]"); raise typer.Exit(1)

@task_app.command("unarchive")
def task_unarchive(ctx: typer.Context, task_id: int):
    if tasks.unarchive(task_id, ctx.obj.db_path):
        console.print(f"[green]task {task_id} unarchived[/green]")
    else:
        console.print(f"[red]task {task_id} not found[/red]"); raise typer.Exit(1)

@task_app.command("rm")
def task_rm(ctx: typer.Context, task_id: int, force: bool = typer.Option(False, "--force")):
    try:
        ok = tasks.delete_task(task_id, ctx.obj.db_path, force=force)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
    if not ok:
        console.print(f"[red]task {task_id} not found[/red]"); raise typer.Exit(1)
    console.print(f"[green]task {task_id} deleted[/green]")

@task_app.command("merge")
def task_merge(ctx: typer.Context, src: int, dst: int):
    if tasks.merge_tasks(src, dst, ctx.obj.db_path):
        console.print(f"[green]merged[/green] task {src} → {dst}")
    else:
        console.print(f"[red]source task not found[/red]"); raise typer.Exit(1)

@task_app.command("tag")
def task_tag(
    ctx: typer.Context,
    task_id: int,
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
):
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

@log_app.command("ls")
def log_ls(
    ctx: typer.Context,
    task_id: int,
    since: str = typer.Option(None, "--since"),
    until: str = typer.Option(None, "--until"),
):
    """List time entries for a task (with entry IDs), optionally within a window."""
    s, u = tparse.window(since, until)
    used_db = ctx.obj.db_path
    rows = logs.entries_with_durations(task_id, used_db)
    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("ID", justify="right"); table.add_column("Start"); table.add_column("End"); table.add_column("Min", justify="right"); table.add_column("Note")
    for eid, start_s, end_s, note, mins in rows:
        if s or u:
            sec = logs._overlap_seconds(start_s, end_s, s, u)
            mins = logs._round_seconds_to_minutes(sec) if sec > 0 else 0
            if mins <= 0: continue
        table.add_row(str(eid), start_s, end_s or "(running)", str(mins), note or "")
    console.print(table)

@log_app.command("add")
def log_add(
    ctx: typer.Context,
    task_id: int,
    minutes: int = typer.Option(None, "--minutes", help="Duration in minutes; creates 'now - minutes' → now"),
    start: str = typer.Option(None, "--start", help="Start datetime (ISO or 'YYYY-MM-DD HH:MM'); requires --end or --minutes"),
    end: str = typer.Option(None, "--end", help="End datetime (ISO or 'YYYY-MM-DD HH:MM')"),
    ago: str = typer.Option(None, "--ago", help="Human duration like '90m', '2h', '1h30m', '1d2h'; creates 'now - ago' → now"),
    note: str = typer.Option("", "--note", help="Optional note for this entry"),
):
    try:
        eid = logs.add_manual_entry(task_id, ctx.obj.db_path, minutes=minutes, start=start, end=end, ago=ago, note=note or None)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
    console.print(f"[green]entry {eid} added[/green]")

@log_app.command("rm")
def log_rm(ctx: typer.Context, entry_id: int):
    ok = logs.delete_entry(entry_id, ctx.obj.db_path)
    if not ok:
        console.print(f"[red]entry {entry_id} not found[/red]"); raise typer.Exit(1)
    console.print(f"[green]entry {entry_id} deleted[/green]")

@log_app.command("edit")
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
def log_move(ctx: typer.Context, entry_id: int, new_task_id: int):
    if logs.reassign_entry(entry_id, new_task_id, ctx.obj.db_path):
        console.print(f"[green]moved[/green] entry {entry_id} → task {new_task_id}")
    else:
        console.print(f"[red]entry {entry_id} not found[/red]"); raise typer.Exit(1)

@log_app.command("split")
def log_split(ctx: typer.Context, entry_id: int, at: str = typer.Option(..., "--at", help="Split point (ISO or 'YYYY-MM-DD HH:MM')")):
    try:
        left, right = logs.split_entry(entry_id, at, ctx.obj.db_path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
    console.print(f"[green]split[/green] entry {entry_id} into [{left}] + [{right}]")

@log_app.command("trim")
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
def export_md(
    ctx: typer.Context,
    since: str = typer.Option("today", "--since"),
    until: str = typer.Option("now", "--until"),
):
    """Markdown export grouped by task with per-entry bullets."""
    s, u = tparse.window(since, until)
    rows = tasks.list_tasks(None, ctx.obj.db_path, include_archived=False)
    lines: List[str] = []
    for r in rows:
        tid, title, *_ = r
        per = logs.entry_minutes_for_task_window(tid, s, u, ctx.obj.db_path)
        if not per: continue
        total = sum(m for _, m in per)
        lines.append(f"- {title} — {fmt_minutes(total)}")
        for note, m in per:
            lines.append(f"  - {note or '(no note)'} — {fmt_minutes(m)}")
    typer.echo("\n".join(lines) if lines else "(no data)")

@app.command()
def export_csv(
    ctx: typer.Context,
    since: str = typer.Option(None, "--since"),
    until: str = typer.Option(None, "--until"),
    out: Path = typer.Option(..., "--out"),
):
    """CSV export: task,title,start,end,minutes,note"""
    import csv
    s, u = tparse.window(since, until)
    with dbmod.connect(ctx.obj.db_path) as conn, open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["task_id", "task_title", "start", "end", "minutes", "note"])
        rows = conn.execute("""
            SELECT e.task_id, t.title, e.start, e.end, e.note
            FROM time_entries e JOIN tasks t ON t.id = e.task_id
            ORDER BY e.start
        """).fetchall()
        for task_id, title, start_s, end_s, note in rows:
            sec = logs._overlap_seconds(start_s, end_s, s, u)
            if sec <= 0: continue
            w.writerow([task_id, title, start_s, end_s or "", logs._round_seconds_to_minutes(sec), (note or "").strip()])
    console.print(f"[green]wrote[/green] {out}")

# ---------- entry point ----------

if __name__ == "__main__":
    app()
