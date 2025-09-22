"""
Centralized error types for ttx.

This module defines a small hierarchy of exceptions to keep user-facing
messages clean and enable precise handling in CLI/TUI and services.

These classes are safe to adopt incrementally. They do not change behavior
by themselves; raising them instead of generic exceptions simply makes
catch/handle and messaging clearer.

Public API (stable):
- TTXError (base)
- ValidationError
- DatabaseError
- ConfigError
- TaskNotFoundError
- EntryNotFoundError
- PluginError

Notes:
- All exceptions are regular Python Exceptions; no dependency on Rich/Typer.
- __str__ messages are concise and human-friendly.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


class TTXError(Exception):
    """Base class for ttx-specific errors."""
    default_message = "An unexpected error occurred."

    def __init__(self, message: Optional[str] = None):
        super().__init__(message or self.default_message)

    def __str__(self) -> str:
        return super().__str__()


class ValidationError(TTXError):
    """Invalid user input or option combinations (CLI/TUI/domain)."""
    default_message = "Invalid input."


class DatabaseError(TTXError):
    """Database connection, schema, or migration issues."""
    default_message = "Database error."

    def __init__(self, message: Optional[str] = None, *, path: Optional[str] = None):
        self.path = path
        if message is None and path:
            message = f"Database error at {path}"
        super().__init__(message)


class ConfigError(TTXError):
    """Configuration file or environment issues."""
    default_message = "Configuration error."


@dataclass(frozen=True)
class TaskNotFoundError(TTXError):
    """Raised when a task id cannot be found."""
    task_id: int

    def __init__(self, task_id: int, message: Optional[str] = None):
        object.__setattr__(self, "task_id", task_id)  # keep dataclass frozen
        super().__init__(message or f"Task with ID {task_id} not found.")


@dataclass(frozen=True)
class EntryNotFoundError(TTXError):
    """Raised when a time entry id cannot be found."""
    entry_id: int

    def __init__(self, entry_id: int, message: Optional[str] = None):
        object.__setattr__(self, "entry_id", entry_id)  # keep dataclass frozen
        super().__init__(message or f"Time entry with ID {entry_id} not found.")


class PluginError(TTXError):
    """Plugin lifecycle or capability issues (future-proof)."""
    default_message = "Plugin error."


__all__ = [
    "TTXError",
    "ValidationError",
    "DatabaseError",
    "ConfigError",
    "TaskNotFoundError",
    "EntryNotFoundError",
    "PluginError",
]
