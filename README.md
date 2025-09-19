# TT — CLI & TUI Task + Time Tracker

Lightweight task + time tracking with a fast CLI and a Textual TUI.

- ⌨️ **CLI** for scripts and quick ops
- 🖥️ **TUI** powered by [Textual] for a nice keyboard-first UI
- 🗃️ SQLite backend, zero external services
- 🧩 Extensible (calendar import planned)

## Install

```bash
# recommended
pipx install tt-productivity

# or via pip in a venv
pip install tt-productivity
```

> Dev install (editable):
```bash
git clone https://github.com/martindahl/tt.git
cd tt
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

```bash
# run TUI
python -m tt.cli tui
# or, if installed as console script
tt tui

# add a task
tt add "Write README"

# start / stop timer
tt start 1
tt stop
```

### TUI keys (highlights)

- `Tab` switch focus (Tasks ↔ Logs)
- `a` add (task/log depending on focus)
- `e` edit (task title or **log: Start → End → Minutes → Note**)
- `Enter` submits inline inputs (input closes)
- `Esc` cancels inline edit
- `Backspace/Delete` delete selected log **only when not typing**
- `Space/Enter` start/stop timer on selected task (when Tasks focused)
- `S` stop timer globally
- `x` / `X` delete / force delete task

## Config / data

- DB: stored in `tt.db` by default (see `tt/db.py`)
- Rounding: `--rounding entry|session` (if supported by your CLI)

## Roadmap

- Calendar import (macOS EventKit, Google, CalDAV)
- Export reports (CSV/Markdown)
- Tags browser in TUI

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md). We use Ruff + Black + MyPy + PyTest.
