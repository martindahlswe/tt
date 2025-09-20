# tt/errors.py
from __future__ import annotations

class AppError(Exception):
    """Base for user-facing errors. Message should be human-readable."""
    exit_code = 1
    def __init__(self, message: str, *, details: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:  # pragma: no cover
        return self.message

class BadInput(AppError):
    """User entered something invalid (bad flag, bad time range, etc.)."""
    exit_code = 2

class NotFound(AppError):
    """Resource doesn't exist (task / entry / tag)."""
    exit_code = 3

class Conflict(AppError):
    """Valid, but conflicts with current state (e.g., already running)."""
    exit_code = 4

class StateError(AppError):
    """Operation not allowed in current state (e.g., editing a running entry)."""
    exit_code = 5

class ConfigError(AppError):
    """Bad/missing config."""
    exit_code = 6

class DbError(AppError):
    """Database / migration trouble."""
    exit_code = 7
