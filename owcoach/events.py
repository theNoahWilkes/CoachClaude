"""Stage 4: timestamped events per match. First source: the kill feed.

Each feed row is "killer [hero, assist icons] [ability] > [hero] victim", newest on top.
The player's name is found with the profile's nameplate template (same font and size in
the feed), on the white-text mask of the full-res feed crop (roiscan region "feed"):

  * name at the right edge  -> the player is the victim  -> death
  * name at the left        -> the player is the killer  -> final blow

A candidate must also be a whole word (no ink just left or right of it), which rejects the
name turning up inside a longer one. Rows stay on screen for several seconds and replay
during the kill cam (from the killer's side, colours swapped), so events are tracked:

  * deaths: sightings closer than DEATH_GAP are one death (respawning takes longer)
  * kills:  the victim's name is OCR'd on every sighting; the same name (fuzzy) within
            KILL_SAME seconds of a kill's first sighting is that kill. Rows flicker in and
            out of detection (semi-transparent boxes), so identity can't rest on continuity.

The killer's name is OCR'd once per death, from the same row.
Validated: deaths equal the final scoreboard's D in all 9 matches of the first two sessions.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .profile import nameplate_tpl, text_mask
from .scan import load_index

FIRST_CUT = 0.40      # coarse template score that makes a candidate worth rescoring
NAME_MIN = 0.55       # rescored score for the player's name (others <= 0.51, own 0.55..0.8)
MAX_HITS = 4          # candidates per frame
DEATH_GAP = 10.0      # s
KILL_SAME = 12.0      # s: the same victim name within this of a kill's first sighting is that kill
ICON_EDGES = 0.25     # edge density left of a victim name: hero portraits >= 0.33, deployable icons <= 0.18
MISREAD_GAP = 6.0     # s: a differently-read kill this soon after another, never on screen with it, is a misread


def _feed(cache: Path, entry: dict) -> np.ndarray:
    return cv2.imread(str(cache / "roi" / "feed" / entry["f"]))


def _rescore(im: np.ndarray, x: int, y: int, tpl: np.ndarray) -> tuple[float, bool, int, int]:
    """Local, brightness-adaptive match around a candidate -> (score, whole_word, x, y)."""
    th, tw = tpl.shape
    px, py = max(0, x - 12), max(0, y - 8)
    P = im[py:y + th + 8, px:x + tw + 12]
    best = (0.0, False, x, y)
    for frac in (0.75, 0.6, 0.45):
        m = text_mask(P, frac)
        if m.shape[0] < th or m.shape[1] < tw or not m.any():
            continue
        r = cv2.matchTemplate(m, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, (lx, ly) = cv2.minMaxLoc(r)
        if mx > best[0]:
            rows = m[ly + 3:ly + th - 3]
            left = rows[:, max(0, lx - 5):lx + 1].sum(0)
            right = rows[:, lx + tw - 1:lx + tw + 5].sum(0)
            best = (float(mx), bool((left >= 2).sum() == 0 and (right >= 2).sum() == 0), px + lx, py + ly)
    return best


def frame_hits(im: np.ndarray, tpl: np.ndarray) -> list[dict]:
    """Player-name sightings in one feed crop -> [{x, y, score, side}]."""
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 2] > 175) & (hsv[..., 1] < 80)).astype(np.float32)
    th, tw = tpl.shape
    r = cv2.matchTemplate(m, tpl, cv2.TM_CCOEFF_NORMED)
    out = []
    for _ in range(MAX_HITS):
        _, mx, _, (x, y) = cv2.minMaxLoc(r)
        if mx < FIRST_CUT:
            break
        r[max(0, y - th):y + th, max(0, x - tw):x + tw] = -1
        sc, word, x2, y2 = _rescore(im, x, y, tpl)
        if sc >= NAME_MIN and word:
            out.append({"x": x2, "y": y2, "score": round(sc, 3),
                        "side": "victim" if x2 > im.shape[1] / 2 else "killer"})
    return out


def scan_feed(cache: Path) -> list[list[dict]]:
    """Hits for every thumbnail frame, cached to feed_hits.json."""
    p = cache / "feed_hits.json"
    frames = load_index(cache)["frames"]
    if p.exists():
        d = json.loads(p.read_text())
        if len(d) == len(frames):
            return d
    tpl = nameplate_tpl()
    with ThreadPoolExecutor(12) as ex:
        hits = list(ex.map(lambda e: frame_hits(_feed(cache, e), tpl), frames))
    p.write_text(json.dumps(hits))
    return hits


def _name_crop(im: np.ndarray, y: int, th: int, side: str, with_x: bool = False):
    """Greyscale crop of the other player's name on this row: the rightmost word of the right
    half (victim) or the leftmost word of the left half (killer)."""
    W = im.shape[1]
    band = im[max(0, y - 4):y + th + 4]
    half = band[:, W // 2:] if side == "right" else band[:, :int(W * 0.7)]
    m = text_mask(half, 0.6).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    cs = sorted((st[i] for i in range(1, n) if 0.45 * th <= st[i, 3] <= 1.1 * th and st[i, 4] >= 6),
                key=lambda c: c[0])
    if not cs:
        return (None, None) if with_x else None
    words = [[cs[0]]]
    for c in cs[1:]:
        prev = words[-1][-1]
        if c[0] - (prev[0] + prev[2]) > 0.5 * th:
            words.append([c])
        else:
            words[-1].append(c)
    w = words[-1] if side == "right" else words[0]
    x0, x1 = min(c[0] for c in w), max(c[0] + c[2] for c in w)
    y0, y1 = min(c[1] for c in w), max(c[1] + c[3] for c in w)
    if x1 - x0 < th:
        return (None, None) if with_x else None
    g = cv2.cvtColor(half[max(0, y0 - 3):y1 + 3, max(0, x0 - 4):x1 + 4], cv2.COLOR_BGR2GRAY)
    if not with_x:
        return g
    # victim side: what sits left of the name, a hero portrait (detailed) or a deployable icon
    # (a flat square with one small glyph). Colour can't tell them apart: Doctrine's dark red
    # portrait on a red box looks like the box.
    icon = cv2.cvtColor(half[:, max(0, x0 - 60):max(0, x0 - 6)], cv2.COLOR_BGR2GRAY).astype(np.float32)
    if icon.size == 0:
        return g, None
    edges = np.hypot(cv2.Sobel(icon, cv2.CV_32F, 1, 0), cv2.Sobel(icon, cv2.CV_32F, 0, 1))
    return g, bool((edges > 60).mean() < ICON_EDGES)


def _similar(a: str | None, b: str | None) -> float:
    return difflib.SequenceMatcher(None, a or "", b or "").ratio() if a and b else 0.0


def ocr_name(gray: np.ndarray | None) -> str | None:
    """One name, white on a coloured box -> uppercase text (A-Z, 0-9, _)."""
    if gray is None:
        return None
    g = cv2.resize(255 - gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    g = cv2.copyMakeBorder(g, 16, 16, 16, 16, cv2.BORDER_REPLICATE)
    _, buf = cv2.imencode(".png", g)
    txt = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7", "-c",
                          "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"],
                         input=buf.tobytes(), capture_output=True).stdout.decode(errors="replace")
    txt = re.sub(r"[^A-Z0-9_]", "", txt.upper())
    return txt if len(txt) >= 3 else None


def match_events(cache: Path, frames: list[dict], t: np.ndarray, hits: list[list[dict]],
                 start: float, end: float) -> dict:
    tpl = nameplate_tpl()
    th = tpl.shape[0]
    ks = [k for k in range(len(t)) if start <= t[k] <= end + 3]

    deaths: list[dict] = []
    for k in ks:
        v = [h for h in hits[k] if h["side"] == "victim"]
        if not v:
            continue
        if deaths and t[k] - deaths[-1]["last"] <= DEATH_GAP:
            deaths[-1]["last"] = float(t[k])
            deaths[-1]["n"] += 1
            deaths[-1]["seen"].append((k, v[0]["y"]))
        else:
            deaths.append({"t": float(t[k]), "last": float(t[k]), "n": 1, "seen": [(k, v[0]["y"])]})

    # final blows: OCR the victim on every sighting, then group by name
    sight = [(k, h) for k in ks for h in hits[k] if h["side"] == "killer"]

    def victim(kh):
        k, h = kh
        g, flat = _name_crop(_feed(cache, frames[k]), h["y"], th, "right", with_x=True)
        return ocr_name(g), flat

    with ThreadPoolExecutor(8) as ex:
        reads = list(ex.map(victim, sight))
    kills: list[dict] = []
    for (k, h), (nm, flat) in zip(sight, reads):
        tk = float(t[k])
        live = [e for e in kills if tk - e["t"] <= KILL_SAME]
        if nm:
            same = max(live, key=lambda e: _similar(e["victim"], nm), default=None)
            if same is not None and _similar(same["victim"], nm) >= 0.6:
                same["n"] += 1
                same["names"].append(nm)
                same["ks"].add(k)
                same["flat"].append(flat)
                continue
        elif live:
            near = min(live, key=lambda e: tk - e["t"])
            near["n"] += 1
            near["ks"].add(k)
            continue
        kills.append({"t": tk, "n": 1, "k": k, "y": h["y"], "victim": nm, "names": [nm] if nm else [],
                      "ks": {k}, "flat": [flat]})
    # a misread of a row never shares a frame with the row's good reading; two real kills
    # close together are two rows on screen at once
    kills.sort(key=lambda e: e["t"])
    merged: list[dict] = []
    for e in kills:
        host = next((a for a in reversed(merged) if e["t"] - a["t"] <= MISREAD_GAP
                     and not (a["ks"] & e["ks"])), None)
        if host is not None:
            host["n"] += e["n"]
            host["names"] += e["names"]
            host["ks"] |= e["ks"]
            host["flat"] += e["flat"]
        else:
            merged.append(e)
    kills = [e for e in merged if e["names"] or e["n"] >= 2]
    for e in kills:   # most common reading wins
        if e["names"]:
            e["victim"] = Counter(e["names"]).most_common(1)[0][0]

    def killer(e):
        reads = [ocr_name(_name_crop(_feed(cache, frames[k]), y, th, "left")) for k, y in e["seen"][:6]]
        reads = [r for r in reads if r]
        return Counter(reads).most_common(1)[0][0] if reads else None

    with ThreadPoolExecutor(8) as ex:
        killers = list(ex.map(killer, deaths))
    for e in kills:
        votes = [f for f in e["flat"] if f is not None]
        e["deployable"] = bool(votes) and sum(votes) > len(votes) / 2
        e["icon_votes"] = votes
    return {
        "deaths": [{"t": round(e["t"], 2), "t_clip": None, "killed_by": nm, "seen": e["n"]}
                   for e, nm in zip(deaths, killers)],
        "final_blows": [{"t": round(e["t"], 2), "t_clip": None, "victim": e["victim"], "seen": e["n"]}
                        for e in kills if not e["deployable"]],
        "deployables_destroyed": [{"t": round(e["t"], 2), "t_clip": None, "owner": e["victim"], "seen": e["n"]}
                                  for e in kills if e["deployable"]],
    }


# --- ult ---------------------------------------------------------------------------
# The ult meter (roiscan region "ult") is a ring of orange segments around the charge %.
# When the ult is ready it turns into a blue ring around a light disc with the ult icon
# (the icon's glyph is hero-specific and can cover most of the disc, so only its rim is used),
# which is what's detected here: the % ring is unreliable on orange/red backgrounds and
# isn't needed for ready / used / held. Only the player's own-view frames count: the kill
# cam shows the killer's meter.
ULT_CY = 0.861 - 0.795       # ring centre below the top of the "ult" region, in heights
ULT_RIM = (0.024, 0.030)     # light rim of the icon disc (the glyph inside is hero-specific, often dark)
ULT_RING = (0.033, 0.045)    # the blue ring
READY_LIGHT = 0.50           # light rim: ready 0.64..0.81 for Doctrine/Lifeweaver/Mizuki/Moira
READY_BLUE = 0.35            # blue ring: ready 0.48..0.72
READY_SAT_STEP = 50          # ring saturation minus rim saturation: rejects plain light-blue backgrounds
READY_MIN = 2                # own frames in a row before a state change counts
SWAP_NEAR = 15.0             # s: a ready ult that disappears this close to a hero swap was lost
RESPAWN_MAX = 40.0           # s: death -> back in own view, upper bound (kill cam + respawn + hero select)
RECHARGE_MIN = 25.0          # s: no ult recharges from empty this fast
DIED_WITH = 2.0              # s: a death sighted this soon after the last ready frame took the ult with it
                             # (the feed lags the death by up to 2 s; the icon goes at the death itself)


def ult_ready(u: np.ndarray, gh: float) -> bool:
    """u = the "ult" region crop; gh = game-area height in the crop's pixel scale."""
    cy, cx = ULT_CY * gh, u.shape[1] / 2
    yy, xx = np.mgrid[0:u.shape[0], 0:u.shape[1]]
    d = np.hypot(xx - cx, yy - cy)
    hsv = cv2.cvtColor(u, cv2.COLOR_BGR2HSV).astype(int)
    rim = hsv[(d > ULT_RIM[0] * gh) & (d < ULT_RIM[1] * gh)]
    ring = hsv[(d > ULT_RING[0] * gh) & (d < ULT_RING[1] * gh)]
    light = ((rim[:, 2] > 150) & (rim[:, 1] < 100)).mean()
    blue = ((ring[:, 0] >= 92) & (ring[:, 0] <= 125) & (ring[:, 1] > 70) & (ring[:, 2] > 110)).mean()
    step = np.median(ring[:, 1]) - np.median(rim[:, 1])
    return bool(light >= READY_LIGHT and blue >= READY_BLUE and step >= READY_SAT_STEP)


def scan_ult(cache: Path, gh: float) -> np.ndarray:
    """Ready flag for every frame, cached to ult_ready.npy."""
    p = cache / "ult_ready.npy"
    frames = load_index(cache)["frames"]
    if p.exists():
        r = np.load(p)
        if len(r) == len(frames):
            return r
    with ThreadPoolExecutor(12) as ex:
        r = np.array(list(ex.map(lambda e: ult_ready(cv2.imread(str(cache / "roi" / "ult" / e["f"])), gh), frames)))
    np.save(p, r)
    return r


def match_ult(m: dict, t: np.ndarray, ready: np.ndarray, own: np.ndarray, deaths: list[dict]) -> dict:
    ks = [k for k in np.where(own)[0] if m["start"] <= t[k] <= m["end"]]
    # debounced state over own frames only
    state, runs, cur, streak = False, [], None, 0
    for k in ks:
        if bool(ready[k]) != state:
            streak += 1
            if streak >= READY_MIN:
                state = not state
                first = ks[ks.index(k) - READY_MIN + 1]
                if state:
                    cur = {"ready_t": float(t[first])}
                else:
                    cur["last_ready_t"] = float(t[prev_ready])
                    cur["gone_t"] = float(t[first])
                    runs.append(cur)
                    cur = None
                streak = 0
        else:
            streak = 0
        if ready[k]:
            prev_ready = k
    if cur is not None:
        cur["last_ready_t"] = float(t[prev_ready])
        cur["gone_t"] = None
        runs.append(cur)

    # One ult can't be spent and fully recharged in RECHARGE_MIN seconds, so ready runs closer
    # than that are one ult: the meter was hidden by effects for a moment, or by a death (charge
    # survives death; the kill cam and dead frames read as not ready), the latter up to RESPAWN_MAX.
    merged = []
    for r in runs:
        gap = r["ready_t"] - merged[-1]["last_ready_t"] if merged and merged[-1]["gone_t"] is not None else None
        died = gap is not None and any(merged[-1]["last_ready_t"] - 1 <= d["t"] <= r["ready_t"] for d in deaths)
        if gap is not None and (gap <= RECHARGE_MIN or (died and gap <= RESPAWN_MAX)):
            merged[-1]["last_ready_t"], merged[-1]["gone_t"] = r["last_ready_t"], r["gone_t"]
        else:
            merged.append(r)
    runs = merged
    swaps = [h["from"] for h in m.get("heroes", [])[1:]]
    out = []
    for r in runs:
        if r["gone_t"] is None:
            how = "held_to_end"
        elif any(r["last_ready_t"] - 1 <= d["t"] <= r["last_ready_t"] + DIED_WITH for d in deaths):
            how = "died_with_it"
        elif any(r["last_ready_t"] - 1 <= sw <= r["gone_t"] + SWAP_NEAR for sw in swaps):
            how = "lost_on_swap"
        else:
            how = "used"
        end = r["last_ready_t"] if how in ("used", "died_with_it") else (r["gone_t"] or m["end"])
        died = [d["t"] for d in deaths if r["ready_t"] - 1 <= d["t"] <= end + 2]
        out.append({"ready_t": round(r["ready_t"], 2),
                    "used_t": round(r["last_ready_t"], 2) if how == "used" else None,
                    "outcome": how, "held_s": round(end - r["ready_t"], 1),
                    "deaths_while_ready": [round(x, 2) for x in died],
                    "hero": _hero_at(m, r["ready_t"])})
    return {"ults": out}


# --- players alive ---------------------------------------------------------------------
# "[blue icon] 5  VS  [red icon] 4" (roiscan region "alive"). Found by the "VS" text, then the
# two digits at fixed offsets either side, binarized and matched to digit templates from the
# game font (assets/alive_digits.npz: 2..5 so far; 0/1 read as None until seen). The counter
# fades while both teams are full and is hidden under TAB / kill cam / death screen, so it's
# a sparse series of readings; events take the last reading just before them.
ALIVE_REF_H = 1440           # px height the offsets below were measured at
VS_AT = (104, 21)            # where assets/alive_vs.png was cut from, at ALIVE_REF_H
BLUE_X = (-35, -17)          # blue digit window, x relative to the VS template's left edge
RED_X = (79, 101)            # red digit window
DIGIT_Y = (15, 41)
VS_MIN = 0.5
DIGIT_MIN = 0.6


def _assets():
    from importlib import resources
    base = resources.files("owcoach") / "assets"
    vs = (cv2.imread(str(base / "alive_vs.png"), cv2.IMREAD_GRAYSCALE) > 127).astype(np.float32)
    digits = dict(np.load(str(base / "alive_digits.npz")))
    return vs, digits


def read_alive(a: np.ndarray, vs: np.ndarray, digits: dict, scale: float = 1.0) -> tuple | None:
    """a = "alive" region crop -> (ally, enemy) with None for an unreadable digit, or None."""
    if scale != 1.0:
        a = cv2.resize(a, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(a, cv2.COLOR_BGR2HSV).astype(int)
    m = ((hsv[..., 1] < 110) & (hsv[..., 2] > 140)).astype(np.float32)
    if m.shape[0] < vs.shape[0] or m.shape[1] < vs.shape[1]:
        return None
    r = cv2.matchTemplate(m, vs, cv2.TM_CCOEFF_NORMED)
    _, mx, _, (vx, _) = cv2.minMaxLoc(r)
    if mx < VS_MIN:
        return None

    def digit(x0, x1):
        w = a[DIGIT_Y[0]:DIGIT_Y[1], max(0, vx + x0):max(0, vx + x1)].max(2).astype(np.uint8)
        if w.size == 0 or w.shape[1] < 8:
            return None
        _, b = cv2.threshold(w, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        n, lab, st, _ = cv2.connectedComponentsWithStats(b)
        cs = [i for i in range(1, n) if st[i, 3] >= 12 and st[i, 4] >= 25]
        if not cs:
            return None
        i = max(cs, key=lambda i: st[i, 4])
        x, y, ww, hh = st[i, :4]
        g = cv2.resize((lab[y:y + hh, x:x + ww] == i).astype(np.float32), (14, 20), interpolation=cv2.INTER_AREA)
        sc = {d: max(float(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)[0, 0]) for t in ts) for d, ts in digits.items()}
        d = max(sc, key=sc.get)
        return int(d) if sc[d] >= DIGIT_MIN else None

    return digit(*BLUE_X), digit(*RED_X)


def scan_alive(cache: Path, gh: float) -> list:
    """(ally, enemy) or None for every frame, cached to alive.json."""
    p = cache / "alive.json"
    frames = load_index(cache)["frames"]
    if p.exists():
        r = json.loads(p.read_text())
        if len(r) == len(frames):
            return r
    vs, digits = _assets()
    with ThreadPoolExecutor(12) as ex:
        r = list(ex.map(lambda e: read_alive(cv2.imread(str(cache / "roi" / "alive" / e["f"])), vs, digits,
                                             gh / ALIVE_REF_H), frames))
    p.write_text(json.dumps(r))
    return r


def match_alive(m: dict, t: np.ndarray, alive: list, ev: dict) -> dict:
    """Changes in the counter over the match, and the counts just before each death / final blow."""
    ks = [k for k in range(len(t)) if m["start"] <= t[k] <= m["end"] and alive[k] and None not in alive[k]]
    changes = []
    for k in ks:
        a = tuple(alive[k])
        if not changes or (changes[-1]["ally"], changes[-1]["enemy"]) != a:
            changes.append({"t": round(float(t[k]), 2), "ally": a[0], "enemy": a[1]})

    def before(tt):
        prev = [k for k in ks if tt - 6 <= t[k] <= tt - 0.4]
        if not prev:
            return None
        a = alive[prev[-1]]
        return {"ally": a[0], "enemy": a[1], "age_s": round(tt - float(t[prev[-1]]), 1)}

    for e in ev["deaths"] + ev["final_blows"]:
        e["alive_before"] = before(e["t"])
    return {"alive": changes}


def _hero_at(m: dict, tt: float) -> str | None:
    for h in m.get("heroes", []):
        if h["from"] - 1 <= tt <= h["to"] + 1:
            return h["hero"]
    return None


def events(cache: Path) -> dict:
    """All matches in a segmented session -> events.json in the cache."""
    from .roiscan import roiscan
    roiscan(cache, quiet=True)
    frames = load_index(cache)["frames"]
    t = np.array([e["t"] for e in frames])
    hits = scan_feed(cache)
    sess = json.loads((cache / "matches.json").read_text())
    cfg = json.loads((cache / "scan.json").read_text())
    gh = cfg["crop"][1] if cfg["crop"] else cfg["probe"]["height"]
    ready = scan_ult(cache, gh)
    own = np.load(cache / "own_view.npy")
    alive = scan_alive(cache, gh)
    from .objective import context_at, match_objective, scan_objective
    obj_states = scan_objective(cache, own, gh)["states"]
    out = []
    for m in sess["matches"]:
        ev = match_events(cache, frames, t, hits, m["start"], m["end"])
        ev |= match_ult(m, t, ready, own, ev["deaths"])
        ev |= match_alive(m, t, alive, ev)
        ev |= match_objective(m, obj_states)
        for e in ev["deaths"] + ev["final_blows"]:
            e["objective"] = context_at(ev["objective"], obj_states, e["t"])
        for u in ev["ults"]:
            u["objective_at_ready"] = context_at(ev["objective"], obj_states, u["ready_t"])
            if u["used_t"] is not None:
                u["objective_at_use"] = context_at(ev["objective"], obj_states, u["used_t"])
        for kind in ("deaths", "final_blows", "deployables_destroyed"):
            for e in ev[kind]:
                e["hero"] = _hero_at(m, e["t"])
                e.pop("t_clip", None)
        out.append({"n": m["n"], **ev})
    res = {"video": sess["video"], "matches": out}
    (cache / "events.json").write_text(json.dumps(res, indent=1))
    return res
