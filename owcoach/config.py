"""Where everything lives: one config file, a per-player profile, a per-recording library.

  ~/.config/coachclaude/config.json      {"ow": {"player", "captures": [...], "library", "profile", "tesseract"}}
                                         (coachlib.config owns the file; the HotS coach has its own section)
  <profile>                             per player, small: profile.json, nameplate.png, portraits.npz,
                                         hud_layouts.json, history.sqlite, lessons.md, focus_proposal*.md, heroes/
  <library>/.cache/<recording stem>/     the scan cache (thumbnails, matches.json, events.json, hud.json)
  <library>/<session>/mNN_result_mode_map/{match.mp4, match.json, packet/...}

Captures (the ShadowPlay folder) are read-only input. Nothing is written next to a recording.
Why: until 2026-10-17 the session folders sat inside the capture folder, the cache under
~/.cache and the profile under ~/.owcoach, with the "where is the session folder" rule copied
in split, packet, the cut script and the skill text. One module owns it now, and the layout
matches the HotS coach's (~/.config/<app>, ~/.local/share/<app>) so a shared core can take it.

Env overrides: COACHCLAUDE_CONFIG (the file), OWCOACH_PROFILE, OWCOACH_LIBRARY.
"""
from __future__ import annotations

import os
from pathlib import Path

from coachlib.config import config_path, data_dir, dev, load, save  # noqa: F401  (the file is shared with the HotS coach)
from coachlib.install import skill_dir as _skill_dir
from coachlib.version import version

SESSION_PREFIX = "Overwatch 2 "        # ShadowPlay names recordings "Overwatch 2 <date> - <time>.<n>"
CAPTURE_DEFAULTS = ("Videos/NVIDIA/Overwatch 2",)


def ow() -> dict:
    return load().get("ow") or {}


def profile_dir() -> Path:
    return Path(os.environ.get("OWCOACH_PROFILE") or ow().get("profile") or data_dir("ow"))


def library() -> Path:
    return Path(os.environ.get("OWCOACH_LIBRARY") or ow().get("library") or Path.home() / "Videos" / "owcoach")


def captures() -> list[Path]:
    c = ow().get("captures")
    if c:
        return [Path(x) for x in c]
    return [p for p in (Path.home() / d for d in CAPTURE_DEFAULTS) if p.is_dir()]


def tesseract_dir() -> Path | None:
    t = ow().get("tesseract")
    return Path(t) if t else None


def stem(video: Path | str) -> str:
    """The recording's name without '.mp4'. Not Path.stem: a bare name ends in '.03' (the take
    number), which Path would strip as a suffix."""
    n = Path(video).name
    return n[:-4] if n.lower().endswith(".mp4") else n


def session_name(video: Path | str) -> str:
    """'Overwatch 2 2026.10.16 - 22.23.04.03' -> '2026.10.16 - 22.23.04.03' (the session folder name)."""
    st = stem(video)
    return st[len(SESSION_PREFIX):] if st.startswith(SESSION_PREFIX) else st


def cache_for(video: Path | str) -> Path:
    return library() / ".cache" / stem(video)


def session_dir(video: Path | str) -> Path:
    return library() / session_name(video)


def resolve_cache(arg: str) -> Path:
    """A cache dir, a recording path, or a bare recording stem / session name -> the cache dir."""
    p = Path(arg)
    if p.is_dir() and (p / "scan.json").exists():
        return p
    if p.suffix.lower() == ".mp4":
        return cache_for(p)
    for stem in (p.name, SESSION_PREFIX + p.name):
        c = library() / ".cache" / stem
        if c.is_dir():
            return c
    return p


def resolve_session(arg: str) -> Path:
    """A session folder path, or its name (with or without the 'Overwatch 2 ' prefix) -> the folder."""
    p = Path(arg)
    if p.is_dir():
        return p
    s = library() / session_name(p.name)
    return s if s.is_dir() else p


def recordings() -> list[Path]:
    """Every recording in the capture folders, newest first."""
    out = []
    for c in captures():
        out += [p for p in c.glob("*.mp4") if p.is_file()]
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def new_recordings() -> list[Path]:
    """Recordings with no session folder in the library yet."""
    return [p for p in recordings() if not (session_dir(p) / "session.json").exists()]


def relpath(p: Path | str, base: Path) -> str:
    """p relative to base as a forward-slash string, or p itself when it isn't under base."""
    try:
        return Path(p).resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(p)


def resolved() -> dict:
    return {"config": str(config_path()), "player": ow().get("player"), "captures": [str(c) for c in captures()],
            "library": str(library()), "profile": str(profile_dir()), "cache": str(library() / ".cache"),
            "tesseract": str(tesseract_dir()) if tesseract_dir() else None, "skill": str(skill_dir()),
            "dev": "on" if dev() else "off", "version": version()}


def repo_dir() -> Path:
    """The folder the package runs from (the checkout, or site-packages); the driver's cwd."""
    return Path(__file__).resolve().parent.parent


def skill_dir() -> Path:
    """The ow-coach skill: the packaged one (coachlib/skills), else the copy under ~/.claude/skills."""
    return _skill_dir("ow-coach")
