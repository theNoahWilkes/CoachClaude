"""One config file for every coach: ~/.config/coachclaude/config.json, a section per game.

  {"ow":   {"player": ..., "captures": [...], "library": ..., "profile": ..., "tesseract": ...},
   "hots": {"player": ..., "replay_dir": ...}}

Data goes under ~/.local/share/coachclaude/<section>/ unless a section says otherwise.
Env: COACHCLAUDE_CONFIG names another file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP = "coachclaude"


def config_path() -> Path:
    return Path(os.environ.get("COACHCLAUDE_CONFIG") or Path.home() / ".config" / APP / "config.json")


def load() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    return p


def section(name: str) -> dict:
    return load().get(name) or {}


def update(name: str, **values) -> Path:
    """Merge values into one section and save; other sections are left alone."""
    cfg = load()
    sec = dict(cfg.get(name) or {})
    sec.update({k: v for k, v in values.items() if v is not None})
    cfg[name] = sec
    return save(cfg)


def data_dir(name: str) -> Path:
    return Path.home() / ".local" / "share" / APP / name
