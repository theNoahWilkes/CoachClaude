"""Saves: the "SAVED <ally>" notice under the crosshair, as a text fact (ADR 0012).

Why: before ADR 0012 the overview readers found saves by looking at the whole match, and the
coach used them for what went well. Without the whole-match skim, a save is still on screen as a
notice pill: translucent blue, the ally's portrait, a heart, "SAVED STRIKERQ" (or "SAVED BY
HAMZERGER" when a teammate saved the player), centred under the crosshair, up for 2.5-3 s. It
shares the notice stack with "PROTECTED BY" (same pill, other icon), red kill pills and the
elimination banner; the newest notice is on top and older ones move down ~0.03 of the height.

How: the roiscan region "notices" (native resolution, at the thumbnail keyframes, 2 fps) is
scaled to a 720 px frame height and matched against assets/saved.png (heart + "SAVED", grey,
cut at 720 px from m06 Shambali 2026-10-20). At the 534 px thumbnail scale the word is ~8 px
tall and PROTECTED BY scores as high as a faint SAVED, so the thumbnails won't do.
assets/saved_by.png ("BY", same frame scale) right after the match tells the two apart.
Measured on the whole 2026-10-20 session (6 matches, 11,856 keyframes): 38 notices found, every
one a real SAVED (checked by eye), none of the 6 known ones missed, 5 SAVED BY all right. Lowest
real onset 0.667; the highest non-save 0.645 (PROTECTED BY under a kill pill), kept out by the
second-frame rule. The margin is thin on both sides: a "PROTECTED" check like the BY one is the
fix if a false save turns up. The notices roiscan pass took 65 s (CUDA), scoring 5 s.

Output: <cache>/notices.json {"version", "n_frames", "scores": [[saved, by] or null per frame]},
and per match a list of saves [{"t": session s, "by": bool}].
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from pathlib import Path

import cv2
import numpy as np

REF_H = 720                  # px: the frame height the templates were cut at
REGION_H = 0.30              # the "notices" region's height in game heights (roiscan.REGIONS)
SAVE_MIN, SAVE_NEAR = 0.66, 0.6   # onset: a frame >= MIN with another >= NEAR within the next two
BY_MIN = 0.62                # "BY" after the word: a teammate saved the player
SAVE_GAP = 1.5               # s below NEAR that ends a notice
NOTICES_VERSION = 1


def _tpl(name: str) -> np.ndarray:
    return cv2.imread(str(resources.files("owcoach") / "assets" / name), cv2.IMREAD_GRAYSCALE).astype(np.float32)


def score(crop: np.ndarray | None, saved: np.ndarray, by: np.ndarray) -> list[float] | None:
    """A notices crop -> [SAVED score, BY score right after it]; None when there is no crop."""
    if crop is None:
        return None
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    f = REF_H * REGION_H / g.shape[0]
    g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_AREA).astype(np.float32)
    r = cv2.matchTemplate(g, saved, cv2.TM_CCOEFF_NORMED)
    _, s, _, (x, y) = cv2.minMaxLoc(r)
    # "BY" starts ~55 px into the template's width at 720 px; look a little either side
    w = g[max(0, y - 3):y + saved.shape[0] + 3, x + 48:x + 48 + by.shape[1] + 16]
    b = float(cv2.matchTemplate(w, by, cv2.TM_CCOEFF_NORMED).max()) if w.shape[0] >= by.shape[0] and w.shape[1] >= by.shape[1] else 0.0
    return [round(float(s), 3), round(b, 3)]


def notices(cache: Path, jobs: int = 8) -> dict:
    """Scores for every keyframe of the session, cached in <cache>/notices.json."""
    from .roiscan import roiscan
    from .scan import load_index
    p = cache / "notices.json"
    frames = load_index(cache)["frames"]
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("n_frames") == len(frames) and d.get("version") == NOTICES_VERSION:
            return d
    roiscan(cache, quiet=True)            # crops the "notices" region if this cache predates it
    saved, by = _tpl("saved.png"), _tpl("saved_by.png")

    def one(e):
        im = cv2.imread(str(cache / "roi" / "notices" / e["f"]))
        return score(im, saved, by)

    with ThreadPoolExecutor(jobs) as ex:
        scores = list(ex.map(one, frames))
    d = {"version": NOTICES_VERSION, "n_frames": len(frames), "scores": scores}
    p.write_text(json.dumps(d), encoding="utf-8")
    return d


def saves(t: np.ndarray, scores: list, start: float, end: float) -> list[dict]:
    """The save notices between start and end (session s): [{"t": onset, "by": bool}]. A notice
    starts at a frame >= SAVE_MIN with another >= SAVE_NEAR in the next two, and lasts while the
    score stays >= SAVE_NEAR with gaps of at most SAVE_GAP. Two saves stacked within a notice's
    life count once."""
    ks = np.where((t >= start) & (t <= end))[0]
    s = [scores[k] or [0.0, 0.0] for k in ks]
    out: list[dict] = []
    seen = None                            # the current notice's last frame >= SAVE_NEAR
    for i, k in enumerate(ks):
        if seen is not None and t[k] - seen > SAVE_GAP:
            seen = None
        if seen is not None:
            if s[i][0] >= SAVE_NEAR:
                seen = float(t[k])
                out[-1]["by"] = out[-1]["by"] or s[i][1] >= BY_MIN
            continue
        if s[i][0] >= SAVE_MIN and any(x[0] >= SAVE_NEAR for x in s[i + 1:i + 3]):
            out.append({"t": float(t[k]), "by": s[i][1] >= BY_MIN})
            seen = float(t[k])
    return out
