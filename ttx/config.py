# tt/config.py
"""
XDG-compliant config loader & creator for TT.

Config precedence (low → high):
  1) Defaults in code
  2) XDG config file: $XDG_CONFIG_HOME/tt/config.yml  (fallback: ~/.config/tt/config.yml)
     (Legacy fallback supported: ~/.tt.yml or ~/.tt.yaml)
  3) Environment variables: TT_DB, TT_ROUNDING

Example config.yml:
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

# -------- defaults (note: title is intentionally NOT configurable) --------
DEFAULTS: Dict[str, Any] = {
    "rounding": "entry",            # "entry" (sum per-entry rounded minutes) or "overall"
    "default_status": None,
    "list": {"compact": False, "limit": None},
    # You may add "db" here if you want a default path baked into the file,
    # but we also support setting it via env TT_DB or elsewhere in code.
}

# -------- XDG paths --------
def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

def config_path() -> Path:
    """Preferred XDG config path."""
    return _xdg_config_home() / "tt" / "config.yml"

def legacy_paths() -> list[Path]:
    home = Path.home()
    return [home / ".tt.yml", home / ".tt.yaml"]

# -------- YAML helpers --------
def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception:
        # YAML not available; behave as before (empty config), but warn
        print(f"[ttx:config] Warning: PyYAML not available; ignoring {path}", file=sys.stderr)
        return {}
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            data = (yaml.safe_load(text) or {})
            if not isinstance(data, dict):
                print(f"[ttx:config] Warning: {path} does not contain a mapping (ignoring)", file=sys.stderr)
                return {}
            return data
    except yaml.YAMLError as e:  # type: ignore
        print(f"[ttx:config] Warning: invalid YAML in {path}: {e}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"[ttx:config] Warning: error reading {path}: {e}", file=sys.stderr)
        return {}
    return {}


def _deep_merge(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow for most keys; deep for 'list' subdict."""
    out = {**base}
    for k, v in incoming.items():
        if k == "list":
            bsub = out.get("list", {}) or {}
            vsub = v or {}
            if isinstance(bsub, dict) and isinstance(vsub, dict):
                out["list"] = {**bsub, **vsub}
            else:
                out["list"] = v
        else:
            out[k] = v
    return out

# -------- public API --------
def load() -> Dict[str, Any]:
    """
    Load config with precedence:
    defaults < XDG file (or legacy) < env overrides.
    """
    cfg = DEFAULTS.copy()

    # 1) XDG config
    xdg = config_path()
    xdg_data = _read_yaml(xdg)
    if xdg_data:
        cfg = _deep_merge(cfg, xdg_data)
    else:
        # 2) Legacy fallback
        for lp in legacy_paths():
            data = _read_yaml(lp)
            if data:
                cfg = _deep_merge(cfg, data)
                break

    # 3) Env overrides
    if os.getenv("TT_ROUNDING"):
        cfg["rounding"] = (os.getenv("TT_ROUNDING") or "").strip().lower() or cfg.get("rounding", "entry")
    if os.getenv("TT_DB"):
        cfg["db"] = (os.getenv("TT_DB") or "").strip()

    return cfg

def save(cfg: Dict[str, Any], *, path: Path | None = None, overwrite: bool = False) -> Path:
    """
    Write config to XDG config path (or supplied path). Creates parent directory.
    """
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError("PyYAML is required to save config (pip install pyyaml)") from e

    dest = path or config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not overwrite:
        return dest
    text = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    dest.write_text(text, encoding="utf-8")
    return dest

def ensure_exists(*, defaults: Dict[str, Any] | None = None, migrate_legacy: bool = True) -> Path:
    """
    Ensure the XDG config file exists; if not:
      - migrate from legacy ~/.tt.yml/.yaml if present (when migrate_legacy=True)
      - otherwise write defaults (merged with library defaults)
    Returns the path to the XDG config file.
    """
    xdg = config_path()
    if xdg.exists():
        return xdg

    if migrate_legacy:
        for lp in legacy_paths():
            data = _read_yaml(lp)
            if data:
                # merge legacy data over DEFAULTS
                merged = _deep_merge(DEFAULTS, data)
                return save(merged, path=xdg, overwrite=False)

    base = DEFAULTS if defaults is None else _deep_merge(DEFAULTS, defaults)
    return save(base, path=xdg, overwrite=False)

def xdg_config_home() -> Path:
    """Return XDG config home (supports macOS & Linux)."""
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

def xdg_config_path() -> Path:
    """Path to ttx config file."""
    return xdg_config_home() / "tt" / "config.yml"

def write_yaml_config(path: Path, data: Dict[str, Any]) -> None:
    """Write YAML config, fallback if PyYAML not available."""
    try:
        import yaml  # type: ignore
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    except ImportError:
        # minimal writer (no PyYAML installed)
        lines = []
        for k, v in data.items():
            if isinstance(v, dict):
                lines.append(f"{k}:")
                for kk, vv in v.items():
                    lines.append(f"  {kk}: {vv}")
            else:
                lines.append(f"{k}: {v}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

