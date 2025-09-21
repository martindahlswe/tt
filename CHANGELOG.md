# CHANGELOG


## v1.0.0 (2025-09-20)

### Features

- Major UX & infra improvements, remove pomodoro
  ([`eab0f3f`](https://github.com/martindahlswe/tt/commit/eab0f3f746837c3376baec7c4365f440f09ff248))

CLI: - Added `ttx examples` command with real working examples - Improved top-level help/UX and
  version flag - Added `ttx config` subcommands: validate, path, edit - Log listing now supports
  `--today`, `--week`, `--running`, CSV/JSON output refinements - Removed Pomodoro commands

Config: - Switched to XDG-compliant config path (`~/.config/tt/config.yml`) - Added helpers to
  create, save, and migrate legacy configs - Support bulk-delete confirmations toggle via config

Time parsing & durations: - Centralized datetime parsing with strict ISO toggle - Added shorthand
  support (`:30`, `1h15`, `yesterday`, `today`) - Unified across CLI/TUI/log parsing

TUI: - Added filter indicator bar and sort cycling - Implemented entry marking, bulk delete, bulk
  minutes adjust - Persist focus, filter, and selection across sessions - Added help overlay (`?`)
  and theme toggle (`T`)

DB: - Enabled WAL mode and created helpful indexes automatically

Project infra: - Added semantic-release CI configs for automated changelog & versioning - Updated
  `__init__.py` to derive version from installed dist - Simplified README and CONTRIBUTING guides

BREAKING CHANGE: removed Pomodoro feature and commands

### Breaking Changes

- Removed Pomodoro feature and commands
