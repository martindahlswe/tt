# tt/__init__.py
__all__ = []

try:
    from importlib.metadata import version as _dist_version
    __version__ = _dist_version("tt")
except Exception:
    # Fallback during editable installs or if metadata is unavailable
    __version__ = "0.0.0"
