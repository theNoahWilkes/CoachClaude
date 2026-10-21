"""Objective state from the top-centre objective HUD (roiscan region "objective").

The HUD is mostly text in every mode, so one reader covers them all:

    escort (comp)  score | our time / distance | PHASE LABEL | their time / distance | score
    escort/hybrid  PHASE LABEL | time left        (QP: progress only as a bar, not read here)
    control        score | our % | point icon | their % | score
    push           our distance | clock | their distance       (+ CONTESTED! under the bar)

Allies are always on the left (blue). Pipeline per frame:
  1. top-hat on the max channel: text brighter than its own box, whatever the box colour
  2. glyph-sized components in the HUD rows locate tokens (scene clutter is dropped)
  3. each token is OCR'd from the unfiltered binary crop, so '.', ':' and '%' survive
  4. tokens are typed by regex (time, distance, percent, score) or fuzzy-matched to PHRASES,
     and put on our or their side by x relative to the centre

Only own-view frames are read: the kill cam shows the same objective from the killer's
side, colours and sides swapped. Single-frame misreads are left to the series step.
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .scan import load_index

# phrase -> (kind, side). side: the player's team is attacking / defending / None (neutral)
PHRASES = {
    "PREPARE TO ATTACK": ("setup", "attack"),
    "PREPARE YOUR DEFENSES": ("setup", "defend"),
    "ESCORT THE PAYLOAD": ("phase", "attack"),
    "STOP THE PAYLOAD": ("phase", "defend"),
    "ATTACK OBJECTIVE A": ("phase", "attack"),
    "ATTACK OBJECTIVE B": ("phase", "attack"),
    "DEFEND OBJECTIVE A": ("phase", "defend"),
    "DEFEND OBJECTIVE B": ("phase", "defend"),
    "CAPTURE THE OBJECTIVE": ("phase", None),
    "CONTESTED!": ("flag", None),
    "OVERTIME": ("flag", None),
    "POINT UNLOCKS": ("flag", None),
    "CAPTURING": ("flag", None),
}
_KEYS = {re.sub(r"[^A-Z]", "", p): p for p in PHRASES}
PHRASE_MIN = 0.75

WHITELIST = "0123456789.:%mABCDEFGHIJKLMNOPQRSTUVWXYZ!"
TOPHAT = 25              # px at 1440: wider than a glyph stroke, narrower than a box
GLYPH_H = (0.008, 0.026) # heights
GLYPH_W = 0.045
ROWS = ((5, 10_000),)    # px at 1440: OVERTIME sits above the score row, CONTESTED!/CAPTURING below
TOKEN_GAP = 0.011        # heights: glyphs closer than this belong to one token
SAMPLE_EVERY = 1.0       # s between frames read
NUM_ROW_MAX = 0.135      # heights from the top: numbers below this are scene clutter (control % row is at 0.12)
OT_SEARCH = (0.0, 0.11, -0.15, 0.15)   # y0, y1, x0, x1 (heights from top / centre) for the OVERTIME banner
OT_MIN = 0.48            # template match: overtime 0.51..1.0 (dim on bright scenes), other frames p95 0.42


def _ocr_line(b: np.ndarray) -> str:
    _, buf = cv2.imencode(".png", b)
    return subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7", "-c",
                           f"tessedit_char_whitelist={WHITELIST}"],
                          input=buf.tobytes(), capture_output=True).stdout.decode(errors="replace").strip()


def read_tokens(img: np.ndarray, gh: float) -> list[dict]:
    """img = "objective" region crop; gh = game-area height in the crop's pixel scale."""
    s = gh / 1440
    v = img.max(2)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(TOPHAT * s)),) * 2)
    th = cv2.morphologyEx(v, cv2.MORPH_TOPHAT, k)
    t, _ = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    b = (th > max(40, t)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(b)
    rows = [(r0 * s, r1 * s) for r0, r1 in ROWS]
    glyphs = [st[i] for i in range(1, n)
              if GLYPH_H[0] * gh <= st[i, 3] <= GLYPH_H[1] * gh and st[i, 2] <= GLYPH_W * gh and st[i, 4] >= 12 * s * s
              and any(r0 <= st[i, 1] <= r1 for r0, r1 in rows)]
    toks: list[dict] = []
    for c in sorted(glyphs, key=lambda c: c[0]):
        cy = c[1] + c[3] / 2
        for tk in toks:
            if abs(tk["cy"] - cy) < 0.006 * gh and c[0] - tk["x1"] <= TOKEN_GAP * gh and c[0] >= tk["x0"] - 2:
                tk["x1"] = max(tk["x1"], c[0] + c[2])
                tk["y0"], tk["y1"] = min(tk["y0"], c[1]), max(tk["y1"], c[1] + c[3])
                break
        else:
            toks.append({"x0": c[0], "x1": c[0] + c[2], "y0": c[1], "y1": c[1] + c[3], "cy": cy})
    cx = img.shape[1] / 2
    if not toks:
        return []
    crops = []
    for tk in toks:
        crop = b[max(0, tk["y0"] - 3):tk["y1"] + 4, max(0, tk["x0"] - 3):tk["x1"] + 4]
        g = cv2.resize(255 - crop * 255, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
        crops.append(cv2.copyMakeBorder(g, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255))
    texts = _ocr_stack(crops)
    out = []
    for tk, txt in zip(toks, texts):
        if txt:
            out.append({"text": txt, "x": round(((tk["x0"] + tk["x1"]) / 2 - cx) / gh, 4),
                        "y": round(tk["y0"] / gh, 4)})
    return out


def _ocr_stack(crops: list[np.ndarray]) -> list[str]:
    """One tesseract call for all tokens of a frame: crops stacked in vertical slots, words
    mapped back to tokens by their y position (tesseract's own line grouping drops or merges
    single-character lines, so line order can't be trusted). Spawn time dominates per-token calls."""
    w = max(c.shape[1] for c in crops) + 20
    rows, slots, y = [], [], 0
    for c in crops:
        rows.append(np.pad(c, ((0, 0), (0, w - c.shape[1])), constant_values=255))
        slots.append((y, y + c.shape[0]))
        y += c.shape[0]
        rows.append(np.full((40, w), 255, np.uint8))
        y += 40
    _, buf = cv2.imencode(".png", np.vstack(rows))
    out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "6", "-c",
                          f"tessedit_char_whitelist={WHITELIST}", "tsv"],
                         input=buf.tobytes(), capture_output=True).stdout.decode(errors="replace")
    words: list[list[tuple[int, str]]] = [[] for _ in crops]
    for r in csv.DictReader(io.StringIO(out), delimiter="	", quoting=csv.QUOTE_NONE):
        txt = (r.get("text") or "").strip()
        if not txt:
            continue
        cy = int(r["top"]) + int(r["height"]) / 2
        for i, (y0, y1) in enumerate(slots):
            if y0 <= cy <= y1:
                words[i].append((int(r["left"]), txt))
                break
    return ["".join(t for _, t in sorted(ws)) for ws in words]


def overtime_score(img: np.ndarray, gh: float, tpl: np.ndarray) -> float:
    """OVERTIME is italic (tesseract can't read it) but a fixed graphic: NCC on the top-hat image."""
    s = gh / 1440
    v = img.max(2)
    th = cv2.morphologyEx(v, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(TOPHAT * s)),) * 2))
    if s != 1:
        th = cv2.resize(th, None, fx=1 / s, fy=1 / s, interpolation=cv2.INTER_AREA)
    cx = th.shape[1] / 2
    y0, y1, x0, x1 = OT_SEARCH
    win = th[int(y0 * 1440):int(y1 * 1440), max(0, int(cx + x0 * 1440)):int(cx + x1 * 1440)].astype(np.float32)
    if win.shape[0] < tpl.shape[0] or win.shape[1] < tpl.shape[1]:
        return 0.0
    return float(cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED).max())


def _ot_tpl() -> np.ndarray:
    from importlib import resources
    return cv2.imread(str(resources.files("owcoach") / "assets" / "overtime.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32)


def parse(tokens: list[dict]) -> dict:
    """Tokens -> {phrases, ally/enemy: {pct, dist, time, score}, clock}."""
    st = {"phrases": [], "ally": {}, "enemy": {}, "clock": None}
    for tk in tokens:
        txt, x, y = tk["text"], tk["x"], tk["y"]
        side = "ally" if x < 0 else "enemy"
        letters = re.sub(r"[^A-Z!]", "", txt)
        if len(letters) >= 6:
            key = re.sub(r"[^A-Z]", "", letters)
            best = max(_KEYS, key=lambda k: difflib.SequenceMatcher(None, key, k).ratio())
            if difflib.SequenceMatcher(None, key, best).ratio() >= PHRASE_MIN:
                st["phrases"].append(_KEYS[best])
            continue
        if y > NUM_ROW_MAX:
            continue
        if m := re.fullmatch(r"(\d{1,3})%", txt):
            st[side]["pct"] = int(m.group(1))
        elif m := re.fullmatch(r"(\d{1,2}):(\d{2})", txt):
            secs = int(m.group(1)) * 60 + int(m.group(2))
            if abs(x) < 0.03:
                st["clock"] = secs          # push: clock in the middle
            elif abs(x) > 0.06:
                st[side]["time"] = secs     # escort time bank / QP timer right of the label
        elif m := re.fullmatch(r"(\d{1,3}\.\d{1,2})[m1lI]?", txt):
            st[side]["dist"] = float(m.group(1))
        elif re.fullmatch(r"[0-9]", txt) and abs(x) > 0.12:   # stray digits are dropped by the +1 rule
            st[side]["score"] = int(txt)
    return st


def scan_objective(cache: Path, own: np.ndarray, gh: float) -> dict:
    """Parsed state for own-view frames about SAMPLE_EVERY apart, cached to objective.json."""
    p = cache / "objective.json"
    frames = load_index(cache)["frames"]
    if p.exists():
        d = json.loads(p.read_text())
        if d.get("n_frames") == len(frames):
            return d
    picked, last = [], -1e9
    for k in np.where(own)[0]:
        if frames[k]["t"] - last >= SAMPLE_EVERY:
            picked.append(int(k))
            last = frames[k]["t"]

    ot = _ot_tpl()

    def job(k):
        img = cv2.imread(str(cache / "roi" / "objective" / frames[k]["f"]))
        toks = read_tokens(img, gh)
        return {"k": k, "t": frames[k]["t"], "tokens": toks, **parse(toks),
                "ot": round(overtime_score(img, gh, ot), 3)}

    with ThreadPoolExecutor(16) as ex:
        states = list(ex.map(job, picked))
    d = {"n_frames": len(frames), "states": states}
    p.write_text(json.dumps(d))
    return d


# --- series ---------------------------------------------------------------------------
STABLE = 4               # reads a score / side must hold before it counts
# which numbers each mode actually prints (QP escort/hybrid show progress only as a bar)
FIELDS = {("control", None): ("pct",), ("push", None): ("dist",),
          ("escort", "competitive"): ("dist",), ("hybrid", "competitive"): ("dist",)}
MONOTONIC = ("pct",)     # push robots move both ways; escort distance resets per round (handled by bounds)
FLAG_GAP = 5.0           # s: flag sightings closer than this are one stretch
SMOOTH = 5               # reads in the rolling median for %, distance


def _runs(ts: list[float], gap: float, min_n: int = 1) -> list[dict]:
    runs: list[list[float]] = []
    for t in ts:
        if runs and t - runs[-1][-1] <= gap:
            runs[-1].append(t)
        else:
            runs.append([t])
    return [{"from": round(r[0], 2), "to": round(r[-1], 2)} for r in runs if len(r) >= min_n]


def _stable(seq: list[tuple[float, object]]) -> list[tuple[float, object]]:
    """(t, value) reads -> changes that held for STABLE reads in a row."""
    out, cand, n = [], None, 0
    for t, v in seq:
        if v is None:
            continue
        if out and v == out[-1][1]:
            cand, n = None, 0
            continue
        if cand is not None and v == cand[1]:
            n += 1
        else:
            cand, n = (t, v), 1
        if n >= STABLE:
            out.append(cand)
            cand, n = None, 0
    return out


def _median(seq: list[tuple[float, float | None]]) -> list[tuple[float, float]]:
    vals = [(t, v) for t, v in seq if v is not None]
    out = []
    for i, (t, _) in enumerate(vals):
        w = [v for _, v in vals[max(0, i - SMOOTH // 2):i + SMOOTH // 2 + 1]]
        out.append((t, float(np.median(w))))
    return out


SCORE_WINDOW = 15.0      # s: a new score counts once it's read STABLE times within this window


def _score_steps(seq: list[tuple[float, int | None]]) -> list[dict]:
    """Score reads -> steps. Scores only go up by one. The lone digit misreads often (a 1 reads as
    4, 5, 7 or nothing), so requiring STABLE reads in a row dated steps 10-18 s late (Havana,
    2026-10-13 m04). Now a step also counts when the next value is read STABLE times within
    SCORE_WINDOW, more than half the reads there. It's dated to the first read of it after the
    last read of the old value, at most SCORE_WINDOW back (a longer back-date crossed two minutes
    of noise on Gibraltar).
    TODO: date control captures from pct reaching 100 (Nepal 2026-10-13 m02 reads 11:30 by pct,
    12:31 here), escort checkpoints from the distance / time bank."""
    reads = [(t, v) for t, v in seq if v is not None]
    steps, cur, last_cur = [], None, -1e9
    for i, (t, v) in enumerate(reads):
        if cur is not None and v == cur:
            last_cur = t
            continue
        if not (cur is None and v == 0 or cur is not None and v == cur + 1):
            continue
        win = [vv for tt, vv in reads[i:] if tt <= t + SCORE_WINDOW]
        in_a_row = all(vv == v for _, vv in reads[i:i + STABLE]) and len(reads) >= i + STABLE
        if not in_a_row and (win.count(v) < STABLE or win.count(v) * 2 <= len(win)):
            continue
        first = next(tt for tt, vv in reads if tt > max(last_cur, t - SCORE_WINDOW) and vv == v)
        steps.append({"t": round(first, 2), "score": v})
        cur, last_cur = v, t
    return steps


def match_objective(m: dict, states: list[dict]) -> dict:
    S = [x for x in states if m["start"] <= x["t"] <= m["end"]]
    side_of = {p: v[1] for p, v in PHRASES.items() if v[1]}
    sides = _stable([(x["t"], next((side_of[p] for p in x["phrases"] if p in side_of), None)) for x in S])
    if m.get("mode") == "control":   # both teams capture; "PREPARE TO ATTACK" says nothing about sides
        sides = []
    setups = _runs([x["t"] for x in S if any(PHRASES[p][0] == "setup" for p in x["phrases"])], 20.0, 2)
    rounds = []
    for r in setups:
        side = next((sd for t, sd in reversed(sides) if t <= r["to"] + 30), None)
        rounds.append({"t": r["from"], "side": side})
    overtime = _runs([x["t"] for x in S if x["ot"] >= OT_MIN], FLAG_GAP, 2)
    contested = _runs([x["t"] for x in S if "CONTESTED!" in x["phrases"]], FLAG_GAP)
    score = {sd: _score_steps([(x["t"], x[sd].get("score")) for x in S]) for sd in ("ally", "enemy")}
    keys = FIELDS.get((m.get("mode"), m.get("queue")), FIELDS.get((m.get("mode"), None), ()))
    bounds = [r["t"] for r in rounds] + [m["end"]]
    series = {}
    for key in keys:
        for sd in ("ally", "enemy"):
            v = _median([(x["t"], x[sd].get(key)) for x in S])
            if key in MONOTONIC:   # within a round, capture % and payload distance never go back
                out, peak, bi = [], -1.0, 0
                for t, y in v:
                    while bi < len(bounds) - 1 and t >= bounds[bi]:
                        peak, bi = -1.0, bi + 1
                    peak = max(peak, y)
                    out.append((t, peak))
                v = out
            if len(v) >= 10:
                series[f"{sd}_{key}"] = [(round(t, 1), round(y, 2)) for t, y in v[::5]]
    return {"objective": {"sides": [{"t": round(t, 2), "side": sd} for t, sd in sides], "rounds": rounds,
                          "overtime": overtime, "contested": contested, "score": score, "series": series}}


def context_at(obj: dict, states: list[dict], tt: float) -> dict:
    """The objective situation at one moment: side, overtime, contested, latest numbers."""
    side = next((x["side"] for x in reversed(obj["sides"]) if x["t"] <= tt), None)
    near = [x for x in states if tt - 4 <= x["t"] <= tt + 0.5]
    nums = {}
    for sd in ("ally", "enemy"):
        for key in ("pct", "dist"):
            vals = [x[sd][key] for x in near if x[sd].get(key) is not None]
            if vals:
                nums[f"{sd}_{key}"] = round(float(np.median(vals)), 1)
    return {"side": side,
            "overtime": any(r["from"] - 1 <= tt <= r["to"] + 1 for r in obj["overtime"]),
            "contested": any(r["from"] - 2 <= tt <= r["to"] + 2 for r in obj["contested"]),
            **nums}
