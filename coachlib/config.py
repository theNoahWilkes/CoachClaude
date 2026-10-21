"""One config file for every coach: ~/.config/coachclaude/config.json, a section per game.

  {"ow":   {"player": ..., "captures": [...], "library": ..., "profile": ..., "tesseract": ...},
   "hots": {"player": ..., "replay_dir": ...}}

Data goes under ~/.local/share/coachclaude/<section>/ unless a section says otherwise.
Env: COACHCLAUDE_CONFIG names another file.

One top-level key, "dev": true, turns on developer mode (off by default): the coaching skills
may edit the pipeline when it misses, and `owcoach coach` prints its dollar estimate. A
released install never shows either. Env COACHCLAUDE_DEV=1|0 overrides it for one command.
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


def dev() -> bool:
    """Developer mode: off unless the config says {"dev": true} or COACHCLAUDE_DEV=1."""
    env = os.environ.get("COACHCLAUDE_DEV")
    if env is not None:
        return env.strip().lower() in ("1", "true", "on", "yes")
    return bool(load().get("dev"))


def set_dev(on: bool) -> Path:
    cfg = load()
    cfg["dev"] = bool(on)
    return save(cfg)


def parse_on_off(value: str) -> bool:
    v = value.strip().lower()
    if v in ("on", "1", "true", "yes"):
        return True
    if v in ("off", "0", "false", "no"):
        return False
    raise ValueError(f"expected on or off, got {value!r}")
