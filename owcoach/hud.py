"""Read the player's HUD from the detail stills: current / max HP (bottom left) and the ability
squares (bottom right): ready, cooling (with the countdown), or blocked.

Why: HP and cooldowns are the facts every death note cites, and reading them off images one
frame at a time was the slowest, most expensive and least reliable part of coaching (an LLM
reader turned 210 into 10, and called an on-cooldown dash "pressed late"). Both are fixed-font
digits at fixed HUD spots, which template matching reads for free.

Everything is measured at 1440p and scaled by the game-area height, so it works on other heights.
A detail still holds the HUD strip at native resolution under the centre crop (packet._detail).

HP:  white digits on a translucent box. Current HP is the big font (~28 px), max HP the small
     grey font (~22 px) to its right; the "|" between them is often too faint to see. An adaptive
     threshold on the min channel isolates the glyphs whatever is behind the box; the scoreboard
     digit templates (assets/score_digits.npz) read them: 98 % of frames over 65 deaths, max HP
     right in every death. Noah's checks: the HP-hits-0 frame precedes the banner anchor by up to ~1 s.
Abilities: squares of SQ px at PITCH px spacing on a fixed row, in a per-hero layout. The states
     look nothing alike (ready = translucent white; cooling = dark grey filling with orange from
     the bottom, white italic countdown; blocked = red outline + slash, no fill), so squares are
     found by geometry: two continuous vertical edges SQ apart, repeated at PITCH, plus the row's
     top and bottom edges (the per-frame comb fits vote on the grid phase; every grid position is
     then scored over the clear frames). The layout is learned from a hero's first death (all of its frames
     vote) and cached in the profile (hud_layouts.json), then read at fixed slots. Countdown
     digits are italic, so they have their own templates (assets/cooldown_digits.npz,
     bootstrapped from 1,400 harvested glyphs, 99.9 % self-match).
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .stats import GLYPH, _match, _templates

REF_H = 1440                 # px: every constant below is at this game-area height
STRIP_H = 0.181              # HUD strip height under the detail crop, in game-area heights (packet.DETAIL_HUD)
LEFT_W, RIGHT_W = 0.542, 0.547
# HP line: rows / columns of the left strip (at REF_H)
HP_BAND, HP_X = (0, 70), (180, 720)
TOPHAT_K, INK = 31, 40
BIG, SMALL = (25, 34), (18, 24)      # glyph heights: current HP, max HP
GLYPH_W = (7, 30)
DIGIT_MIN = 0.35                     # weak digits stay inside a word; confidence is reported
# ability squares: right strip (at REF_H)
SQ, PITCH = 85, 105
ROW = (38, 123)
X_MAX = 560
SLOT_MIN = 0.45                      # per-slot geometry score to count as a slot
CD_MIN = 0.6                         # countdown digit template score


# --- HP ---------------------------------------------------------------------------------------

def _binarize(line: np.ndarray, k: int, ink: int) -> np.ndarray:
    g = line.min(2)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return (cv2.morphologyEx(g, cv2.MORPH_TOPHAT, se) > ink).astype(np.uint8) * 255


def _glyphs(b: np.ndarray, tpl: dict, s: float, hmin: float, hmax: float, wmin: float, wmax: float, score_min: float):
    n, lab, st, _ = cv2.connectedComponentsWithStats(b)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 30 * s * s or not (hmin * s <= h <= hmax * s) or not (wmin * s < w <= wmax * s):
            continue
        ink = ((lab == i).astype(np.uint8) * 255)[y:y + h, x:x + w]
        d, sc = _match(ink, tpl)
        if sc >= score_min:
            out.append((int(x), int(y), int(w), int(h), d[0], float(sc)))
    return sorted(out, key=lambda g: g[0])


def _word(gs, gap_frac: float = 0.5):
    """Longest run of glyphs with small gaps -> (value, min score, glyphs), or None."""
    if not gs:
        return None
    H = float(np.median([g[3] for g in gs]))
    runs, cur = [], [gs[0]]
    for g in gs[1:]:
        if g[0] - (cur[-1][0] + cur[-1][2]) > gap_frac * H:
            runs.append(cur); cur = [g]
        else:
            cur.append(g)
    runs.append(cur)
    best = max(runs, key=lambda r: (len(r), -r[0][0]))
    return int("".join(g[4] for g in best)), min(g[5] for g in best), best


def read_hp(left: np.ndarray, H: int, tpl: dict | None = None) -> tuple[int | None, int | None, float]:
    """Left HUD strip -> (current, max, confidence). The strip is STRIP_H * H tall."""
    s = H / REF_H
    tpl = tpl or _templates()
    y0, y1 = int(HP_BAND[0] * s), int(HP_BAND[1] * s)
    x0, x1 = int(HP_X[0] * s), int(HP_X[1] * s)
    line = left[y0:y1, x0:x1]
    if line.size == 0:
        return None, None, 0.0
    # adaptive threshold on the min channel (white text is the only thing high in all channels):
    # a bright background behind the translucent box defeats a global or top-hat threshold
    # (98 % of frames read over 65 deaths, against 93 % for a top-hat)
    b = cv2.adaptiveThreshold(line.min(2), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
                              max(3, int(TOPHAT_K * s) | 1), -20)
    gs = _glyphs(b, tpl, s, SMALL[0], BIG[1], GLYPH_W[0], GLYPH_W[1], DIGIT_MIN)
    big = [g for g in gs if BIG[0] * s <= g[3] <= BIG[1] * s]
    cur = _word(big)
    if cur is None:
        return None, None, 0.0
    right = cur[2][-1][0] + cur[2][-1][2]
    small = [g for g in gs if SMALL[0] * s <= g[3] <= SMALL[1] * s and g[0] > right]
    mx = _word(small)
    return cur[0], (mx[0] if mx else None), round(cur[1], 2)


def clean_hp(series: list[tuple[float, int | None, int | None, float]]) -> tuple[int | None, list]:
    """Per-death cleanup. Returns (max HP = mode of the max reads, [[dt, hp, conf], ...]) with
    reads over 1.6 x max, lone spikes, and dropped leading digits (210 read as 10) set to None."""
    mx = [m for _, _, m, _ in series if m is not None]
    mode = max(set(mx), key=mx.count) if mx else None
    vals = [c if (c is None or not mode or c <= 1.6 * mode) else None for _, c, _, _ in series]
    out = despike(vals)
    return mode, [[dt, v, conf if v is not None else 0.0] for (dt, _, _, conf), v in zip(series, out)]


def despike(vals: list) -> list:
    """A read that disagrees with both neighbours while they agree with each other, or that has
    fewer digits than both (a dropped leading digit: 250 read as 2), is set to None."""
    out = list(vals)
    for i in range(1, len(vals) - 1):
        a, b, c = vals[i - 1], vals[i], vals[i + 1]
        if b is None or a is None or c is None:
            continue
        if abs(a - c) <= 30 and abs(b - a) > 60 and abs(b - c) > 60:
            out[i] = None
        elif len(str(b)) < len(str(a)) and len(str(b)) < len(str(c)) and abs(a - c) <= 60:
            out[i] = None
    return out


# --- abilities --------------------------------------------------------------------------------

_cd_tpl: dict | None = None


def _cooldown_templates() -> dict:
    global _cd_tpl
    if _cd_tpl is None:
        from importlib import resources
        _cd_tpl = dict(np.load(str(resources.files("owcoach") / "assets" / "cooldown_digits.npz")))
    return _cd_tpl


def _edge_profile(right: np.ndarray, s: float):
    g = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3))
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    r0, r1 = int(ROW[0] * s), int(ROW[1] * s)
    m = int(6 * s)
    vline = (gx[r0 + m:r1 - m] > 40).mean(0)
    top = gy[max(0, r0 - 3):r0 + 4].max(0); bot = gy[r1 - 4:r1 + 3].max(0)
    hcov = ((top > 40) & (bot > 40)).astype(np.float32)
    return cv2.blur(vline.reshape(1, -1), (1, 3)).ravel(), cv2.blur(hcov.reshape(1, -1), (1, 9)).ravel()


def _slot_score(prof, x0: int, s: float) -> float:
    vline, hcov = prof
    W = len(vline)
    sq, g = int(SQ * s), int(15 * s)
    a, b = x0, x0 + sq
    if b + 3 >= W or a + sq // 2 < 0:
        return -1.0
    e = [vline[b]] + ([vline[a]] if a >= 0 else [])
    gut = [vline[b + 3:b + 3 + g].mean() if b + 3 + g < W else 0.0] + ([vline[max(0, a - g):a].mean()] if a > g else [])
    return float(np.mean(e) + 0.5 * hcov[max(0, a) + int(10 * s):b - int(10 * s)].mean() - np.mean(gut))


def _comb_fit(prof, s: float):
    """Best (score, k, x0) of k slots at PITCH from offset x0 (k = 2..4)."""
    vline, hcov = prof
    W = len(vline)
    sq, pitch, xmax = int(SQ * s), int(PITCH * s), int(X_MAX * s)
    best = (0.0, 0, 0)
    for k in (2, 3, 4):
        for x0 in range(-sq // 2, min(W - sq, xmax) - (k - 1) * pitch):
            sc = [_slot_score(prof, x0 + j * pitch, s) for j in range(k)]
            if min(sc) < 0:
                continue
            v = float(np.mean(sc) - 0.03 * (4 - k))
            if v > best[0]:
                best = (v, k, x0)
    return best


def learn_slots(rights: list[np.ndarray], H: int) -> list[float]:
    """Slot centres (px from the strip's left edge, at this H) from all of a death's right strips:
    the comb fit of each frame votes on the grid phase, then every grid position is scored over
    all frames and the longest contiguous run of good ones is the layout."""
    s = H / REF_H
    sq, pitch, xmax = int(SQ * s), int(PITCH * s), int(X_MAX * s)
    profs = [_edge_profile(r, s) for r in rights]
    fits = [(f, p) for f, p in ((_comb_fit(p, s), p) for p in profs) if f[0] >= 0.5]
    if len(fits) < 5:                      # frames that show the squares clearly, from any death
        return []
    # candidate grid phases: clusters of the fits' phases (a fit aligned on a gutter instead of a
    # square gives a second cluster ~20 px off). Each candidate's grid positions are scored over
    # the clear frames; the phase whose contiguous run of good slots scores best wins.
    phases = np.array([(x0 + sq / 2) % pitch for (_, _, x0), _ in fits])
    dist = lambda a, b: np.minimum(np.abs(a - b), pitch - np.abs(a - b))
    cands = []
    for c in sorted(set(np.round(phases / (4 * s)) * 4 * s)):
        n = int(np.sum(dist(phases, c) <= 4 * s))
        if n >= 0.2 * len(phases) and all(dist(np.array([c]), k)[0] > 8 * s for k, _ in cands):
            cands.append((float(np.median(phases[dist(phases, c) <= 4 * s])), n))
    best, best_key = [], (0, 0.0)
    for ph, _ in cands:
        grid = [int(round(ph - sq / 2 + j * pitch)) for j in range(-1, 6)]
        grid = [x for x in grid if -sq // 2 < x < xmax]
        # 75th percentile over frames: a slot drawn as a thin outline (blocked) for most of a
        # window still scores on the frames where it has a fill
        # ... and the best of +-2 px: the edge-continuity score is sensitive to a 1 px shift
        sc = {x: max(float(np.percentile([_slot_score(p, x + dx, s) for _, p in fits], 75)) for dx in (-2, -1, 0, 1, 2)) for x in grid}
        runs, cur = [], []
        for x in grid:
            if sc[x] >= SLOT_MIN:
                cur.append(x)
            else:
                runs.append(cur); cur = []
        runs.append(cur)
        run = max(runs, key=len)
        key = (len(run), float(np.mean([sc[x] for x in run])) if run else 0.0)
        if key > best_key:
            best, best_key = run, key
    return [x + sq / 2 for x in best] if len(best) >= 2 else []


def read_number(box: np.ndarray, s: float) -> tuple[int | None, float]:
    tpl = _cooldown_templates()
    b = _binarize(box, max(3, int(TOPHAT_K * s) | 1), 50)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b)
    gl = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 80 * s * s or not (24 * s <= h <= 60 * s) or not (8 * s < w <= 45 * s):
            continue
        ink = ((lab == i).astype(np.uint8) * 255)[y:y + h, x:x + w]
        g = cv2.resize(ink, GLYPH, interpolation=cv2.INTER_AREA).astype(np.float32)
        v = (g - g.mean()).ravel(); nv = np.linalg.norm(v) + 1e-6
        best = ("", -1.0)
        for k, t in tpl.items():
            u = (t - t.mean()).ravel()
            c = float(v @ u / (nv * np.linalg.norm(u) + 1e-6))
            if c > best[1]:
                best = (k[0], c)
        if best[1] >= CD_MIN:
            gl.append((int(x), best[0], best[1]))
    gl.sort()
    if not gl:
        return None, 0.0
    return int("".join(d for _, d, _ in gl)), min(c for _, _, c in gl)


SLASH_MIN = 8.0              # brightness excess of the anti-diagonal band that marks a blocked slot's slash


def _slash(V: np.ndarray) -> float:
    """How much brighter the top-right-to-bottom-left diagonal is than the rest of the square:
    a blocked slot's red slash (+28 measured), absent on an in-use icon (-12 to -18)."""
    h, w = V.shape
    yy, xx = np.mgrid[0:h, 0:w]
    band = np.abs(xx / w + yy / h - 1.0) < 0.06
    Vf = V.astype(np.float32)
    return float(Vf[band].mean() - Vf[~band].mean()) if band.any() and (~band).any() else 0.0


def read_slot(right: np.ndarray, cx: float, H: int) -> dict:
    """One slot -> {"state": ready | cooling | blocked | active | hidden, "n": countdown if shown}.
    blocked = red square with the diagonal slash (can't be used); active = the icon swapped to
    its in-use form on a red/orange tint without the slash (Katashiro's doll out and the RETURN
    prompt up, a platform placed, ...): the ability is in progress and may be re-pressable."""
    s = H / REF_H
    sq = int(SQ * s)
    x0 = int(round(cx - sq / 2)); xa, xb = max(0, x0), min(right.shape[1], x0 + sq)
    box = right[int(ROW[0] * s):int(ROW[1] * s), xa:xb]
    if box.size == 0:
        return {"state": "hidden"}
    Hh, S, V = cv2.split(cv2.cvtColor(box, cv2.COLOR_BGR2HSV))
    white = float(((S < 60) & (V > 150)).mean())
    orange = float(((Hh >= 5) & (Hh <= 25) & (S > 120) & (V > 120)).mean())
    red = float((((Hh <= 5) | (Hh >= 170)) & (S > 120) & (V > 100)).mean())
    n, ns = read_number(box, s)
    if n is not None and ns >= 0.75:
        state = "cooling"
    elif white >= 0.30:
        state = "ready"
    elif red >= 0.06:
        state = "blocked" if _slash(V) >= SLASH_MIN else "active"
    elif orange >= 0.10:
        state = "cooling"
    else:
        state = "hidden"
    rec = {"state": state}
    if state in ("cooling", "blocked") and n is not None:
        rec["n"] = n
    return rec


# --- per death --------------------------------------------------------------------------------

def strips(still: np.ndarray, H: int) -> tuple[np.ndarray, np.ndarray]:
    """A detail still -> (left HUD strip, right HUD strip), as packet._detail laid them out."""
    hh, lw, rw = round(STRIP_H * H), round(LEFT_W * H), round(RIGHT_W * H)
    hud = still[still.shape[0] - hh:]
    return hud[:, :lw], hud[:, hud.shape[1] - rw:]


def layouts_path() -> Path:
    from .profile import profile_dir
    return profile_dir() / "hud_layouts.json"


def load_layouts() -> dict:
    p = layouts_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_layouts(layouts: dict) -> None:
    p = layouts_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(layouts, indent=1), encoding="utf-8")


def load_stills(pdir: Path, frames: list[dict], H: int) -> list[tuple[float, np.ndarray, np.ndarray, np.ndarray | None]]:
    """(dt, left strip, right strip, centre crop) for each detail still of a death, in time
    order. The centre crop is the still above the HUD strips (packet.DETAIL_CENTRE of the
    frame, at native scale when the frame is 1440 px tall), used for the overlay detectors."""
    out = []
    hh = round(STRIP_H * H)
    for f in frames:
        if f.get("kind") != "detail":
            continue
        im = cv2.imread(str(pdir / f["file"]))
        if im is not None:
            centre = im[:im.shape[0] - hh] if im.shape[0] > hh else None
            out.append((f["dt"], *strips(im, H), centre))
    return sorted(out, key=lambda t: t[0])


def hero_layout(rights: list[np.ndarray], H: int, cached: list[float] | None) -> list[float]:
    """Slot centres in game-area heights from the right edge, learned from every right strip of
    a hero in this game and merged with the cached layout: the longer one wins when they agree
    on the slots they share (a single death can miss a slot whose square is faint)."""
    rw = round(RIGHT_W * H)
    learned = [round((rw - x) / H, 4) for x in learn_slots(rights, H)] if rights else []
    if not cached:
        return learned
    if not learned:
        return cached
    sub = lambda a, b: all(any(abs(x - y) < 0.01 for y in b) for x in a)
    agree = sub(cached, learned) or sub(learned, cached)
    return learned if agree and len(learned) > len(cached) else cached


def _smooth_abilities(abil: list[list]) -> list[list]:
    """Per slot: majority state over a 5-frame window, and the countdown carried along a cooling
    run when a frame's number failed to read or disagrees with the count-down (1 per second)."""
    if not abil:
        return abil
    n = len(abil[0]) - 1
    out = [[row[0]] + [dict(r) for r in row[1:]] for row in abil]
    for j in range(1, n + 1):
        states = [row[j]["state"] for row in abil]
        for i in range(len(abil)):
            win = [st for st in states[max(0, i - 2):i + 3] if st != "hidden"]
            if win:
                out[i][j]["state"] = max(set(win), key=win.count)
        # each run of cooling/blocked frames: a countdown falls 1 per second, so every good read
        # implies the same end time. The median end is the anchor; a read off it by more than
        # 1.5 s is a misread (a dropped leading digit: 14 read as 4, 2026-10-16 Havana d08) and
        # is replaced. Anchoring on the first read, as before, carried a bad first read along.
        i = 0
        while i < len(abil):
            if out[i][j]["state"] not in ("cooling", "blocked"):
                out[i][j].pop("n", None)
                i += 1
                continue
            k = i
            while k < len(abil) and out[k][j]["state"] in ("cooling", "blocked"):
                k += 1
            reads = [(q, abil[q][j]["n"]) for q in range(i, k) if abil[q][j].get("n") is not None and abil[q][j]["n"] <= 30]
            if reads:
                ends = sorted(abil[q][0] + n for q, n in reads)
                med = ends[len(ends) // 2]
                for q in range(i, k):
                    n_read = abil[q][j].get("n")
                    if n_read is not None and n_read <= 30 and abs(abil[q][0] + n_read - med) <= 1.5:
                        out[q][j]["n"] = n_read
                    else:
                        out[q][j]["n"] = max(0, int(round(med - abil[q][0])))
            else:
                for q in range(i, k):
                    out[q][j].pop("n", None)
            i = k
    return out


def death_hud(stills: list[tuple[float, np.ndarray, np.ndarray]], slots_h: list[float], H: int,
              tpl: dict | None = None, aspect: float = 3456 / 1440) -> dict:
    """One death's HUD: HP series, max HP, when HP first read 0, and each slot's state per frame
    (smoothed), with a paragraph summary for the readers."""
    if not stills:
        return {}
    tpl = tpl or _templates()
    rw = round(RIGHT_W * H)
    from .overlay import perk_prompt_left, scoreboard
    covered = {dt: (centre is not None and scoreboard(centre, H, centre.shape[1] / 2, -(H - centre.shape[0]) / 2))
               for dt, left, _, centre in stills}
    # the scoreboard fades in over ~0.5 s and the health box already reads 0 while it does
    on = sorted(dt for dt, c in covered.items() if c)
    for dt in covered:
        if any(0 < o - dt <= 0.5 for o in on):
            covered[dt] = True
    perk = {dt: perk_prompt_left(left, aspect) for dt, left, _, _ in stills}
    hp_raw = [(dt, None, None, 0.0) if covered[dt] else (dt, *read_hp(left, H, tpl)) for dt, left, _, _ in stills]
    hp_max, hp = clean_hp(hp_raw)
    zero = next((dt for dt, v, c in hp if v == 0 and c >= 0.7), None)
    slots_px = [rw - off * H for off in slots_h]
    abil = _smooth_abilities([[dt] + ([{"state": "hidden"}] * len(slots_px) if covered[dt] else [read_slot(r, cx, H) for cx in slots_px])
                              for dt, _, r, _ in stills])
    notices = []
    for what, flags in (("scoreboard", covered), ("perk_prompt", perk)):
        run = None
        for dt in sorted(flags):
            if flags[dt]:
                if run and dt - run[1] <= 0.6:
                    run[1] = dt
                else:
                    if run:
                        notices.append(run)
                    run = [dt, dt, what]
        if run:
            notices.append(run)
    notices = [{"from": a, "to": b, "what": w} for a, b, w in sorted(notices)]
    return {
        "hp_max": hp_max,
        "hp": hp,
        "hp_zero_dt": zero,
        "hp_read": sum(v is not None for _, v, _ in hp),
        "slots": slots_h,
        "abilities": abil,
        "notices": notices,
        "summary": summarize(hp, hp_max, zero, abil) + "".join(
            f" {w['what'].replace('_', ' ').capitalize()} {w['from']:+.1f} to {w['to']:+.1f} s." for w in notices),
    }


def summarize(hp: list, hp_max: int | None, zero: float | None, abil: list) -> str:
    """One paragraph the readers can quote: HP every 0.5 s (median of the reads within 0.2 s),
    then each slot's runs of state with the countdown's start and end."""
    parts = []
    good = [(dt, v) for dt, v, c in hp if v is not None and c >= 0.7]
    pts = []
    for k in range(-30, 1, 5):
        dt = k / 10
        w = [v for t, v in good if abs(t - dt) <= 0.2]
        if w:
            pts.append(f"{dt:+.1f}s:{int(np.median(w))}")
    if pts:
        parts.append(f"HP (max {hp_max}): " + " ".join(pts) + ".")
    if zero is not None:
        parts.append(f"HP first reads 0 at {zero:+.1f} s.")
    nslots = len(abil[0]) - 1 if abil else 0
    for j in range(nslots):
        runs = []
        for dt, r in ((row[0], row[j + 1]) for row in abil):
            if r["state"] == "hidden":
                continue
            if runs and runs[-1]["state"] == r["state"]:
                runs[-1]["to"] = dt
                if "n" in r:
                    runs[-1]["ns"].append(r["n"])
            else:
                runs.append({"state": r["state"], "from": dt, "to": dt, "ns": [r["n"]] if "n" in r else []})
        runs = [x for x in runs if round((x["to"] - x["from"]) * 10) >= 2] or runs[:1]
        if not runs:
            continue
        if len(runs) == 1 and runs[0]["state"] == "ready":
            parts.append(f"Slot {j + 1}: ready throughout.")
            continue
        bits = []
        for x in runs:
            span = f"{x['from']:+.1f} to {x['to']:+.1f} s"
            if x["ns"]:
                bits.append(f"{x['state']} {x['ns'][0]}->{x['ns'][-1]} ({span})")
            else:
                bits.append(f"{x['state']} ({span})")
        parts.append(f"Slot {j + 1}: " + ", ".join(bits) + ".")
    return " ".join(parts)


# --- whole game (from hudscan's hud.json) -----------------------------------------------------

LOW_FRAC = 0.5               # "low" = under half of max HP
FIGHT_GAP = 8.0              # s: activity closer than this is one fight
FIGHT_MIN = 4.0              # s: shorter stretches aren't fights
HP_ACTIVE = 10               # HP change between keyframes that counts as activity
EVENT_BEFORE, EVENT_AFTER = 6.0, 2.0   # s: the fight window a kill / death / ult opens on its own


def _state_str(slot) -> str:
    return slot[0] + (" " + str(slot[1]) if slot[1] is not None else "")


def game_hud(rows: list[dict], start: float, event_ts: list[float], death_ts: list[float],
             clock) -> dict:
    """One match's HUD rows (own-view keyframes, 2 fps) -> the series, fights, every slot's
    presses (with context), low-HP episodes (with every slot's state at the start and what was
    pressed before), and per-hero per-slot stats. Facts only: which slot is an escape, and
    whether it could have been used, is the coach's call from its own knowledge of the kit (and
    the hero note from `owcoach hero`, if one exists)."""
    rows = [r for r in rows if r.get("hp") is not None or r.get("slots")]
    if not rows:
        return {}
    # max HP per hero = the mode of its reads (a lone misread like 2507 would make everything "low")
    maxes: dict[str, int] = {}
    for hero in {r.get("hero") or "" for r in rows}:
        mx = [r["max"] for r in rows if (r.get("hero") or "") == hero and r["max"]]
        if mx:
            maxes[hero] = max(set(mx), key=mx.count)
    for r in rows:
        r["max_read"] = r["max"]
        r["max"] = maxes.get(r.get("hero") or "")
        # a frame whose max HP didn't read as the hero's max is a dimmed or occluded HUD (spawn
        # room, setup, menus): its current HP read isn't trusted either ("250 | 250" dimmed
        # read as "2 | 2")
        if r["hp"] is not None and (r["max_read"] != r["max"] or r["hp"] > 1.6 * r["max"]):
            r["hp"] = None
    conf_idx = [i for i, r in enumerate(rows) if r["hp"] is not None and r["conf"] >= 0.7]
    cleaned = despike([rows[i]["hp"] for i in conf_idx])
    for i, v in zip(conf_idx, cleaned):
        rows[i]["hp"] = v
    good = [r for r in rows if r["hp"] is not None and r["conf"] >= 0.7 and r["max"]]
    hp_of = lambda r: r["hp"] if (r["hp"] is not None and r["conf"] >= 0.7) else None
    series = [[round(r["t"] - start, 1), hp_of(r), [_state_str(sl) for sl in r["slots"]]] for r in rows]
    notices = []                       # runs of frames with the scoreboard open / the perk prompt up
    for what in ("scoreboard", "perk_prompt"):
        run = None
        for r in rows:
            if what in (r.get("notices") or []):
                if run and r["t"] - run[1] <= 1.1:
                    run[1] = r["t"]
                else:
                    if run:
                        notices.append(run)
                    run = [r["t"], r["t"], what]
        if run:
            notices.append(run)
    notices = [{"from": round(a - start, 1), "to": round(b - start, 1), "clock": clock(a), "what": w}
               for a, b, w in sorted(notices)]

    # fights: HP changes, plus kills / deaths / ults, merged. An event opens a window of its
    # own (EVENT_BEFORE s before it, EVENT_AFTER after), so a death with no HP rows around it
    # (HUD hidden by the scoreboard, own view lost) is still a fight and the presses before it
    # aren't labelled travel (Route 66 d04, 2026-10-16).
    acts = [[e - EVENT_BEFORE, e + EVENT_AFTER] for e in event_ts]
    for a, b in zip(good, good[1:]):
        if abs(b["hp"] - a["hp"]) >= HP_ACTIVE and b["t"] - a["t"] <= 2.0:
            acts.append([b["t"], b["t"]])
    acts.sort()
    spans, fcur = [], None
    for a0, a1 in acts:
        if fcur and a0 - fcur[1] <= FIGHT_GAP:
            fcur[1] = max(fcur[1], a1)
        else:
            if fcur:
                spans.append(fcur)
            fcur = [a0, a1]
    if fcur:
        spans.append(fcur)
    spans = [(a - 2, b + 2) for a, b in spans if b - a >= FIGHT_MIN]
    fights = [{"from": clock(a), "to": clock(b), "from_t": round(a - start, 1), "to_t": round(b - start, 1)} for a, b in spans]
    in_fight = lambda ts: any(a <= ts <= b for a, b in spans)

    # presses, every slot: a steady "ready" (>= 2 frames) -> steady not-ready (>= 2 frames).
    # context: travel = outside a fight; fight = in a fight at or above half HP; low = in a fight under half.
    # Not "engage": it says nothing about which way the press went, and a Fade out of a 3v5 at
    # 217 HP was read as going in (Runasapi 2026-10-27).
    presses = []
    by_hero: dict[str, list[dict]] = {}
    for r in rows:
        by_hero.setdefault(r.get("hero") or "", []).append(r)
    for hero, hrows in by_hero.items():
        nslots = max((len(r["slots"]) for r in hrows), default=0)
        for j in range(nslots):
            seq = [(r, r["slots"][j]) for r in hrows if j < len(r["slots"]) and r["slots"][j][0] != "hidden"]
            for i in range(2, len(seq) - 1):
                a, b, c, d = seq[i - 2][1][0], seq[i - 1][1][0], seq[i][1][0], seq[i + 1][1][0]
                if a == b == "ready" and c != "ready" and d != "ready":
                    r = seq[i][0]
                    hp = hp_of(r)
                    ctx = "unknown" if hp is None else ("low" if hp < LOW_FRAC * r["max"] else ("fight" if in_fight(r["t"]) else "travel"))
                    # the countdown it starts from (the first number read in this cooling run)
                    first_n = next((seq[k][1][1] for k in range(i, min(i + 4, len(seq))) if seq[k][1][1] is not None), None)
                    presses.append({"t": round(r["t"] - start, 1), "clock": clock(r["t"]), "hero": hero or None,
                                    "slot": j + 1, "hp": hp, "max": r["max"], "context": ctx, "cooldown_from": first_n})
    presses.sort(key=lambda x: x["t"])

    # low-HP episodes, with every slot's state at the start and the last press of each slot before it
    episodes, cur = [], None
    for r in good:
        low = r["hp"] < LOW_FRAC * r["max"]
        if low and cur is None:
            cur = {"from_t": r["t"], "to_t": r["t"], "min_hp": r["hp"], "max": r["max"], "hero": r.get("hero"),
                   "slots_at_start": [_state_str(sl) for sl in r["slots"]]}
        elif low:
            cur["to_t"] = r["t"]
            cur["min_hp"] = min(cur["min_hp"], r["hp"])
        elif cur is not None and r["t"] - cur["to_t"] > 1.5:
            episodes.append(cur)
            cur = None
    if cur is not None:
        episodes.append(cur)
    out_eps = []
    for e in episodes:
        died = any(e["from_t"] - 1 <= d <= e["to_t"] + 2.5 for d in death_ts)
        if e["to_t"] - e["from_t"] < 0.75 and not died:
            continue                        # one keyframe: a misread, not an episode
        t0, t1 = e["from_t"] - start, e["to_t"] - start
        before = {}
        for j, st in enumerate(e["slots_at_start"], 1):
            if not st.startswith("ready"):
                last = [p for p in presses if p["hero"] == e["hero"] and p["slot"] == j and p["t"] < t0]
                if last:
                    lp = last[-1]
                    before[str(j)] = {"pressed_s_before": round(t0 - lp["t"], 1), "hp": lp["hp"], "context": lp["context"]}
        out_eps.append({"from": round(t0, 1), "to": round(t1, 1), "clock": clock(e["from_t"]), "hero": e["hero"],
                        "min_hp": e["min_hp"], "max": e["max"], "slots_at_start": e["slots_at_start"],
                        "last_press_before": before,
                        "pressed_in": [{"t": p["t"], "slot": p["slot"], "hp": p["hp"]} for p in presses
                                       if p["hero"] == e["hero"] and t0 - 1 <= p["t"] <= t1 + 1],
                        "outcome": "died" if died else "recovered"})

    # stats: overall, and per hero per slot
    n_good = len(good)
    low_n = sum(1 for r in good if r["hp"] < LOW_FRAC * r["max"])
    stats = {
        "time_under_half_pct": round(100 * low_n / n_good, 1) if n_good else None,
        "low_episodes": len(out_eps),
        "low_episodes_died": sum(e["outcome"] == "died" for e in out_eps),
        "hp_read_pct": round(100 * n_good / len(rows), 1),
        "by_hero": {},
    }
    for hero, hrows in by_hero.items():
        if not hero:
            continue
        nslots = max((len(r["slots"]) for r in hrows), default=0)
        eps = [e for e in out_eps if e["hero"] == hero]
        slots = []
        for j in range(1, nslots + 1):
            ps = [p for p in presses if p["hero"] == hero and p["slot"] == j]
            cds = [p["cooldown_from"] for p in ps if p["cooldown_from"]]
            hp = [p["hp"] for p in ps if p["hp"] is not None]
            slots.append({"slot": j, "presses": len(ps),
                          "by_context": {c: sum(1 for p in ps if p["context"] == c) for c in ("travel", "fight", "low", "unknown")},
                          "press_hp_median": int(np.median(hp)) if hp else None,
                          "cooldown_s": max(set(cds), key=cds.count) if cds else None,
                          "low_episodes_ready_at_start": sum(1 for e in eps if j <= len(e["slots_at_start"]) and e["slots_at_start"][j - 1].startswith("ready")),
                          "low_episodes_not_ready_at_start": sum(1 for e in eps if j <= len(e["slots_at_start"]) and not e["slots_at_start"][j - 1].startswith("ready"))})
        stats["by_hero"][hero] = {"low_episodes": len(eps), "low_died": sum(e["outcome"] == "died" for e in eps), "slots": slots}
    return {"series": series, "notices": notices, "fights": fights, "presses": presses, "low_episodes": out_eps, "stats": stats}
