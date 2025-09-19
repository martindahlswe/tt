# tt/pomodoro.py
from __future__ import annotations
import signal
import time
from dataclasses import dataclass
from typing import Optional, Callable
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from . import time_entries as logs

console = Console()

def _parse_minutes(s: str) -> int:
    # Reuse the duration parser from time_entries if available
    try:
        return logs._parse_duration_to_minutes(s)  # type: ignore[attr-defined]
    except Exception:
        # minimal fallback (e.g., "25", "25m", "1h30m")
        s = s.strip().lower()
        if s.isdigit(): return int(s)
        total = 0
        num = ""
        for ch in s:
            if ch.isdigit(): num += ch; continue
            if ch == "h": total += int(num) * 60; num = ""
            elif ch == "m": total += int(num); num = ""
            else: raise ValueError(f"bad duration: {s}")
        if num: total += int(num)
        return total

@dataclass
class PomConfig:
    task_id: int
    work_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    cycles: int = 4
    long_every: int = 4          # long break after every N work sessions
    auto_breaks: bool = True     # if False, wait for keypress between sessions
    note_prefix: str = "Pomodoro"

def _beep():
    try:
        console.print("\a", end="")  # terminal bell
    except Exception:
        pass

def _run_interval(seconds: int, label: str, on_tick: Optional[Callable[[int], None]] = None):
    if seconds <= 0:
        return
    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed} / {task.total}s"),
        TimeRemainingColumn(),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task(label, total=seconds)
        start = time.time()
        while not progress.finished:
            elapsed = int(time.time() - start)
            remaining = max(0, seconds - elapsed)
            progress.update(task, completed=min(elapsed, seconds))
            if on_tick:
                on_tick(remaining)
            time.sleep(0.5)

def run_pomodoro(db_path, cfg: PomConfig):
    """
    Blocking CLI loop that starts/stops real time entries for each work block.
    Ctrl+C cleanly stops the current entry and exits.
    """
    stop_requested = False

    def handle_sigint(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    old = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_sigint)

    def run_block(minutes: int, label: str, start_entry: bool):
        nonlocal stop_requested
        secs = minutes * 60
        entry_id = None
        if start_entry:
            entry_id = logs.start(cfg.task_id, db_path, note=f"{cfg.note_prefix}: {label}")
        console.rule(f"[bold]{label}[/bold] ({minutes}m)")
        try:
            _run_interval(secs, label)
        finally:
            if start_entry and entry_id is not None:
                logs.stop(db_path=db_path)
        _beep()

    try:
        for n in range(1, cfg.cycles + 1):
            if stop_requested: break
            run_block(cfg.work_minutes, f"Work #{n}", start_entry=True)
            if stop_requested: break
            is_long = (n % cfg.long_every == 0)
            bmin = cfg.long_break_minutes if is_long else cfg.short_break_minutes
            if bmin > 0:
                run_block(bmin, "Long Break" if is_long else "Break", start_entry=False)
            if not cfg.auto_breaks and n < cfg.cycles:
                console.input("[dim]Press Enter to start next work block...[/dim]")
        console.rule("[green]Pomodoro finished[/green]")
    except KeyboardInterrupt:
        pass
    finally:
        # Ensure any running entry is closed
        logs.stop(db_path=db_path)
        signal.signal(signal.SIGINT, old)

def parse_pom_config(task_id: int, length: str, short_break: str, long_break: str, cycles: int, long_every: int, auto_breaks: bool, note_prefix: str) -> PomConfig:
    return PomConfig(
        task_id=task_id,
        work_minutes=_parse_minutes(length),
        short_break_minutes=_parse_minutes(short_break),
        long_break_minutes=_parse_minutes(long_break),
        cycles=cycles,
        long_every=long_every,
        auto_breaks=auto_breaks,
        note_prefix=note_prefix.strip() or "Pomodoro",
    )
