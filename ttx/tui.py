# tt/tui.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict, Any

from . import config as cfgmod

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Input
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

from . import tasks
from . import time_entries as logs


HELP_TEXT = """[b]Keys[/b]
  Tab: switch
  ↑/↓ or j/k: move
  Enter/Space: start/stop
  a: add
  e: edit
  x/X: delete
  Del/Backspace: delete log
  r: refresh 
  q: quit
  t: toggle
  o/v/U/M: sort/bulk ops
  Esc: cancel
"""


class StatusBar(Static):
    def set_message(self, msg: str) -> None:
        self.update(msg)


class TTApp(App):
    # ------------- state persistence -------------
    def _state_path(self) -> Path:
        try:
            cfg_dir = cfgmod.config_path().parent
        except Exception:
            cfg_dir = Path.home() / ".config" / "tt"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        return cfg_dir / "tui_state.json"

    def _save_state(self) -> None:
        """Persist lightweight UI state; safe even if widgets are already unmounted."""
        try:
            try:
                sel_task = self._get_selected_task_id()
            except Exception:
                sel_task = None
            try:
                sel_entry = self._get_selected_entry_id()
            except Exception:
                sel_entry = None

            st = {
                "focus": self.focus_where,
                "compact": self.compact,
                "log_sort_key": self._log_sort_key,
                "log_filter": self._log_filter,
                "selected_task_id": sel_task,
                "selected_entry_id": sel_entry,
            }
            self._state_path().write_text(json.dumps(st), encoding="utf-8")
        except Exception:
            pass

    def _load_state(self) -> dict:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            return data
        except Exception:
            return {}

    def _set_selected_task_id(self, task_id: int | None) -> None:
        if task_id is None:
            return
        t = self.query_one("#tasks", DataTable)
        try:
            row = self._task_row_ids.index(task_id)
        except ValueError:
            return
        try:
            t.cursor_coordinate = (row, 0)
        except Exception:
            pass

    def _set_selected_entry_id(self, entry_id: int | None) -> None:
        if entry_id is None:
            return
        e = self.query_one("#entries", DataTable)
        try:
            row = self._entry_row_ids.index(entry_id)
        except ValueError:
            return
        try:
            e.cursor_coordinate = (row, 0)
        except Exception:
            pass

    CSS = """
    Screen { layout: vertical; }
    #tables { layout: horizontal; }
    #left, #right { width: 1fr; }
    #status { height: 3; }
    #filterbar { height: 1; content-align: left middle; padding: 0 1; color: $text; background: $boost; }

    /* Make active edit step visually obvious */
    .inline-banner {
        background: $accent;
        color: $background;
        padding: 0 2;
        height: auto;
        content-align: left middle;
        text-style: bold;
        margin-bottom: 1;
    }
    Input.edit-field {
        border: heavy $accent;
        background: $boost;
        text-style: bold;
    }
    .overlay {
        layer: overlay;
        background: $panel 80%;
        width: 100%;
        height: 100%;
        content-align: left top;
        padding: 2 3;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("t", "toggle_compact", "Compact", priority=True),
        Binding("tab", "toggle_focus", "Focus", priority=True),
        Binding("escape", "cancel_inline", "Cancel", priority=True),
        Binding("slash", "filter_logs", "Filter", priority=True),
        Binding("question_mark", "toggle_help", "Help", priority=True),
        Binding("o", "cycle_sort", "Sort", priority=True),
        Binding("v", "toggle_mark", "Mark", priority=True),
        Binding("U", "bulk_delete", "Bulk Del", priority=True),
        Binding("M", "bulk_minutes", "Bulk Min", priority=True),
        Binding("T", "toggle_theme", "Theme", priority=True),

        Binding("a", "add", "Add", priority=True),
        Binding("e", "edit", "Edit", priority=True),
        Binding("x", "delete_task", "Delete Task", priority=True),
        Binding("X", "force_delete_task", "Force Delete Task", priority=True),

        # Let Input handle Enter/Space first so inline editors submit & close
        Binding("enter", "toggle_timer", "Start/Stop"),
        Binding("space", "toggle_timer", "Start/Stop"),

        Binding("up", "cursor_up", "Up", priority=True),
        Binding("down", "cursor_down", "Down", priority=True),
        Binding("k", "cursor_up", "Up", priority=True),
        Binding("j", "cursor_down", "Down", priority=True),

        # IMPORTANT: no priority so Input gets these keys while typing
        Binding("delete", "del_log", "Delete Log"),
        Binding("backspace", "del_log", "Delete Log"),
    ]

    def __init__(self, db_path: Path, rounding: str = "entry"):
        super().__init__()
        self.db_path = db_path
        self.rounding = rounding
        self.focus_where: str = "tasks"  # or "entries"
        self.compact: bool = True
        self._confirm_bulk: bool = True
        try:
            _cfg = cfgmod.load()
            self._confirm_bulk = bool((_cfg.get('confirmations') or {}).get('bulk_delete', True))
            lst = _cfg.get('list', {}) or {}
            if 'compact' in lst:
                self.compact = bool(lst.get('compact'))
        except Exception:
            pass

        self._task_row_ids: List[int] = []
        self._entry_row_ids: List[int] = []

        self._pending_task_id: Optional[int] = None
        self._pending_entry_id: Optional[int] = None
        self._temp_minutes: Optional[int] = None

        # Multi-step entry editor state
        self._edit_entry_id: Optional[int] = None
        self._edit_buf: Dict[str, Any] = {"start": None, "end": None, "minutes": None, "note": None}
        self._edit_orig: Dict[str, Any] = {"start": None, "end": None, "minutes": None, "note": None}
        self._edit_changed: Dict[str, bool] = {"start": False, "end": False, "minutes": False, "note": False}
        self._log_sort_key: str = "start"
        self._marked_entries: set[int] = set()
        self._undo: list[tuple[str, dict]] = []  # (op, details)

        # Logs filter (note contains)
        self._log_filter: str = ""

        self.status = StatusBar(HELP_TEXT, id="status")

    # -------------------- layout --------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="filterbar")
        with Horizontal(id="tables"):
            with Vertical(id="left"):
                yield Static("Tasks", id="ltitle")
                yield DataTable(id="tasks")
            with Vertical(id="right"):
                yield Static("Logs", id="rtitle")
                yield DataTable(id="entries")
        yield self.status
        yield Footer()

    def on_mount(self) -> None:
        # Build tables and initial data
        self._setup_tables()
        self.refresh_data()

        # Restore persisted UI state
        st = self._load_state()
        if st:
            self.compact = bool(st.get('compact', self.compact))
            self._log_sort_key = st.get('log_sort_key', self._log_sort_key)
            self._log_filter = st.get('log_filter', self._log_filter)

        # Apply selection and focus
        self._set_selected_task_id((st or {}).get('selected_task_id'))
        self._load_entries_for_selected()
        self._update_filter_indicator()
        self._set_selected_entry_id((st or {}).get('selected_entry_id'))
        self.focus_where = (st or {}).get('focus', self.focus_where)
        if self.focus_where == 'entries':
            try:
                self.query_one('#entries', DataTable).focus()
            except Exception:
                pass
        else:
            try:
                self.query_one('#tasks', DataTable).focus()
            except Exception:
                pass

        self.title = "ttx — Task & Time Tracker"

    def on_unmount(self) -> None:
        # Save UI state on exit
        self._save_state()
    def _setup_tables(self) -> None:
        t = self.query_one("#tasks", DataTable)
        e = self.query_one("#entries", DataTable)

        t.clear(columns=True)
        e.clear(columns=True)

        t.add_columns("ID", "Title", "Status", "Priority", "Due", "Est", "Billable", "Total")
        e.add_columns("ID", "Start", "End", "Note", "Minutes")

        try:
            t.cursor_type = "row"
            e.cursor_type = "row"
        except Exception:
            pass

        self._select_first_row(t)

    def _select_first_row(self, table: DataTable) -> None:
        if table.row_count:
            try:
                table.cursor_coordinate = (0, 0)
            except Exception:
                try:
                    table.cursor_row = 0
                except Exception:
                    pass

    # -------------------- data loading --------------------

    

    def _update_filter_indicator(self) -> None:
        try:
            fb = self.query_one("#filterbar", Static)
        except Exception:
            return
        parts = []
        if (self._log_filter or "").strip():
            parts.append(f"[b]Filter[/b]: note contains '{self._log_filter.strip()}'")
        parts.append(f"[b]Sort[/b]: {self._log_sort_key}")
        if self._marked_entries:
            parts.append(f"[b]Marked[/b]: {len(self._marked_entries)}")
        fb.update("  |  ".join(parts) if parts else "")

    def refresh_data(self) -> None:
            self._clear_inline_ui()
            self._load_tasks()
            self._load_entries_for_selected()
            self._update_filter_indicator()
    
    def _load_tasks(self) -> None:
        t = self.query_one("#tasks", DataTable)
        t.clear()
        self._task_row_ids.clear()

        rows = tasks.list_tasks(db_path=self.db_path, include_archived=False)
        totals = logs.minutes_by_task(self.db_path, rounding=self.rounding)  # {task_id: minutes}

        # Build child map from get_children() to compute true hierarchy
        try:
            from .tasks import get_children  # lazy import to avoid cycles
        except Exception:  # fallback if not available
            def get_children(_tid, db_path=None):
                return []

        rows_by_id = {r[0]: r for r in rows}
        order_ids = [r[0] for r in rows]
        child_map = {tid: [] for tid in order_ids}
        child_ids = set()
        for tid in order_ids:
            try:
                children = get_children(tid, db_path=self.db_path) or []
            except Exception:
                children = []
            for c in children:
                cid = c[0]
                child_ids.add(cid)
                child_map.setdefault(tid, []).append(cid)
                if cid not in rows_by_id:
                    # pad/normalize and store so render can use totals etc.
                    padded = tuple(c) + (None,)*(10-len(c))
                    rows_by_id[cid] = padded

        top_level_ids = [tid for tid in order_ids if tid not in child_ids]

        def render_task(tid:int, indent:str=""):
            r = rows_by_id.get(tid)
            if not r:
                return
            # Ensure tuple has 10 elements: (id, title, status, created_at, completed_at, archived_at, prio, due, est, billable)
            r = tuple(r) + (None,)*(10-len(r))
            _, title, st, _, _, _, prio, due, est, billable = r[:10]
            bill = "✓" if billable else "•"
            total = totals.get(tid, 0)
            t.add_row(str(tid), indent + title, st, str(prio or 0), due or "", f"{est or 0}", bill, f"{total}m")
            self._task_row_ids.append(int(tid))
            # Recurse children (keep their insertion order by ID ascending to be stable)
            for cid in sorted(child_map.get(tid, [])):
                render_task(cid, indent + "  ↳ ")

        for tid in top_level_ids:
            render_task(tid)

        if rows:
            try:
                t.cursor_type = "row"
            except Exception:
                pass
            self._select_first_row(t)
            self._load_entries_for_selected()
        self._update_filter_indicator()
    def _load_entries_for_selected(self) -> None:
        t = self.query_one("#tasks", DataTable)
        e = self.query_one("#entries", DataTable)
        e.clear()
        self._entry_row_ids.clear()

        task_id = self._get_selected_task_id()
        if task_id is None:
            self.query_one("#rtitle", Static).update("Logs")
            return

        total = 0
        flt = (self._log_filter or "").lower()
        rows_tmp = []
        for eid, start, end, note, minutes in logs.entries_with_durations(task_id, self.db_path):
            if flt and flt not in (note or '').lower():
                continue
            m = int(minutes or 0)
            rows_tmp.append((int(eid), start or '', end or '', note or '', m))
        # sort
        key = self._log_sort_key
        if key == 'start':
            rows_tmp.sort(key=lambda r: (r[1], r[0]))
        elif key == 'end':
            rows_tmp.sort(key=lambda r: (r[2] or '', r[0]))
        else:
            rows_tmp.sort(key=lambda r: (r[4], r[0]), reverse=True)
        for eid, start, end, note, m in rows_tmp:
            total += m
            e.add_row(str(eid), start or "", end or "", note or "", f"{m}")
            self._entry_row_ids.append(int(eid))

        if e.row_count:
            self._select_first_row(e)

        self.query_one("#rtitle", Static).update(f"Logs — total: {total}m" + (f" — filter: {self._log_filter}" if self._log_filter else ""))

    def _get_selected_task_id(self) -> Optional[int]:
        t = self.query_one("#tasks", DataTable)
        try:
            row = t.cursor_row  # type: ignore[attr-defined]
        except Exception:
            try:
                row = t.cursor_coordinate.row  # type: ignore[attr-defined]
            except Exception:
                return None
        if row is None or row < 0 or row >= len(self._task_row_ids):
            return None
        return int(self._task_row_ids[row])

    def _get_selected_entry_id(self) -> Optional[int]:
        e = self.query_one("#entries", DataTable)
        try:
            row = e.cursor_row  # type: ignore[attr-defined]
        except Exception:
            try:
                row = e.cursor_coordinate.row  # type: ignore[attr-defined]
            except Exception:
                return None
        if row is None or row < 0 or row >= len(self._entry_row_ids):
            return None
        return int(self._entry_row_ids[row])

    # -------------------- inline UI helpers --------------------

    def _clear_inline_ui(self) -> None:
        # Remove banners and any edit inputs
        for wid in list(self.query(".inline-banner").results()):
            try:
                wid.remove()
            except Exception:
                pass
        for inp in list(self.query("Input").results()):
            if getattr(inp, "classes", "") and "edit-field" in inp.classes:
                try:
                    inp.remove()
                except Exception:
                    pass

    def _show_edit_banner(self, text: str, side: str = "right", *, replace: bool = False) -> None:
        # Remove any existing banners to avoid stacking (controlled by replace)
        for wid in list(self.query(".inline-banner").results()):
            try:
                wid.remove()
            except Exception:
                pass
        mount_after = "#rtitle" if side == "right" else "#ltitle"
        after_widget = self.query_one(mount_after, Static)
        banner = Static(text, classes="inline-banner")
        self.mount(banner, after=after_widget)

    def _mount_edit_input(self, id_: str, value: str, placeholder: str, side: str = "right") -> None:
        """
        Mount (or reuse) a single-line Input for inline editing.
        - If an Input with the same id already exists, reuse it (update value/placeholder/focus).
        - If multiple exist (shouldn't happen, but can on re-prompts), remove extras.
        - Only create a new Input if none exist.
        """
        from textual.widgets import Input, Static

        mount_after = "#rtitle" if side == "right" else "#ltitle"
        after_widget = self.query_one(mount_after, Static)

        # Find matching inputs (prefer scoping to the right pane if it exists)
        try:
            right = self.query_one("#right")
            existing = list(right.query(f"Input#{id_}"))
        except Exception:
            existing = list(self.query(f"Input#{id_}"))

        if existing:
            primary = existing[0]
            # Remove duplicates
            for w in existing[1:]:
                try:
                    w.remove()
                except Exception:
                    pass
            # Reuse primary
            try:
                primary.value = value or ""
                primary.placeholder = placeholder
                if "edit-field" not in primary.classes:
                    primary.add_class("edit-field")
                primary.focus()
                return
            except Exception:
                try:
                    primary.remove()
                except Exception:
                    pass

        # Fresh mount
        inp = Input(value=(value or ""), placeholder=placeholder, id=id_, classes="edit-field")
        self.mount(inp, after=after_widget)
        try:
            self.query_one(f"#{id_}", Input).focus()
        except Exception:
            pass
    # -------------------- actions --------------------

    def action_toggle_theme(self) -> None:
        self.dark = not self.dark

    def action_cycle_sort(self) -> None:
        order = ["start", "end", "minutes"]
        try:
            idx = order.index(self._log_sort_key)
        except ValueError:
            idx = 0
        self._log_sort_key = order[(idx + 1) % len(order)]
        self.status.set_message(f"Sort by: {self._log_sort_key}")
        self._load_entries_for_selected()
        self._update_filter_indicator()

    def action_toggle_mark(self) -> None:
        e = self.query_one("#entries", DataTable)
        if not e.row_count:
            return
        row = e.cursor_row
        if row is None or row < 0:
            return
        eid = self._entry_row_ids[row]
        if eid in self._marked_entries:
            self._marked_entries.remove(eid)
            e.set_row_label(row, "")
        else:
            self._marked_entries.add(eid)
            e.set_row_label(row, "●")
        self.status.set_message(f"Marked: {len(self._marked_entries)}")
        self._update_filter_indicator()

    def action_bulk_delete(self) -> None:
        if not self._marked_entries:
            self.status.set_message("[yellow]No marked entries[/yellow]")
            return
        # Confirm
        self._show_edit_banner(f"Delete {len(self._marked_entries)} logs? type 'yes' to confirm")
        self._mount_edit_input("confirm_bulk_delete", "", "yes")

    def action_bulk_minutes(self) -> None:
        if not self._marked_entries:
            self.status.set_message("[yellow]No marked entries[/yellow]")
            return
        self._show_edit_banner(f"Adjust minutes for {len(self._marked_entries)} logs (e.g., +5, -2, 15)")
        self._mount_edit_input("bulk_minutes", "", "+/-N or N")


    def action_toggle_help(self) -> None:
        # Toggle a simple help overlay
        try:
            overlay = self.query_one("#help_overlay", Static)
            overlay.remove()
            return
        except Exception:
            pass
        text = HELP_TEXT + "\n\n[dim]Press ? again to close[/dim]"
        self.mount(Static(text, id="help_overlay", classes="overlay"))

    def action_filter_logs(self) -> None:
        if self.focus_where != "entries":
            return
        self._show_edit_banner("Filter logs: NOTE CONTAINS (empty to clear)")
        self._mount_edit_input("filter_logs", self._log_filter or "", "Note contains…")


    def action_quit(self) -> None:
        self._save_state()
        self.exit()

    def action_refresh(self) -> None:
        self.refresh_data()
        self._update_filter_indicator()

    def action_toggle_compact(self) -> None:
        self.compact = not self.compact
        self.status.set_message("[green]Toggled compact[/green]")

    def action_toggle_focus(self) -> None:
        self.focus_where = "entries" if self.focus_where == "tasks" else "tasks"
        which = "#entries" if self.focus_where == "entries" else "#tasks"
        try:
            self.query_one(which, DataTable).focus()
        except Exception:
            pass
        self.status.set_message(f"[blue]Focus:[/blue] {self.focus_where.capitalize()}")

    def action_cancel_inline(self) -> None:
        self._clear_inline_ui()
        self._edit_entry_id = None
        self._edit_buf = {"start": None, "end": None, "minutes": None, "note": None}
        self._edit_orig = {"start": None, "end": None, "minutes": None, "note": None}
        self._edit_changed = {"start": False, "end": False, "minutes": False, "note": False}
        self._temp_minutes = None
        self._pending_task_id = None
        self._pending_entry_id = None
        self.status.set_message("[yellow]Edit cancelled[/yellow]")
        # restore section title
        self._load_entries_for_selected()
        self._update_filter_indicator()

    def action_add(self) -> None:
        if self.focus_where == "tasks":
            self._action_add_task()
        else:
            self._action_add_log()

    def _action_add_task(self) -> None:
        self._clear_inline_ui()
        self._show_edit_banner("New task: TITLE", side="left")
        self._mount_edit_input("new_title", "", "Task title…", side="left")

    def _action_edit_task(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        current = tasks.get_title(int(task_id), self.db_path) or ""
        input_id = f"edit_title_{task_id}"
        self._clear_inline_ui()
        self._show_edit_banner(f"Edit task {task_id}: TITLE", side="left")
        self._mount_edit_input(input_id, current, "New title…", side="left")

    def action_delete_task(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        pid = "confirm_delete_task"
        self._clear_inline_ui()
        self._show_edit_banner(f"Delete task {task_id}: confirm", side="left")
        self._mount_edit_input(pid, "", "Type 'yes' to delete (fails if it has logs)…", side="left")
        self._pending_task_id = task_id

    def action_force_delete_task(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        pid = "confirm_force_delete_task"
        self._clear_inline_ui()
        self._show_edit_banner(f"Force delete task {task_id}: confirm", side="left")
        self._mount_edit_input(pid, "", "Type 'force' to remove task and all logs…", side="left")
        self._pending_task_id = task_id

    def action_edit(self) -> None:
        if self.focus_where == "tasks":
            self._action_edit_task()
            return

        # --- Edit a log ---
        entry_id = self._get_selected_entry_id()
        if entry_id is None:
            return

        task_id = self._get_selected_task_id()
        if task_id is None:
            return

        # Load current values to prefill
        cur = None
        for eid, start, end, note, minutes in logs.entries_with_durations(task_id, self.db_path):
            if int(eid) == int(entry_id):
                cur = (eid, start or "", end or "", note or "", int(minutes or 0))
                break
        if not cur:
            self.status.set_message("[red]Could not load entry[/red]")
            return

        eid, start, end, note, minutes = cur
        self._edit_entry_id = int(eid)
        self._edit_buf = {"start": start, "end": end, "minutes": minutes, "note": note}
        self._edit_orig = {"start": start, "end": end, "minutes": minutes, "note": note}
        self._edit_changed = {"start": False, "end": False, "minutes": False, "note": False}

        # If running (no end), allow NOTE edit only
        if not end:
            self._show_edit_banner(f"Editing entry {eid} (running): NOTE")
            self.status.set_message("Edit NOTE (optional). Press Enter to save.")
            self._mount_edit_input(
                id_=f"edit_all_note_{eid}",
                value=note,
                placeholder="Note (optional). Blank = keep",
            )
            return

        # Finished entry: prompt START first
        self._show_edit_banner(f"Editing entry {eid}: START")
        self.status.set_message("Enter a new START (YYYY-MM-DD HH:MM or ISO), or press Enter to keep.")
        self._mount_edit_input(
            id_=f"edit_start_{eid}",
            value=start,
            placeholder="Start (YYYY-MM-DD HH:MM or ISO). Blank = keep",
        )

    def action_del_log(self) -> None:
        # SAFETY: don't delete when user is typing in an Input
        try:
            if isinstance(self.focused, Input):
                return
        except Exception:
            pass
        if self.focus_where != "entries":
            return
        entry_id = self._get_selected_entry_id()
        if entry_id is None:
            return
        try:
            logs.delete_entry(entry_id, self.db_path)
            self.status.set_message(f"[red]Deleted log[/red] {entry_id}")
            self.refresh_data()
        except Exception as e:
            self.status.set_message(f"[red]{e}[/red]")

    def action_toggle_timer(self) -> None:
        # Do not steal Enter from active Input
        try:
            if isinstance(self.focused, Input):
                return
        except Exception:
            pass

        if self.focus_where != "tasks":
            return
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        running = logs.current_running(self.db_path)  # e.g., (entry_id, task_id)
        if running and running[1] == task_id:
            try:
                logs.stop(db_path=self.db_path)
                self.status.set_message(f"[yellow]Stopped[/yellow] task {task_id}")
            except Exception as e:
                self.status.set_message(f"[red]{e}[/red]")
        else:
            if running:
                try:
                    logs.stop(db_path=self.db_path)
                except Exception:
                    pass
            try:
                logs.start(task_id, self.db_path)
                self.status.set_message(f"[green]Started[/green] task {task_id}")
            except Exception as e:
                self.status.set_message(f"[red]{e}[/red]")
        self.refresh_data()

    def action_stop_timer(self) -> None:
        try:
            logs.stop(db_path=self.db_path)
            self.refresh_data()
        except Exception as e:
            self.status.set_message(f"[red]{e}[/red]")

    def action_cursor_up(self) -> None:
        table = self.query_one("#tasks" if self.focus_where == "tasks" else "#entries", DataTable)
        try:
            table.action_cursor_up()
        except Exception:
            try:
                table.cursor_row = max(0, (self._cursor_row(table) - 1))
            except Exception:
                pass
        if self.focus_where == "tasks":
            self._load_entries_for_selected()
        self._update_filter_indicator()

    def action_cursor_down(self) -> None:
        table = self.query_one("#tasks" if self.focus_where == "tasks" else "#entries", DataTable)
        try:
            table.action_cursor_down()
        except Exception:
            try:
                table.cursor_row = min(max(0, table.row_count - 1), self._cursor_row(table) + 1)
            except Exception:
                pass
        if self.focus_where == "tasks":
            self._load_entries_for_selected()
        self._update_filter_indicator()

    def _cursor_row(self, table: DataTable) -> int:
        try:
            return int(table.cursor_row or 0)
        except Exception:
            try:
                return int(table.cursor_coordinate.row or 0)
            except Exception:
                return 0

    # -------------------- helpers --------------------

    def _parse_minutes(self, txt: str) -> Optional[int]:
        if not txt:
            return None
        try:
            if "h" in txt or "m" in txt or "d" in txt or ":" in txt:
                return logs._parse_duration_to_minutes(txt)  # uses your parser
            return int(txt)
        except Exception:
            return None

    def _action_add_log(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        self._clear_inline_ui()
        self._show_edit_banner("Add manual log: MINUTES")
        self._mount_edit_input("add_minutes", "", "Minutes (e.g. 25 or 1h15m or 2:30)…")

    # -------------------- table events (broad Textual compat) --------------------

    def on_data_table_cursor_moved(self, event) -> None:
        sender = getattr(event, "sender", None) or getattr(event, "data_table", None)
        if getattr(sender, "id", "") == "tasks":
            self._load_entries_for_selected()
        self._update_filter_indicator()

    def on_data_table_row_highlighted(self, event) -> None:
        sender = getattr(event, "sender", None) or getattr(event, "data_table", None)
        if getattr(sender, "id", "") == "tasks":
            self._load_entries_for_selected()
        self._update_filter_indicator()

    # -------------------- input submissions --------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        ctrl = event.input
        cid = ctrl.id or ""

        # ----- Confirm bulk delete -----
        if cid == "confirm_bulk_delete":
            ok = (ctrl.value or '').strip().lower() == 'yes'
            ctrl.remove()
            if not ok:
                self.status.set_message('[yellow]Cancelled[/yellow]')
                return
            # perform delete
            count = 0
            for eid in list(self._marked_entries):
                try:
                    logs.delete_entry(eid, self.db_path)
                    count += 1
                except Exception:
                    pass
                self._marked_entries.discard(eid)
            self.status.set_message(f'[green]Deleted {count} logs[/green]')
            self._load_entries_for_selected()
            self._update_filter_indicator()
            return

        # ----- Bulk minutes -----
        if cid == "bulk_minutes":
            delta = (ctrl.value or '').strip()
            ctrl.remove()
            if not delta:
                self.status.set_message('[yellow]Cancelled[/yellow]')
                return
            adj = 0
            try:
                if delta.startswith(('+','-')):
                    adj = int(delta)
                else:
                    adj = int(delta)  # absolute set
            except Exception:
                self.status.set_message('[red]Invalid number[/red]')
                return
            count = 0
            for eid in list(self._marked_entries):
                try:
                    row = logs.get_entry(eid, self.db_path)
                    minutes = int(row[4] or 0)
                    newm = max(0, minutes + adj) if delta.startswith(('+','-')) else max(0, int(delta))
                    logs.edit_entry(eid, db_path=self.db_path, minutes=newm)
                    count += 1
                except Exception:
                    pass
            self.status.set_message(f'[green]Updated {count} logs[/green]')
            self._load_entries_for_selected()
            self._update_filter_indicator()
            return

        # ----- Filter logs -----
        if cid == "filter_logs":
            self._log_filter = (ctrl.value or "").strip()
            ctrl.remove()
            if self._log_filter:
                self.status.set_message(f"[blue]Filter:[/blue] {self._log_filter}")
            else:
                self.status.set_message("[yellow]Filter cleared[/yellow]")
            self._load_entries_for_selected()
            self._update_filter_indicator()
            return

        # ----- Add task -----
        if cid == "new_title":
            title = ctrl.value.strip()
            ctrl.remove()
            if title:
                try:
                    tasks.add(title, self.db_path)
                    self.status.set_message(f"Added: {title}")
                    self.refresh_data()
                except Exception as e:
                    self.status.set_message(f"[red]{e}[/red]")
            else:
                self.status.set_message("[yellow]Empty title ignored[/yellow]")
            return

        # ----- Edit task title -----
        if cid.startswith("edit_title_"):
            sid = cid.removeprefix("edit_title_")
            ctrl.remove()
            try:
                task_id = int(sid)
            except ValueError:
                return
            title = ctrl.value.strip()
            if not title:
                self.status.set_message("[yellow]Empty title ignored[/yellow]")
                return
            try:
                tasks.edit_title(task_id, title, self.db_path)
                self.status.set_message(f"[green]Renamed[/green] task {task_id}")
                self.refresh_data()
            except Exception as e:
                self.status.set_message(f"[red]{e}[/red]")
            return

        # ----- Delete task (confirm) -----
        if cid == "confirm_delete_task":
            value = ctrl.value.strip().lower()
            ctrl.remove()
            task_id = self._pending_task_id
            self._pending_task_id = None
            if task_id is None:
                return
            if value != "yes":
                self.status.set_message("[yellow]Delete cancelled[/yellow]")
                return
            try:
                tasks.delete_task(task_id, self.db_path, force=False)
                self.status.set_message(f"[red]Deleted task[/red] {task_id}")
                self.refresh_data()
            except Exception as e:
                self.status.set_message(f"[red]{e}[/red]")
            return

        # ----- Force delete task (confirm) -----
        if cid == "confirm_force_delete_task":
            value = ctrl.value.strip().lower()
            ctrl.remove()
            task_id = self._pending_task_id
            self._pending_task_id = None
            if task_id is None:
                return
            if value != "force":
                self.status.set_message("[yellow]Force delete cancelled[/yellow]")
                return
            try:
                tasks.delete_task(task_id, self.db_path, force=True)
                self.status.set_message(f"[red]Force deleted task[/red] {task_id}")
                self.refresh_data()
            except Exception as e:
                self.status.set_message(f"[red]{e}[/red]")
            return

        # ----- Add manual log: minutes then note -----
        if cid == "add_minutes":
            minutes = self._parse_minutes(ctrl.value.strip())
            ctrl.remove()
            if minutes is None or minutes <= 0:
                self.status.set_message("[red]Invalid minutes[/red]")
                # re-open minutes prompt for clarity
                self._show_edit_banner("Add manual log: MINUTES")
                self._mount_edit_input("add_minutes", "", "Minutes (e.g. 25 or 1h15m or 2:30)…")
                return
            self._temp_minutes = minutes
            self._show_edit_banner("Add manual log: NOTE")
            self.status.set_message("Optional note. Press Enter to save.")
            self._mount_edit_input("add_note", "", "Note (optional). Enter to save…")
            return

        if cid == "add_note":
            note = ctrl.value.strip()
            ctrl.remove()
            minutes = self._temp_minutes or 0
            self._temp_minutes = None
            task_id = self._get_selected_task_id()
            if task_id is None:
                return
            try:
                logs.add_manual_entry(task_id, self.db_path, minutes=minutes, note=note or None)
                self.status.set_message(f"[green]Added[/green] {minutes}m")
                self.refresh_data()
            except Exception as e:
                self.status.set_message(f"[red]{e}[/red]")
            return

        # ----- Edit existing log: START submitted -----
        if cid.startswith("edit_start_"):
            eid_str = cid.removeprefix("edit_start_")
            ctrl.remove()
            try:
                eid = int(eid_str)
            except ValueError:
                return
            if self._edit_entry_id != eid:
                return
            val = ctrl.value.strip()
            if val and val != (self._edit_orig.get("start") or ""):
                self._edit_buf["start"] = val
                self._edit_changed["start"] = True

            # Prompt END
            self._show_edit_banner(f"Editing entry {eid}: END")
            self.status.set_message("Enter a new END (YYYY-MM-DD HH:MM or ISO), or press Enter to keep.")
            current = self._edit_buf.get("end") or ""
            self._mount_edit_input(
                id_=f"edit_end_{eid}",
                value=current,
                placeholder="End (YYYY-MM-DD HH:MM or ISO). Blank = keep",
            )
            return

        # ----- Edit existing log: END submitted -----
        if cid.startswith("edit_end_"):
            eid_str = cid.removeprefix("edit_end_")
            ctrl.remove()
            try:
                eid = int(eid_str)
            except ValueError:
                return
            if self._edit_entry_id != eid:
                return
            val = ctrl.value.strip()
            if val and val != (self._edit_orig.get("end") or ""):
                self._edit_buf["end"] = val
                self._edit_changed["end"] = True

            # Prompt MINUTES
            self._show_edit_banner(f"Editing entry {eid}: MINUTES", replace=True)
            self.status.set_message("Enter new MINUTES (e.g. 25 / 1h15m / 2:30), or press Enter to keep.")
            current_minutes = self._edit_buf.get("minutes")
            self._mount_edit_input(
                id_=f"edit_all_minutes_{eid}",
                value=str(current_minutes or ""),
                placeholder="Minutes (e.g. 25 / 1h15m / 2:30). Blank = keep",
            )
            return

        # ----- Edit existing log: MINUTES submitted -----
        if cid.startswith("edit_all_minutes_"):
            eid_str = cid.removeprefix("edit_all_minutes_")
            mv = ctrl.value.strip()
            ctrl.remove()
            try:
                eid = int(eid_str)
            except ValueError:
                return
            if self._edit_entry_id != eid:
                return
            if mv:
                pm = self._parse_minutes(mv)
                if pm is None or pm <= 0:
                    self.status.set_message("[red]Invalid minutes[/red]")
                    # re-open minutes prompt with banner
                    self._show_edit_banner(f"Editing entry {eid}: MINUTES", replace=True)
                    self._mount_edit_input(
                        id_=f"edit_all_minutes_{eid}",
                        value=(mv or ""),
                        placeholder="Minutes (e.g. 25 / 1h15m / 2:30). Blank = keep",
                    )
                    return
                if pm != (self._edit_orig.get("minutes") or 0):
                    self._edit_buf["minutes"] = pm
                    self._edit_changed["minutes"] = True

            # Prompt NOTE
            self._show_edit_banner(f"Editing entry {eid}: NOTE")
            self.status.set_message("Edit NOTE (optional). Press Enter to keep current or finish.")
            current_note = self._edit_buf.get("note") or ""
            self._mount_edit_input(
                id_=f"edit_all_note_{eid}",
                value=current_note,
                placeholder="Note (optional). Blank = keep",
            )
            return

        # ----- Edit existing log: NOTE submitted (apply) -----
        if cid.startswith("edit_all_note_"):
            eid_str = cid.removeprefix("edit_all_note_")
            nv = ctrl.value  # may be empty -> keep
            ctrl.remove()
            try:
                eid = int(eid_str)
            except ValueError:
                return
            if self._edit_entry_id != eid:
                return

            if nv != "" and nv != (self._edit_orig.get("note") or ""):
                self._edit_buf["note"] = nv
                self._edit_changed["note"] = True

            # APPLY CHANGES
            applied_any = False
            errors: List[str] = []

            # 1) Trim start/end first (finished entries only)
            orig_end = self._edit_orig.get("end") or ""
            if orig_end:  # finished
                new_start = self._edit_buf.get("start") if self._edit_changed["start"] else None
                new_end = self._edit_buf.get("end") if self._edit_changed["end"] else None
                if new_start or new_end:
                    try:
                        logs.trim_entry(eid, new_start, new_end, self.db_path)
                        applied_any = True
                    except Exception as e:
                        errors.append(str(e))

            # 2) Minutes / note using edit_entry
            #    - If END was set explicitly, ignore minutes (END takes precedence).
            apply_minutes = self._edit_changed["minutes"] and not self._edit_changed["end"] and (self._edit_orig.get("end") or "")
            kwargs: Dict[str, Any] = {}
            if apply_minutes:
                kwargs["minutes"] = self._edit_buf.get("minutes")
            if self._edit_changed["note"]:
                kwargs["note"] = self._edit_buf.get("note")

            if kwargs:
                try:
                    logs.edit_entry(eid, db_path=self.db_path, **kwargs)
                    applied_any = True
                except Exception as e:
                    errors.append(str(e))

            if applied_any and not errors:
                self.status.set_message(f"[green]Updated[/green] entry {eid}")
            elif not applied_any and not errors:
                self.status.set_message("[yellow]No changes[/yellow]")
            else:
                self.status.set_message(f"[red]{'; '.join(errors)}[/red]")

            # cleanup
            self._edit_entry_id = None
            self._edit_buf = {"start": None, "end": None, "minutes": None, "note": None}
            self._edit_orig = {"start": None, "end": None, "minutes": None, "note": None}
            self._edit_changed = {"start": False, "end": False, "minutes": False, "note": False}
            self.refresh_data()
            return


def run_tui(db_path: Path, rounding: str = "entry"):
    app = TTApp(db_path=db_path, rounding=rounding)
    app.run()

# Suggested CSS for styling consistency:
# .help { background: $surface; color: $text; padding: 1; dock: bottom; }