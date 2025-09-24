# CHANGELOG


## v1.2.0 (2025-09-24)

### Features

- **cli**: Add `task add-subtask` command
  ([`df2f337`](https://github.com/martindahlswe/ttx-cli/commit/df2f337e39fcc7e12ac6e731c2defe2cb9822f3c))

- Introduced new subcommand `ttx task add-subtask` - Usage: `ttx task add-subtask <PARENT_ID>
  "<TITLE>"` - Validates that the parent task exists before creating the subtask - Calls
  `tasks.add(..., parent_id=...)` to persist relation - Prints confirmation with both new subtask ID
  and parent ID

This restores explicit subtask creation via CLI while keeping existing `task add` intact.

- **cli**: Add `task tree` command to show nested tasks with logs
  ([`99b3a6c`](https://github.com/martindahlswe/ttx-cli/commit/99b3a6c4c3c2a5058ec3236160cad8e4e33ad257))

- Introduced new `ttx task tree` command - Displays tasks and subtasks in a hierarchical tree -
  Preserves same columns as `task ls` - Includes per-entry log lines when not in `--compact` mode -
  Supports same filters and options as `task ls` - Builds child map to nest subtasks under parents -
  Keeps existing `task ls` behavior unchanged - Removes deprecated `task add-subtask` (subtasks are
  created via `task add --parent-id`)

This provides a unified way to explore tasks, subtasks, and their logs in the CLI.

- **tasks**: Add support for hierarchical subtasks in CLI and TUI
  ([`371365d`](https://github.com/martindahlswe/ttx-cli/commit/371365d944a4d41780b2c21fa32e8a25700b29c6))

- Extend database schema with `parent_id` column on `tasks` table - Added migration helper
  `apply_migrations()` - Ensure `parent_id` is created if missing - Update task creation to support
  optional `parent_id` argument - Add `list_subtasks()` and `get_children()` helpers in `tasks.py` -
  Enhance `task ls` CLI command: - New `--parent-id` option to show subtasks of a given task -
  Default view now nests subtasks visually with indentation - Update TUI task list rendering: -
  Build child map and recurse to render subtasks with indentation - Show subtasks directly beneath
  their parents - Add utility `format_minutes()` to `timeparse.py` - Ensure schema/migrations run
  safely on connect/init

This commit introduces proper hierarchical task management while preserving backward compatibility.


## v1.1.1 (2025-09-23)

### Bug Fixes

- **ci**: Align pyproject.toml versioning with semantic-release
  ([`e09781c`](https://github.com/martindahlswe/ttx-cli/commit/e09781ca41626dcc0f5ba8f087ae6d60616bb77f))

### Chores

- **build**: Configure hatch-vcs for dynamic version without bump
  ([`47e283a`](https://github.com/martindahlswe/ttx-cli/commit/47e283ae9ea56a0afd36b51d5b534c506a5a692a))


## v1.1.0 (2025-09-23)

### Bug Fixes

- Added pyproject dependencies.
  ([`bf00e33`](https://github.com/martindahlswe/ttx-cli/commit/bf00e332397276bcf2a9e922b45b8ddd14708d30))

- **ci**: Align pyproject.toml versioning with semantic-release
  ([`2e09390`](https://github.com/martindahlswe/ttx-cli/commit/2e09390fdd64cd592e017870cc9a340bdeb8313b))

Remove hardcoded version from pyproject.toml and switch to dynamic version management to avoid
  mismatches between GitHub and PyPI releases. Ensures semantic-release controls version
  consistently.

### Continuous Integration

- **release**: Improve GitHub Actions workflow for semantic-release & PyPI
  ([`7af274a`](https://github.com/martindahlswe/ttx-cli/commit/7af274a41e45364f49daae3514abbb1043ba98ce))

- Switch to official python-semantic-release action for reliable release detection - Only build &
  publish when a release is actually created - Add pip caching for faster runs - Add concurrency
  control to prevent overlapping release jobs - Keep minimal permissions (contents + id-token)

This makes the release pipeline more efficient, safer, and avoids unnecessary PyPI uploads.

### Features

- **cli**: Improve error handling and messaging across commands
  ([`c7c20ca`](https://github.com/martindahlswe/ttx-cli/commit/c7c20cab649167c3f719b881c0823d2dc3c948b7))

- **tui**: Improve inline editing and error handling for log entries
  ([`33fdcf9`](https://github.com/martindahlswe/ttx-cli/commit/33fdcf98c499a53373baaf022e2cb4974e6ec598))

- Added smarter handling of inline edit inputs to avoid DuplicateIds crashes when editing logs
  without descriptions or re-submitting edits. - Enhanced `_mount_edit_input` to reuse or clean up
  existing input widgets instead of blindly mounting new ones. - Extended `_show_edit_banner` with a
  `replace` option to prevent banner stacking during repeated prompts. - Fixed error handling around
  editing minutes: ensures consistent behavior with inputs like `20m`, `25`, or `1h15m`. - Cleaned
  up task refresh logic while preserving selection consistency.

This improves stability and UX in the TUI editor. bump: minor


## v1.0.3 (2025-09-21)

### Bug Fixes

- Make sure selected task keeps being selected while modiyfing logs.
  ([`ad71ae0`](https://github.com/martindahlswe/ttx-cli/commit/ad71ae0e665d9fb937f82ef9f13f324be7f7f60a))


## v1.0.2 (2025-09-21)

### Bug Fixes

- Restore missing time entry APIs and CLI integration
  ([`10e0bcc`](https://github.com/martindahlswe/ttx-cli/commit/10e0bcc6d152ad165308fd4b042968360b559e1c))

- Reimplemented core time tracking functions in time_entries.py: - add start(), stop(), and
  current_running() - added _parse_ago() to support `--ago` option for manual log entries - Fixed
  task listing in cli.py: - ensure entries_map always holds lists of (note, minutes) tuples -
  Updated TUI integration: - restored current_running import and usage - Verified no regressions
  across CLI (task, log, report, export) and TUI flows

- **ci**: Ensure semantic-release updates pyproject.toml before build
  ([`47bd92e`](https://github.com/martindahlswe/ttx-cli/commit/47bd92e483fed3d5cbc9d9359754d3898f1807a7))

- **ci**: Ensure semantic-release updates pyproject.toml before build
  ([`db121e4`](https://github.com/martindahlswe/ttx-cli/commit/db121e426d8b6830f4afdbccd57bab519ab6347b))

- **cli**: Improve task listing table rendering and entries_map handling
  ([`640b510`](https://github.com/martindahlswe/ttx-cli/commit/640b510b3b1a0a603b47a7acc81dd0864976b9ae))

- Fixed incorrect indentation in `_print_tasks_table`, which previously caused runtime errors when
  displaying tasks with tags and per-entry bullets. - Updated logic to handle both `list` and `int`
  values in `entries_map`: - Lists are treated as (note, minutes) tuples and displayed as bullets. -
  Integers are treated as a total minutes value and rendered in a summary row. - Ensured
  `console.print(table)` is correctly scoped and avoids NameError. - Improved code readability and
  maintainability without breaking features.


## v1.0.1 (2025-09-21)

### Bug Fixes

- **ci**: Ensure release workflow updates pyproject.toml before build
  ([`bf901f4`](https://github.com/martindahlswe/ttx-cli/commit/bf901f443484ea55eff53032599639347ff27d95))


## v1.0.0 (2025-09-21)

### Chores

- **ci**: Fix release workflow to sync PyPI with GitHub version
  ([`b4fff5b`](https://github.com/martindahlswe/ttx-cli/commit/b4fff5bbb6dcb39614520da0c3051838c725c89b))

Ensure semantic-release bumps pyproject.toml before building so that the published package version
  matches the GitHub release (1.0.0).

- **ci**: Update release workflow and requirement
  ([`7a9def7`](https://github.com/martindahlswe/ttx-cli/commit/7a9def7ca3ce5814502bc7a3cf611719f9eabdbd))

### Features

- Rename project to ttx-cli and update release workflow
  ([`3ffeb49`](https://github.com/martindahlswe/ttx-cli/commit/3ffeb4978706cad225f66030e216ee3b4f325353))

- Rename project from **tt** → **ttx-cli** - CLI command is now `ttx` instead of `tt` - Update
  README.md and CHANGELOG.md to reflect new name - Update config path to `~/.config/ttx/config.yml`
  - Update GitHub repo/issue links to `martindahlswe/ttx-cli` - Simplify and modernize
  pyproject.toml - New project metadata (author, license, description, dependencies) - Define
  [project.scripts] ttx = "ttx.cli:app" - Use Hatch for build configuration - Remove old `tt/`
  package (replaced by `ttx/`) - Update GitHub Actions workflow - Install required tools (hatchling,
  build, twine, python-semantic-release) - Replace action step with direct `semantic-release`
  commands - Add PyPI publishing support with `PYPI_API_TOKEN`

BREAKING CHANGE: The CLI command has changed from `tt` to `ttx`.

### Breaking Changes

- The CLI command has changed from `tt` to `ttx`.
