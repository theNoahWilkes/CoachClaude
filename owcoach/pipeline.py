"""`owcoach run`: every local stage for one recording, into the library.

  scan -> segment -> events -> hud -> split -> packet

Each stage is skipped when its output already exists (so a rerun after a crash continues), and
`force` redoes them all. Nothing here calls a model.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import cache_for, session_dir
from .split import match_dirname


class NoProfile(RuntimeError):
    pass


def _matches(cache: Path) -> list[dict]:
    p = cache / "matches.json"
    return json.loads(p.read_text())["matches"] if p.exists() else []


def status(video: Path) -> dict:
    """Which stage outputs exist for this recording."""
    cache, sdir = cache_for(video), session_dir(video)
    ms = _matches(cache)
    games = [sdir / match_dirname(m) for m in ms]
    return {"cache": cache, "session": sdir, "matches": len(ms),
            "scan": (cache / "index.json").exists(), "segment": bool(ms), "events": (cache / "events.json").exists(),
            "hud": (cache / "hud.json").exists(),
            "split": (sdir / "session.json").exists() and all((g / "match.mp4").exists() for g in games),
            "packet": bool(games) and all((g / "packet" / "packet.json").exists() for g in games)}


def run(video: Path, jobs: int = 2, force: bool = False, hud: bool = True, log=print) -> Path:
    from .profile import profile_dir
    if not (profile_dir() / "profile.json").exists():
        raise NoProfile(f"no player profile in {profile_dir()}: run `owcoach setup --from \"{video}\"` once")
    cache = cache_for(video)
    st = status(video)
    t0 = time.time()

    def step(name: str, done: bool, fn):
        if done and not force:
            log(f"  {name:8s} already done")
            return
        t = time.time()
        fn()
        log(f"  {name:8s} {time.time() - t:5.0f}s")

    from .scan import scan
    step("scan", st["scan"], lambda: scan(video, cache, jobs=jobs, quiet=True))
    from .segment import segment
    step("segment", st["segment"], lambda: segment(cache))
    from .events import events
    step("events", st["events"], lambda: events(cache))
    if hud:
        from .hudscan import hudscan
        step("hud", st["hud"], lambda: hudscan(cache, quiet=True))
    from .split import split
    step("split", st["split"], lambda: split(cache))
    from .packet import packets
    step("packet", st["packet"], lambda: packets(cache, jobs=max(2, jobs * 2)))
    log(f"run: {video.name} -> {session_dir(video)} ({time.time() - t0:.0f}s)")
    try:
        from .site import build
        build()                      # the new game shows on the page as "not coached yet"
    except Exception as e:
        log(f"  page not rebuilt: {e}")
    return session_dir(video)
