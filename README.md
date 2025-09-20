# tt — Tiny Tasks + Time Tracker

[![Release](https://github.com/martindahlswe/tt/actions/workflows/release.yml/badge.svg)](https://github.com/martindahlswe/tt/actions/workflows/release.yml)
[![PyPI version](https://img.shields.io/pypi/v/tt.svg)](https://pypi.org/project/tt/)
[![PyPI downloads](https://img.shields.io/pypi/dm/tt)](https://pypi.org/project/tt/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Author:** [Martin Dahl](https://github.com/martindahlswe)

---

`tt` is a lightweight, terminal-first **task & time tracking** tool with both a **CLI** and an interactive **TUI**.  
It’s designed for speed, simplicity, and scriptability — with sensible defaults and flexible time parsing.

---

## ✨ Features

- **Tasks**: add, list, complete, archive.
- **Time logs**:
  - Start/stop timers
  - Manual entries (`--start/--end`, `--minutes`, `--ago`)
  - Flexible parsing (`09:00`, `:30`, `1h15`, `today`, `yesterday`, `now`)
  - Strict ISO mode (optional)
- **Reports & exports**:
  - Summaries by task, tag, or day
  - CSV and Markdown export
- **Interactive TUI** (powered by [Textual](https://github.com/Textualize/textual)):
  - Task + log views
  - Filter indicator bar
  - Entry marking, bulk actions, sorting
  - Persisted UI state
- **Configurable**:
  - XDG-compliant config (`~/.config/tt/config.yml`)
  - Rounding rules
  - Confirmation prompts for destructive ops
- **SQLite backend**:
  - WAL mode enabled
  - Auto-created indexes
- **Developer-friendly**:
  - Semantic-release CI (auto changelog + versioning)
  - Conventional Commits
  - PyPI-ready packaging

---

## 📦 Installation

### From GitHub (editable dev install)

```bash
git clone https://github.com/martindahlswe/tt.git
cd tt
pip install -e .
```

Now you can run:

```bash
tt --help
```

### From GitHub directly (pip)

```bash
pip install "git+https://github.com/martindahlswe/tt.git@main#egg=tt"
```

### From PyPI (once published)

```bash
pip install tt
```

---

## 🚀 Usage

### CLI examples

```bash
# Initialize DB
tt init

# Add a task and list tasks
tt task add "Finances"
tt task ls

# Start and stop a timer
tt start 1
tt stop

# Add a manual log
tt log add 1 --start "09:00" --end "10:15"
tt log add 1 --minutes 30
tt log add 1 --ago 1h15

# Show logs
tt log ls --all --week

# Generate a report
tt report --group day --since week

# Open TUI
tt tui
```

### TUI keybindings

- `↑ / ↓ / Tab` — navigate
- `Enter` — open details
- `M` — mark entry
- `D` — bulk delete marked
- `+ / -` — adjust minutes
- `?` — help overlay
- `T` — toggle theme

---

## ⚙️ Configuration

Config file lives at:

- Linux/macOS: `~/.config/tt/config.yml`

Example:

```yaml
rounding:
  minutes: 15
input:
  strict_iso: false
confirmations:
  bulk_delete: true
```

---

## 🛠 Development

### Run tests

```bash
pytest
```

### Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/).  
Examples:

```
feat(cli): add tt examples command
fix(tui): guard _save_state when widgets are unmounted
feat!: drop pomodoro feature (breaking)
```

### Release flow

- Merge to `main` with proper commit messages
- [semantic-release](https://python-semantic-release.readthedocs.io/) bumps version, updates changelog, creates GitHub Release

---

## 📄 License

MIT © [Martin Dahl](https://github.com/martindahlswe)

---

## 📌 Links

- Repo: [https://github.com/martindahlswe/tt](https://github.com/martindahlswe/tt)
- Issues: [https://github.com/martindahlswe/tt/issues](https://github.com/martindahlswe/tt/issues)
