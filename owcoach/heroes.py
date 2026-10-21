"""Which hero was played when.

Two on-screen sources, used for what each is good at:

  * TAB side panel (hero name, white on a dark panel): read once per TAB press
    at full res, reliable. These reads *label* the portraits below.
  * HUD portrait (bottom-left face): on screen nearly every frame, so it gives
    the timeline at the 2 fps thumbnail rate. Each frame's face (inside the
    border, which differs between QP and comp) is compared with reference faces
    taken from frames near TAB reads; references persist across sessions in the
    profile's portraits.npz so a hero never TABbed this session is still known.

The portrait also shows whoever you are watching: kill cam (your killer) and
death spectate (a teammate). Those frames carry another player's nameplate, so
short portrait runs are checked against the player's nameplate (full-res colour
mask vs the profile's nameplate.png, see profile.py) and dropped as `views` if it isn't there.
Long runs skip the check: nobody spectates for 30 s with a live HUD.

The hero-select screen was tried first and dropped: its italic display font
defeats tesseract (see git history before the portrait commit).
"""
from __future__ import annotations

import difflib
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .profile import NAME_ROI, nameplate_score, nameplate_tpl, profile_dir
from .scan import frame_path, grab_frame

# Names as printed in the TAB side panel. Unlisted heroes don't snap; add them here.
HEROES = [
    "Ana", "Ashe", "Baptiste", "Bastion", "Brigitte", "Cassidy", "D.Va", "Doctrine", "Doomfist",
    "Echo", "Freja", "Genji", "Hanzo", "Hazard", "Illari", "Junker Queen", "Junkrat", "Juno",
    "Kiriko", "Lifeweaver", "Lúcio", "Mauga", "Mei", "Mercy", "Mizuki", "Moira", "Orisa",
    "Pharah", "Ramattra", "Reaper", "Reinhardt", "Roadhog", "Sigma", "Sojourn", "Soldier: 76",
    "Sombra", "Symmetra", "Torbjörn", "Tracer", "Venture", "Widowmaker", "Winston",
    "Wrecking Ball", "Wuyang", "Zarya", "Zenyatta",
]
ROLE = {h: "tank" for h in ("D.Va", "Doomfist", "Hazard", "Junker Queen", "Mauga", "Orisa", "Ramattra",
                            "Reinhardt", "Roadhog", "Sigma", "Winston", "Wrecking Ball", "Zarya")}
ROLE |= {h: "damage" for h in ("Ashe", "Bastion", "Cassidy", "Echo", "Freja", "Genji", "Hanzo", "Junkrat",
                              "Mei", "Pharah", "Reaper", "Sojourn", "Soldier: 76", "Sombra", "Symmetra",
                              "Torbjörn", "Tracer", "Venture", "Widowmaker")}
ROLE |= {h: "support" for h in ("Ana", "Baptiste", "Brigitte", "Illari", "Juno", "Kiriko", "Lifeweaver",
                               "Lúcio", "Mercy", "Moira", "Wuyang", "Zenyatta",
                               "Doctrine", "Mizuki")}  # last two: SURVIVOR on their hero-select screens

TAB_HERO_ROI = (0.57, 0.33, 0.72, 0.39)  # hero name in the TAB side panel ("MOIRA")
TAB_PRESS_GAP = 2.0                      # s: TAB frames closer than this are one press
TAB_SNAP_CUTOFF = 0.75                   # TAB panel text is clean; garbage like "Sows Afa" must not snap

PORTRAIT = (36, 438, 66, 486)            # face inside the portrait border, thumbnail px; doesn't shift with dx
PORTRAIT_HUD = 0.40                      # only frames with a HUD carry a portrait
REF_WINDOW = 15.0                        # s around a TAB read whose frames label that hero's references
REF_HUD = 0.60                           # stricter HUD score for reference frames
REF_CAP = 400                            # references kept per hero per session
TOPK = 5                                 # score = mean of the k best reference matches
MIN_SCORE = 0.50                         # below this the face matches no known hero
MIN_RUN = 2                              # frames: shorter portrait runs are noise
CHECK_RUN = 60                           # frames (30 s): shorter runs get the nameplate check
NAME_MIN = 0.50                          # nameplate mask match: own name scores >= 0.8, others <= 0.3
NAME_SAMPLES = 3                         # frames checked per run


def _key(s: str) -> str:
    import unicodedata
    return re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", s.upper()).encode("ascii", "ignore").decode())


_TABLE = {_key(h): h for h in HEROES}


def snap_hero(raw: str, cutoff: float = TAB_SNAP_CUTOFF) -> tuple[str | None, float]:
    k = _key(raw)
    if len(k) < 2:
        return None, 0.0
    best = max(_TABLE, key=lambda h: difflib.SequenceMatcher(None, k, h).ratio())
    r = difflib.SequenceMatcher(None, k, best).ratio()
    return (_TABLE[best], r) if r >= cutoff else (None, r)


def snap_words(text: str | None, cutoff: float = TAB_SNAP_CUTOFF) -> str | None:
    """Best hero match over the words of an OCR line ('Zenvatta Sess' -> Zenyatta)."""
    best = max((snap_hero(w, cutoff) for w in (text or "").split()), key=lambda x: x[1], default=(None, 0.0))
    return best[0]


def read_tab_hero(crop: np.ndarray) -> str | None:
    """crop = the TAB_HERO_ROI region of a full-res frame -> raw OCR words."""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    b = cv2.resize(np.where(g > 170, 0, 255).astype(np.uint8), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, buf = cv2.imencode(".png", b)
    txt = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "6", "-l", "eng"],
                         input=buf.tobytes(), capture_output=True).stdout.decode(errors="replace")
    words = re.findall(r"[A-Za-z][A-Za-z.:'\-]{2,}", txt)
    return " ".join(words).title() if words else None


def tab_reads(cache: Path, tab_times: list[float]) -> list[dict]:
    """One full-res side-panel read per TAB press -> [{t, hero|None, raw}]."""
    presses: list[list[float]] = []
    for tt in tab_times:
        if presses and tt - presses[-1][-1] <= TAB_PRESS_GAP:
            presses[-1].append(tt)
        else:
            presses.append([tt])
    td = tempfile.TemporaryDirectory()

    def job(i_p):
        i, p = i_p
        tt = p[len(p) // 2]
        raw = read_tab_hero(cv2.imread(str(grab_frame(cache, tt, Path(td.name) / f"tab{i}.png", roi=TAB_HERO_ROI))))
        return {"t": round(tt, 2), "hero": snap_words(raw), "raw": raw}

    with td, ThreadPoolExecutor(4) as ex:
        return list(ex.map(job, enumerate(presses)))


# --- portrait --------------------------------------------------------------------

def portrait_vec(thumb: np.ndarray) -> np.ndarray:
    """Unit-ish vector: z-scored gradient magnitude (shape) + 0.5 * z-scored Lab a/b (colour).
    Gradients shrug off the screen-wide tints (heal yellow, damage red) that raw pixels don't."""
    x0, y0, x1, y1 = PORTRAIT
    p = thumb[y0:y1, x0:x1]
    g = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)).ravel()
    m = (m - m.mean()) / (m.std() + 1e-6)
    ab = cv2.cvtColor(p, cv2.COLOR_BGR2LAB).astype(np.float32)[..., 1:].ravel()
    ab = (ab - ab.mean()) / (ab.std() + 1e-6)
    return (np.concatenate([m, 0.5 * ab]) / np.sqrt(len(m) + 0.25 * len(ab))).astype(np.float32)


def _vecs(cache: Path, frames: list[dict], ks) -> np.ndarray:
    return np.array([portrait_vec(cv2.imread(str(frame_path(cache, frames[k])))) for k in ks], np.float32)


def _topk(X: np.ndarray, V: np.ndarray) -> np.ndarray:
    S = X @ V.T
    k = min(TOPK, V.shape[0])
    return np.partition(S, -k, axis=1)[:, -k:].mean(1)


def _purify(refs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Drop references that look more like another hero's set than their own: spectate and
    kill-cam frames that happened to sit near a TAB press."""
    out = {}
    for h, V in refs.items():
        own = V @ V.T
        np.fill_diagonal(own, -1)
        k = min(TOPK, max(1, len(V) - 1))
        s_own = np.partition(own, -k, axis=1)[:, -k:].mean(1)
        s_other = np.max([_topk(V, W) for g, W in refs.items() if g != h] or [np.zeros(len(V))], axis=0)
        keep = (s_own > s_other) & (s_own >= np.percentile(s_own, 10))
        out[h] = V[keep]
    return out


def build_refs(cache: Path, frames: list[dict], t: np.ndarray, hud: np.ndarray, reads: list[dict]) -> dict:
    """This session's TAB-labelled portraits, merged with the player's library."""
    by_hero: dict[str, set[int]] = {}
    for r in reads:
        if r["hero"]:
            ks = np.where((np.abs(t - r["t"]) <= REF_WINDOW) & (hud >= REF_HUD))[0]
            by_hero.setdefault(r["hero"], set()).update(ks.tolist())
    rng = np.random.default_rng(0)
    session = {}
    for h, ks in by_hero.items():
        ks = sorted(ks)
        if len(ks) > REF_CAP:
            ks = sorted(rng.choice(ks, REF_CAP, replace=False))
        session[h] = _vecs(cache, frames, ks)
    session = _purify(session) if session else {}

    lib_path = profile_dir() / "portraits.npz"
    lib = dict(np.load(lib_path)) if lib_path.exists() else {}
    stem = cache.name
    lib = {k: v for k, v in lib.items() if not k.startswith(stem + "|")}
    lib |= {f"{stem}|{h}": V for h, V in session.items() if len(V)}
    np.savez_compressed(lib_path, **lib)
    refs: dict[str, list[np.ndarray]] = {}
    for k, V in lib.items():
        refs.setdefault(k.split("|", 1)[1], []).append(V)
    return {h: np.concatenate(v) for h, v in refs.items()}


def _perk_box(name_crop: np.ndarray) -> bool:
    """The NAME_ROI crop filled with the perk prompt's saturated orange."""
    from .overlay import PERK_MIN, _frac
    return _frac(name_crop, (5, 22), 150, 150) >= PERK_MIN


def match_heroes(cache: Path, frames: list[dict], t: np.ndarray, hud: np.ndarray,
                 start: float, end: float, reads: list[dict], refs: dict[str, np.ndarray]
                 ) -> tuple[list[dict], list[dict], list[int]]:
    """-> (segments, views, own) for one match; own = frame indices showing the player's own view.

    Every HUD frame gets the best-matching reference face. Runs of the same face shorter than
    CHECK_RUN are kept only if the player's nameplate shows; the rest are `views` (kill cam,
    spectating). Surviving runs of the same hero merge; a hero change is a swap, placed
    between the last frame of one hero and the first of the next.
    """
    ks = np.where((t >= start) & (t <= end) & (hud >= PORTRAIT_HUD))[0]
    if not len(ks) or not refs:
        return [], [], []
    X = _vecs(cache, frames, ks)
    names = list(refs)
    S = np.stack([_topk(X, refs[h]) for h in names], 1)
    best, score = S.argmax(1), S.max(1)
    lab = [names[b] if s >= MIN_SCORE else None for b, s in zip(best, score)]

    runs: list[dict] = []
    for i, h in enumerate(lab):
        if h is None:
            continue
        if runs and runs[-1]["hero"] == h and runs[-1]["i1"] == i - 1:
            runs[-1]["i1"] = i
        else:
            runs.append({"hero": h, "i0": i, "i1": i})
    runs = [r for r in runs if r["i1"] - r["i0"] + 1 >= MIN_RUN]

    tpl = nameplate_tpl()
    to_check = [r for r in runs if r["i1"] - r["i0"] + 1 < CHECK_RUN]
    td = tempfile.TemporaryDirectory()

    def check(j_r):
        j, r = j_r
        idx = np.unique(np.linspace(r["i0"], r["i1"], NAME_SAMPLES).round().astype(int))
        sc = []
        for n, i in enumerate(idx):
            p = grab_frame(cache, float(t[ks[i]]), Path(td.name) / f"np{j}_{n}.png", roi=NAME_ROI)
            img = cv2.imread(str(p))
            # the SELECT PERK box sits over the nameplate: with it up, the nameplate can't show,
            # and nothing but the player's own view carries it (2026-10-16)
            sc.append(1.0 if _perk_box(img) else nameplate_score(img, tpl))
        return max(sc)

    with td, ThreadPoolExecutor(6) as ex:
        for r, sc in zip(to_check, ex.map(check, enumerate(to_check))):
            r["name"] = round(sc, 2)

    views, mine, own = [], [], []
    for r in runs:
        r["t0"], r["t1"], r["n"] = float(t[ks[r["i0"]]]), float(t[ks[r["i1"]]]), r["i1"] - r["i0"] + 1
        if r.get("name", 1.0) < NAME_MIN:
            views.append({"t0": round(r["t0"], 2), "t1": round(r["t1"], 2), "portrait": r["hero"],
                          "frames": r["n"], "nameplate": r["name"]})
        else:
            own += [int(k) for k in ks[r["i0"]:r["i1"] + 1]]
            if mine and mine[-1]["hero"] == r["hero"]:
                mine[-1]["t1"], mine[-1]["n"] = r["t1"], mine[-1]["n"] + r["n"]
            else:
                mine.append(dict(r))
    if not mine:
        return [], views, own

    segs = []
    for j, r in enumerate(mine):
        frm = start if j == 0 else r["t0"]
        to = end if j == len(mine) - 1 else r["t1"]
        tv = [x for x in reads if x["hero"] and frm <= x["t"] <= to]
        segs.append({"hero": r["hero"], "from": round(frm, 2), "to": round(to, 2),
                     "seconds": round(to - frm, 1), "role": ROLE.get(r["hero"]),
                     "portrait_frames": r["n"], "tab_votes": sum(x["hero"] == r["hero"] for x in tv),
                     "tab_conflicts": sum(x["hero"] != r["hero"] for x in tv),
                     "swap": None if j == 0 else "portrait"})
    return segs, views, own
