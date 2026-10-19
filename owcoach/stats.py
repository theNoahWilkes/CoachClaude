"""Per-game stats from the final TAB scoreboard (scoreboard_final.jpg), normalized per 10 min.

The scoreboard lists all ten players, ordered tank, DPS, DPS, support, support, with
E / A / D / DMG / H / MIT for the whole match *up to the moment TAB was pressed*. Its match
clock (TIME m:ss) is that moment's game time, so it's the denominator for per-10 rates.

Both are read with digit templates rather than tesseract: the scoreboard digits touch each
other and are low-contrast (assets/score_digits.npz, bootstrapped from tesseract reads whose
digit count matched), and tesseract confuses the clock's italic 1/4, 3/5, 6/9
(assets/clock_digits.npz, from hand-read clocks). Checked: 2 scoreboards cell by cell (120/120)
plus Havana by eye; clock reads over all 150 TAB presses never run backwards.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np

# Cell geometry in game-area heights, x from the centre (measured at 3456x1440, 21:9).
COLS = {"E": (-0.208, 0.020), "A": (-0.161, 0.020), "D": (-0.114, 0.020),
        "DMG": (-0.040, 0.036), "H": (0.046, 0.036), "MIT": (0.130, 0.036)}   # centre, half-width
ROWS = {"ally": (0.204, 0.265, 0.326, 0.388, 0.448), "enemy": (0.580, 0.641, 0.702, 0.763, 0.823)}
ROW_HALF = 0.016
ROLES = ("tank", "dps", "dps", "support", "support")
HIGHLIGHT_X = (-0.235, 0.165)    # the row strip compared for the player's lighter highlight


def _cell(img: np.ndarray, yc: float, xc: float, hw: float) -> np.ndarray:
    H, W = img.shape[:2]
    cx = W / 2
    c = img[int((yc - ROW_HALF) * H):int((yc + ROW_HALF) * H),
            int(cx + (xc - hw) * H):int(cx + (xc + hw) * H)]
    g = cv2.resize(c.min(2), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # white digits on blue / red / highlighted rows: the min channel is high only on the white
    # text, then Otsu -> black digits on white (tesseract misses low-contrast single digits)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return cv2.copyMakeBorder(b, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


GLYPH = (20, 28)                 # w, h each digit is normalized to
GLYPH_MIN = 0.75                 # template correlation below this -> unreadable cell


def _components(b: np.ndarray) -> list[np.ndarray]:
    """Binarized cell (black digits on white) -> ink blobs left to right, commas dropped.
    A blob can hold several touching digits; read_number splits those."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(255 - b)
    comps = [st[i] for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 15]
    if not comps:
        return []
    hmax = max(c[cv2.CC_STAT_HEIGHT] for c in comps)
    return [255 - b[c[1]:c[1] + c[3], c[0]:c[0] + c[2]]
            for c in sorted(comps, key=lambda c: c[cv2.CC_STAT_LEFT]) if c[3] >= 0.6 * hmax]


def _templates() -> dict[str, np.ndarray]:
    from importlib import resources
    return dict(np.load(str(resources.files("owcoach") / "assets" / "score_digits.npz")))


def _match(ink: np.ndarray, tpl: dict[str, np.ndarray]) -> tuple[str, float]:
    g = cv2.resize(ink, GLYPH, interpolation=cv2.INTER_AREA).astype(np.float32)
    v = (g - g.mean()).ravel()
    best = ("", -1.0)
    for d, t in tpl.items():
        u = (t - t.mean()).ravel()
        c = float(v @ u / (np.linalg.norm(v) * np.linalg.norm(u) + 1e-6))
        if c > best[1]:
            best = (d, c)
    return best


def _read_blob(ink: np.ndarray, tpl: dict[str, np.ndarray], depth: int = 0) -> list[tuple[str, float]]:
    """One blob -> digits. Touching digits are split at the column that makes both halves match best."""
    d = _match(ink, tpl)
    h, w = ink.shape
    if d[1] >= GLYPH_MIN or depth >= 3 or w < 0.7 * h:
        return [d]
    best, best_score = [d], d[1]
    for x in range(int(0.25 * h), w - int(0.25 * h)):
        L = _read_blob(_trim(ink[:, :x]), tpl, depth + 1)
        R = _read_blob(_trim(ink[:, x:]), tpl, depth + 1)
        sc = min(c for _, c in L + R)
        if sc > best_score:
            best, best_score = L + R, sc
    return best


def _trim(ink: np.ndarray) -> np.ndarray:
    cols = np.where(ink.max(0) > 0)[0]
    return ink[:, cols.min():cols.max() + 1] if len(cols) else ink


def read_number(b: np.ndarray, tpl: dict[str, np.ndarray]) -> int | None:
    blobs = _components(b)
    if not blobs or len(blobs) > 6:
        return None
    digits = [d for ink in blobs for d in _read_blob(ink, tpl)]
    if len(digits) > 6 or any(c < GLYPH_MIN for _, c in digits):
        return None
    return int("".join(d for d, _ in digits))


def read_scoreboard(img: np.ndarray) -> dict:
    """Full-res TAB frame (game area) -> {"rows": [...10...], "player": index or None}."""
    H, W = img.shape[:2]
    tpl = _templates()
    rows: dict[tuple, dict] = {}
    for team, ys in ROWS.items():
        for i, yc in enumerate(ys):
            r = rows.setdefault((team, i), {"team": team, "slot": i, "role": ROLES[i]})
            for k in COLS:
                r[k] = read_number(_cell(img, yc, *COLS[k]), tpl)
    out = list(rows.values())
    # the player's own row is drawn lighter than the other four ally rows
    cx = W / 2
    light = [float(img[int((y - ROW_HALF) * H):int((y + ROW_HALF) * H),
                       int(cx + HIGHLIGHT_X[0] * H):int(cx + HIGHLIGHT_X[1] * H)].mean())
             for y in ROWS["ally"]]
    srt = sorted(light)
    player = int(np.argmax(light)) if srt[-1] - srt[-2] > 6 else None
    return {"rows": out, "player": player, "row_light": [round(x, 1) for x in light]}


CLOCK_GLYPH = (16, 30)


def clock_glyphs(hdr: np.ndarray) -> list[np.ndarray]:
    """Full-res TAB header crop (segment.TAB_HEADER_ROI) -> the TIME clock's digit glyphs.
    The digits are orange italics: mask the orange, undo the slant, split into blobs (the
    colon's dots are dropped by height)."""
    h = hdr.shape[0]
    line = hdr[int(h * .38):int(h * .82)]
    hsv = cv2.cvtColor(line, cv2.COLOR_BGR2HSV)
    orange = ((hsv[..., 0] >= 3) & (hsv[..., 0] <= 25) & (hsv[..., 1] > 110) & (hsv[..., 2] > 120)).astype(np.uint8) * 255
    cols = np.where(orange.sum(0) > 255)[0]
    if len(cols) == 0:
        return []
    x0, x1 = max(0, cols.min() - 8), cols.max() + 8
    ink = orange[:, x0:x1]
    ink = cv2.warpAffine(ink, np.float32([[1, 0.25, 0], [0, 1, 0]]), (ink.shape[1] + 20, ink.shape[0]))
    n, lab, st, _ = cv2.connectedComponentsWithStats((ink > 127).astype(np.uint8))
    comps = [st[i] for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 10]
    if not comps:
        return []
    hmax = max(c[3] for c in comps)
    return [cv2.resize(ink[c[1]:c[1] + c[3], c[0]:c[0] + c[2]], CLOCK_GLYPH, interpolation=cv2.INTER_AREA).astype(np.float32)
            for c in sorted(comps, key=lambda c: c[0]) if c[3] >= 0.6 * hmax]


def read_clock(hdr: np.ndarray) -> int | None:
    """TAB header -> match clock in seconds (templates: assets/clock_digits.npz)."""
    from importlib import resources
    tpl = dict(np.load(str(resources.files("owcoach") / "assets" / "clock_digits.npz")))
    gs = clock_glyphs(hdr)
    if len(gs) not in (3, 4):
        return None
    ds = []
    for g in gs:
        v = (g - g.mean()).ravel()
        sc = {d: float(v @ (t - t.mean()).ravel() / (np.linalg.norm(v) * np.linalg.norm(t - t.mean()) + 1e-6))
              for d, t in tpl.items()}
        d = max(sc, key=sc.get)
        if sc[d] < GLYPH_MIN:
            return None
        ds.append(d)
    mm, ss = int("".join(ds[:-2])), int("".join(ds[-2:]))
    return mm * 60 + ss if ss < 60 else None


def final_clock(cache: Path, m: dict) -> float | None:
    """Match clock (s) on the final scoreboard. The clock pauses during setup, between rounds and
    at the end, so it's read, not inferred; other frames of the same TAB press are the fallback."""
    from .scan import grab_frame
    from .segment import TAB_HEADER_ROI
    t = m.get("final_tab_t")
    if t is None:
        return None
    press = [x for x in m.get("tab_times", []) if abs(x - t) <= 3.0]
    tries = [t] + sorted(press, key=lambda x: abs(x - t))
    with tempfile.TemporaryDirectory() as td:
        for k, tt in enumerate(dict.fromkeys(tries)):
            p = grab_frame(cache, tt, Path(td) / f"h{k}.png", roi=TAB_HEADER_ROI)
            c = read_clock(cv2.imread(str(p)))
            if c is not None:
                return float(c)   # a neighbouring frame of the same press; the clock is frozen by then
    return None


STAT_KEYS = ("E", "A", "D", "DMG", "H", "MIT")


def game_stats(cache: Path, m: dict, gdir: Path, time_dead_s: float) -> dict | None:
    """The stats block for packet.json, or None without a final scoreboard."""
    sb_path = gdir / "scoreboard_final.jpg"
    if not sb_path.exists():
        return None
    sb = read_scoreboard(cv2.imread(str(sb_path)))
    clock = final_clock(cache, m)
    per10 = (lambda v: round(v * 600 / clock, 1) if v is not None and clock else None)
    out = {"clock_s": clock, "clock": clock and f"{int(clock // 60)}:{int(clock % 60):02d}",
           "player_row": sb["player"], "scoreboard": sb["rows"]}
    me = sb["rows"][sb["player"]] if sb["player"] is not None else None
    if me:
        out["player"] = {k: me[k] for k in STAT_KEYS}
        out["player_per10"] = {k: per10(me[k]) for k in STAT_KEYS}
        mate = next((r for r in sb["rows"] if r["team"] == "ally" and r["role"] == me["role"] and r is not me), None)
        if mate:
            out["teammate_same_role_per10"] = {k: per10(mate[k]) for k in STAT_KEYS}
        foes = [r for r in sb["rows"] if r["team"] == "enemy" and r["role"] == me["role"]]
        out["enemy_same_role_per10"] = [{k: per10(r[k]) for k in STAT_KEYS} for r in foes]
    if clock:
        out["time_dead_s"] = time_dead_s
        out["time_dead_pct"] = round(100 * time_dead_s / clock, 1)
    return out
