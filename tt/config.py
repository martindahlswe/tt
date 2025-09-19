# tt/config.py
"""
Load YAML config and env overrides.

Config precedence (low → high):
  1) Defaults in code
  2) YAML file: ~/.tt.yml or ~/.tt.yaml
  3) Environment variables: TT_DB, TT_ROUNDING

Example ~/.tt.yml:
  db: /home/me/tt.sqlite3
  rounding: entry         # or "overall"
  default_status: todo
  list:
    compact: false
    limit: 50
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "rounding": "entry",   # "entry" (sum per-entry rounded minutes) or "overall"
    "default_status": None,
    "list": {"compact": False, "limit": None},
}

def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    try:
        if path.exists():
            return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}
    return {}

def load() -> Dict[str, Any]:
    cfg = DEFAULTS.copy()
    home = Path.home()
    for fname in (".tt.yml", ".tt.yaml"):
        cfg_path = home / fname
        data = _read_yaml(cfg_path)
        if data:
            # deep merge for 'list' subdict
            cfg.update({k: v for k, v in data.items() if k != "list"})
            if "list" in data:
                cfg["list"] = {**cfg.get("list", {}), **(data["list"] or {})}
            break

    # env overrides
    if os.getenv("TT_ROUNDING"):
        cfg["rounding"] = os.getenv("TT_ROUNDING").strip().lower()
    if os.getenv("TT_DB"):
        cfg["db"] = os.getenv("TT_DB").strip()

    return cfg
