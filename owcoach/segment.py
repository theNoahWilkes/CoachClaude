"""Pass 2: classify cached frames and find match boundaries.

Per-frame signals (all cheap, computed once and cached to features.npy):

  hud  - hero-agnostic HUD detector. Three fixed anchors in the bottom-left
         (the "+"/HP readout, the health pip row, your nameplate bar) are
         matched as gradient templates. The block slides sideways a little
         depending on the hero's portrait frame, so each anchor is searched
         over a horizontal window and the score is the best pair of anchors
         that agree on the same offset.
  tab  - TAB scoreboard: blue team rows over red team rows in fixed boxes.

A frame is "in match" if either fires. Runs of in-match frames are merged
across short gaps (deaths, round swaps), and anything longer than MERGE_GAP
of neither is between matches (POTG, accolades, progression, queue).

Then, per match, the slow stuff runs only where it's needed:
  result  - OCR of the VICTORY/DEFEAT banner just after the match ends
  map     - OCR of the TAB header ("ESCORT | ROUTE 66"), grabbed at full res
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

import cv2
import numpy as np

from .heroes import TAB_HERO_ROI, build_refs, match_heroes, read_tab_hero, snap_words, tab_reads
from .scan import frame_path, grab_frame, load_index
from .sheet import fmt_t

# --- tunables (pixel coords are in the 1280-wide cropped thumbnail space) ---------
HUD_THRESH = 0.40      # min template score for an anchor pair
TAB_THRESH = 0.45      # min(blue_frac, red_frac) for a TAB scoreboard
DX_AGREE = 3           # px: anchors must agree on horizontal offset
MERGE_GAP = 75.0       # s: shorter gaps stay inside one match
MIN_MATCH = 120.0      # s: drop shorter runs (stray detections)
ROUND_GAP = 200.0      # s: an unresolved gap shorter than this is a round swap, not a new match
SEARCH_X, SEARCH_Y = 36, 8

REF_Y0 = 420           # assets/hud_ref.png == frame[420:534, 0:300]
ANCHORS = {
    "plus": (84, 434, 140, 452),
    "pips": (84, 450, 176, 472),
    "name": (84, 474, 204, 500),
}
TAB_BLUE = (270, 100, 690, 240)   # x0, y0, x1, y1
TAB_RED = (270, 300, 690, 440)
TAB_HEADER_ROI = (0.60, 0.0, 1.0, 0.075)   # fractions of game area: "[OBJECTIVE - QUEUE] MODE | MAP  TIME"
HEADER_CLOCK_X = 0.88                       # text left of this; the orange clock is found by colour
BANNER_ROI = (0.30, 0.36, 0.70, 0.60)


def _grad(g: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


class HudDetector:
    def __init__(self, ref_path: Path | None = None):
        if ref_path is None:
            ref_path = Path(str(resources.files("owcoach") / "assets" / "hud_ref.png"))
        ref = cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE)
        if ref is None:
            raise FileNotFoundError(ref_path)
        self.tmpl = {k: _grad(ref[y0 - REF_Y0:y1 - REF_Y0, x0:x1])
                     for k, (x0, y0, x1, y1) in ANCHORS.items()}

    def score(self, img: np.ndarray) -> tuple[float, int]:
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        res = []
        for k, (x0, y0, x1, y1) in ANCHORS.items():
            xa = max(0, x0 - SEARCH_X)
            win = _grad(g[y0 - SEARCH_Y:y1 + SEARCH_Y, xa:x1 + SEARCH_X])
            r = cv2.matchTemplate(win, self.tmpl[k], cv2.TM_CCOEFF_NORMED)
            _, v, _, loc = cv2.minMaxLoc(r)
            res.append((float(v), loc[0] - (x0 - xa)))
        best, dx = 0.0, 0
        for i in range(len(res)):
            for j in range(i + 1, len(res)):
                (va, da), (vb, db) = res[i], res[j]
                if abs(da - db) <= DX_AGREE and min(va, vb) > best:
                    best, dx = min(va, vb), round((da + db) / 2)
        return best, dx


def tab_score(img: np.ndarray) -> float:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    x0, y0, x1, y1 = TAB_BLUE
    b = hsv[y0:y1, x0:x1]
    x0, y0, x1, y1 = TAB_RED
    r = hsv[y0:y1, x0:x1]
    bf = ((b[..., 0] > 90) & (b[..., 0] < 115) & (b[..., 1] > 80) & (b[..., 2] > 90)).mean()
    rf = (((r[..., 0] < 8) | (r[..., 0] > 170)) & (r[..., 1] > 100) & (r[..., 2] > 70)).mean()
    return float(min(bf, rf))


def banner_prefilter(img: np.ndarray) -> bool:
    """Big saturated text on a mostly dark centre: worth OCR-ing for a result banner."""
    H, W = img.shape[:2]
    x0, y0, x1, y1 = BANNER_ROI
    hsv = cv2.cvtColor(img[int(H * y0):int(H * y1), int(W * x0):int(W * x1)], cv2.COLOR_BGR2HSV)
    sat = ((hsv[..., 1] > 120) & (hsv[..., 2] > 120)).mean()
    dark = (hsv[..., 2] < 60).mean()
    return 0.02 < sat < 0.35 and dark > 0.45


# --- OCR ------------------------------------------------------------------------------
def _ocr(img: np.ndarray, psm: int = 7, scale: float = 2.0) -> str:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if scale != 1:
        g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, buf = cv2.imencode(".png", g)
    out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", str(psm), "-l", "eng"],
                         input=buf.tobytes(), capture_output=True)
    return out.stdout.decode(errors="replace").strip()


def _fuzzy_word(text: str, words: list[str], cutoff: float = 0.7) -> str | None:
    for tok in re.findall(r"[A-Za-z]{4,}", text.upper()):
        m = difflib.get_close_matches(tok, words, n=1, cutoff=cutoff)
        if m:
            return m[0]
    return None


def read_result(img: np.ndarray) -> str | None:
    H, W = img.shape[:2]
    x0, y0, x1, y1 = BANNER_ROI
    roi = img[int(H * y0):int(H * y1), int(W * x0):int(W * x1)]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    ink = np.where((hsv[..., 1] > 120) & (hsv[..., 2] > 120), 0, 255).astype(np.uint8)
    for variant in (ink, roi):
        r = _fuzzy_word(_ocr(variant, psm=7), ["VICTORY", "DEFEAT", "DRAW"])
        if r:
            return r.lower()
    return None


MODE_WORDS = ["ESCORT", "HYBRID", "CONTROL", "PUSH", "FLASHPOINT", "CLASH"]
# map list for snapping OCR output; unknown names still come through as read
MAPS = ["Antarctic Peninsula", "Blizzard World", "Busan", "Circuit Royal", "Colosseo",
        "Dorado", "Eichenwalde", "Esperança", "Havana", "Hollywood", "Ilios", "Junkertown",
        "Grímsvötn", "King's Row", "Lijiang Tower", "Midtown", "Nepal", "New Junk City", "New Queen Street",
        "Numbani", "Oasis", "Paraíso", "Rialto", "Route 66", "Runasapi", "Samoa", "Shambali Monastery",
        "Suravasa", "Watchpoint: Gibraltar", "Aatlis", "Hanaoka", "Throne of Anubis"]


def _norm(s: str) -> str:
    import unicodedata
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s.lower())
                  .encode("ascii", "ignore").decode())


def _snap_map(raw: str) -> str:
    table = {_norm(m): m for m in MAPS}
    hit = difflib.get_close_matches(_norm(raw), list(table), n=1, cutoff=0.6)
    return table[hit[0]] if hit else raw.title()


def _find_map(txt: str) -> str | None:
    """Find a known map name anywhere in OCR text (exact, then fuzzy over same-length windows)."""
    nt = _norm(txt)
    best, best_r = None, 0.0
    for m in MAPS:
        nm = _norm(m)
        if nm in nt:
            return m
        for i in range(0, max(1, len(nt) - len(nm) + 1)):
            r = difflib.SequenceMatcher(None, nm, nt[i:i + len(nm)]).ratio()
            if r > best_r:
                best, best_r = m, r
    return best if best_r >= 0.82 else None


def read_tab_header(img: np.ndarray) -> tuple[str | None, str | None, str | None, bool]:
    """Full-res TAB header crop -> (mode, map, match_clock, is_competitive).

    QP:   [icon] ESCORT | ROUTE 66                         TIME: m:ss
    Comp: ESCORT THE PAYLOAD - COMPETITIVE | WATCHPOINT: GIBRALTAR  TIME: m:ss
    """
    H, W = img.shape[:2]
    line = img[int(H * .38):int(H * .82)]
    left = 255 - cv2.cvtColor(line[:, :int(W * HEADER_CLOCK_X)], cv2.COLOR_BGR2GRAY)
    txt = _ocr(left, psm=7, scale=1.0).upper()
    mode = _fuzzy_word(txt, MODE_WORDS, cutoff=0.75)
    comp = _fuzzy_word(txt, ["COMPETITIVE"], cutoff=0.75) is not None
    mp = _find_map(txt)
    if mp is None and "|" in txt:
        m = re.match(r"\s*([A-Z0-9'’ÁÉÍÓÖÚÇ:\. -]+)", txt.split("|", 1)[1])
        if m:
            words = [w for w in m.group(1).split() if len(w) > 1 or w.isdigit()]
            if words:
                mp = _snap_map(" ".join(words))

    # match clock: orange italic digits -> mask, deskew, vote across a few shears
    hsv = cv2.cvtColor(line, cv2.COLOR_BGR2HSV)
    orange = (hsv[..., 0] >= 3) & (hsv[..., 0] <= 25) & (hsv[..., 1] > 110) & (hsv[..., 2] > 120)
    cols = np.where(orange.sum(0) > 1)[0]
    if len(cols) == 0:
        return (mode.lower() if mode else None), mp, None, comp
    x0, x1 = max(0, cols.min() - 8), min(W, cols.max() + 8)
    ink = np.where(orange[:, x0:x1], 0, 255).astype(np.uint8)
    votes: dict[str, int] = {}
    for k in (0.25, 0.15, 0.35):
        sh = cv2.warpAffine(ink, np.float32([[1, k, 0], [0, 1, 0]]),
                            (ink.shape[1] + 20, ink.shape[0]), borderValue=255)
        sh = cv2.copyMakeBorder(sh, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        sh = cv2.resize(sh, None, fx=2, fy=2)
        _, buf = cv2.imencode(".png", sh)
        r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7", "-c",
                            "tessedit_char_whitelist=0123456789:"],
                           input=buf.tobytes(), capture_output=True).stdout.decode().strip()
        if re.fullmatch(r"\d{1,2}:[0-5]\d", r):
            votes[r] = votes.get(r, 0) + 1
    clock = max(votes, key=votes.get) if votes else None
    return (mode.lower() if mode else None), mp, clock, comp


RESULT_WORDS = ["VICTORY", "DEFEAT", "DRAW"]


def _gray_inv(img: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    H, W = img.shape[:2]
    x0, y0, x1, y1 = roi
    return 255 - cv2.cvtColor(img[int(H * y0):int(H * y1), int(W * x0):int(W * x1)],
                              cv2.COLOR_BGR2GRAY)


CHAT_ROI = (0.25, 0.80, 0.75, 0.985)
ACCOLADE_ROI = (0.0, 0.0, 0.30, 0.13)   # "VICTORY / MAP / MATCH TIME" on the accolades screen


def read_chat_result(img: np.ndarray) -> str | None:
    """'[ATHENA] Victory.' -- the announcer line survives even when TAB hides the banner."""
    txt = _ocr(_gray_inv(img, CHAT_ROI), psm=6, scale=3)
    m = re.search(r"ATHENA\W{0,3}\s*([A-Za-z]{4,})", txt, re.I)
    if m:
        hit = difflib.get_close_matches(m.group(1).upper(), RESULT_WORDS, n=1, cutoff=0.7)
        return hit[0].lower() if hit else None
    return None


def read_accolade_result(img: np.ndarray) -> str | None:
    r = _fuzzy_word(_ocr(_gray_inv(img, ACCOLADE_ROI), psm=6, scale=2), RESULT_WORDS, cutoff=0.75)
    return r.lower() if r else None


def _bright_ocr(img: np.ndarray, roi: tuple[float, float, float, float]) -> str:
    H, W = img.shape[:2]
    x0, y0, x1, y1 = roi
    g = cv2.cvtColor(img[int(H * y0):int(H * y1), int(W * x0):int(W * x1)], cv2.COLOR_BGR2GRAY)
    return _ocr(np.where(g > 170, 0, 255).astype(np.uint8), psm=6, scale=3)


POST_TABS_ROI = (0.0, 0.0, 0.25, 0.07)    # "COMPETITIVE  SUMMARY  REWARDS" / "SUMMARY  REWARDS"
POST_TITLE_ROI = (0.0, 0.07, 0.25, 0.25)  # "DEFEAT" (comp rank page) / "DOCTRINE 7 minutes" (summary)


def has_post_tabs(img: np.ndarray) -> bool:
    """Cheap thumbnail check for the post-match tab bar."""
    return re.search(r"SUMMAR|REWAR|RFWAR", _bright_ocr(img, POST_TABS_ROI).upper()) is not None


def post_screen(img: np.ndarray) -> tuple[str, str] | None:
    """Post-match screen -> ('rank' | 'summary', title text) or None.

    Comp shows a COMPETITIVE/SUMMARY/REWARDS tab bar and opens on the rank page
    (title = result). QP opens on SUMMARY (title = hero + minutes played).
    Hero select also says COMPETITIVE, but it has no tab bar.
    """
    tabs = _bright_ocr(img, POST_TABS_ROI).upper()
    if not re.search(r"SUMMAR|REWAR|RFWAR", tabs):
        return None
    title = " ".join(_bright_ocr(img, POST_TITLE_ROI).split())
    if _fuzzy_word(title, RESULT_WORDS, 0.7):  # only the comp rank page has a result title
        return "rank", title
    return "summary", title


MAP_MODE = {"Antarctic Peninsula": "control", "Busan": "control", "Ilios": "control",
            "Lijiang Tower": "control", "Nepal": "control", "Oasis": "control", "Samoa": "control",
            "Circuit Royal": "escort", "Dorado": "escort", "Havana": "escort", "Junkertown": "escort",
            "Rialto": "escort", "Route 66": "escort", "Shambali Monastery": "escort",
            "Watchpoint: Gibraltar": "escort", "Grímsvötn": "escort",
            "Blizzard World": "hybrid", "Eichenwalde": "hybrid", "Hollywood": "hybrid",
            "King's Row": "hybrid", "Midtown": "hybrid", "Numbani": "hybrid", "Paraíso": "hybrid",
            "Colosseo": "push", "Esperança": "push", "New Queen Street": "push", "Runasapi": "push",
            "New Junk City": "flashpoint", "Suravasa": "flashpoint", "Aatlis": "flashpoint",
            "Hanaoka": "clash", "Throne of Anubis": "clash"}


# --- segmentation -----------------------------------------------------------------------
def compute_features(cache: Path) -> np.ndarray:
    """(N, 4) array of [t, hud, dx, tab], cached to features.npy."""
    fp = cache / "features.npy"
    idx = load_index(cache)
    if fp.exists():
        f = np.load(fp)
        if f.shape == (len(idx["frames"]), 4):
            return f
    det = HudDetector()
    rows = []
    for e in idx["frames"]:
        im = cv2.imread(str(frame_path(cache, e)))
        s, dx = det.score(im)
        rows.append((e["t"], s, dx, tab_score(im)))
    f = np.array(rows, dtype=np.float64)
    np.save(fp, f)
    return f


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def segment(cache: Path) -> dict:
    from .profile import load as load_profile
    load_profile()   # fail before the slow work, not after
    idx = load_index(cache)
    frames = idx["frames"]
    feats = compute_features(cache)
    t, hud, tab = feats[:, 0], feats[:, 1], feats[:, 3]
    is_hud, is_tab = hud >= HUD_THRESH, tab >= TAB_THRESH
    live = is_hud | is_tab
    dur = idx["probe"]["duration"]
    img = lambda k: cv2.imread(str(frame_path(cache, frames[k])))  # noqa: E731
    near = lambda tt: int(np.abs(t - tt).argmin())                 # noqa: E731

    # 1) runs of in-match frames, merged across short gaps
    spans: list[list[int]] = []
    for a, b in _runs(live):
        if b == a and not is_tab[a]:
            continue  # single-frame HUD blip
        if spans and t[a] - t[spans[-1][1]] < MERGE_GAP:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    spans = [s for s in spans if t[s[1]] - t[s[0]] >= 20]

    def find_result(a: int, b: int, post_hi: float):
        """-> (result, banner_k, end_t, source, post_screens) for the span a..b."""
        window = lambda lo, hi, step: list(range(max(a, near(lo)), near(hi) + 1))[::step]  # noqa: E731
        result, banner_k, end_t, src = None, None, float(t[b]), None
        #   a) the VICTORY/DEFEAT banner itself (POTG shows a HUD, so look well before t[b])
        for k in window(t[b] - 60, t[b] + 30, 1):
            if is_tab[k] or not banner_prefilter(im := img(k)):
                continue
            if r := read_result(im):
                result, banner_k, end_t, src = r, k, float(t[k] + 4), "banner"
                break
        #   b) announcer chat line -- also pins the real end when TAB was held over the banner
        if result is None:
            for k in window(t[b] - 60, t[b] + 30, 2):
                if r := read_chat_result(img(k)):
                    result, end_t, src = r, min(float(t[b]), float(t[k]) + 2), "chat"
                    break
        #   c) accolades screen header
        if result is None:
            for k in [k for k in window(t[b], post_hi, 4) if not is_hud[k]]:
                if r := read_accolade_result(img(k)):
                    result, src = r, "accolades"
                    break
        # post-match screens: QP Summary (hero, E/A/D, damage, healing, mitigation) / comp rank
        post: dict[str, tuple[float, str]] = {}
        for k in [k for k in window(t[b], post_hi, 4) if not is_hud[k] and not is_tab[k]]:
            if has_post_tabs(img(k)):
                # read it from a full-res grab a few seconds in (counters done animating)
                tt = float(t[min(k + 6, len(t) - 1)])
                with tempfile.TemporaryDirectory() as td:
                    fr = cv2.imread(str(grab_frame(cache, tt, Path(td) / "p.png", width=1280)))
                if ps := post_screen(fr):
                    post[ps[0]] = (tt, ps[1])
                break
        if result is None and "rank" in post:
            r = _fuzzy_word(post["rank"][1], RESULT_WORDS, 0.75)
            result, src = (r.lower(), "rank_screen") if r else (None, None)
        return result, banner_k, end_t, src, post

    # 2) a span only ends a match if something says the match ended. Comp round swaps
    #    (side switch + ~80 s hero select) look like a gap but have no result/post screens.
    resolved = []
    i = 0
    while i < len(spans):
        a, b = spans[i]
        nxt = spans[i + 1][0] if i + 1 < len(spans) else None
        post_hi = min(t[nxt] if nxt is not None else dur, t[b] + 150)
        res = find_result(a, b, post_hi)
        if res[0] is None and not res[4] and nxt is not None and t[nxt] - t[b] < ROUND_GAP:
            spans[i][1] = spans[i + 1][1]
            del spans[i + 1]
            continue
        resolved.append((a, b, res))
        i += 1

    matches = []
    for a, b, (result, banner_k, end_t, src, post) in resolved:
        if end_t - t[a] < MIN_MATCH:
            continue
        # 3) TAB snapshots: last one in the match is the final scoreboard
        tabs = [k for k in range(a, b + 1) if is_tab[k]]
        last_tab = tabs[-1] if tabs else None

        flags = []
        if t[a] < 5:
            flags.append("starts_mid_match")
        if result is None and dur - t[b] < 10:
            flags.append("recording_ends_mid_match")
        if src != "banner" and last_tab is not None and end_t - t[last_tab] < 6:
            flags.append("tab_held_at_end")

        matches.append({
            "n": len(matches) + 1,
            "start": round(float(t[a]), 2), "end": round(end_t, 2),
            "start_hms": fmt_t(t[a]), "end_hms": fmt_t(end_t),
            "duration": round(end_t - float(t[a]), 1),
            "result": result, "hero_final": None, "queue": None, "mode": None, "map": None, "final_clock": None,
            "hud_fraction": round(float(is_hud[a:b + 1].mean()), 3),
            "tab_times": [round(float(t[k]), 2) for k in tabs],
            "final_tab_t": round(float(t[last_tab]), 2) if last_tab is not None else None,
            "banner_t": round(float(t[banner_k]), 2) if banner_k is not None else None,
            "result_source": src,
            "summary_t": round(post["summary"][0], 2) if "summary" in post else None,
            "summary_title": post["summary"][1] if "summary" in post else None,
            "rank_t": round(post["rank"][0], 2) if "rank" in post else None,
            "flags": flags,
        })

    # 4) map/mode from the TAB header, read off full-res frames (a few tries per match)
    with tempfile.TemporaryDirectory() as td:
        for m in matches:
            if m["final_tab_t"] is not None:
                p = grab_frame(cache, m["final_tab_t"], Path(td) / "hero.png", roi=TAB_HERO_ROI)
                m["hero_final"] = read_tab_hero(cv2.imread(str(p)))
            tries = m["tab_times"][-1:] + m["tab_times"][:-1][::-1]
            seen = set()
            for tt in tries:
                if len(seen) >= 4:
                    break
                if any(abs(tt - s) < 5 for s in seen):
                    continue
                seen.add(tt)
                p = grab_frame(cache, tt, Path(td) / "hdr.png", roi=TAB_HEADER_ROI)
                mode, mp, clock, comp = read_tab_header(cv2.imread(str(p)))
                if comp:
                    m["queue"] = "competitive"
                if tt == m["final_tab_t"]:
                    m["final_clock"] = clock
                m["mode"] = m["mode"] or mode
                m["map"] = m["map"] or mp
                if m["mode"] and m["map"]:
                    break
            m["mode"] = m["mode"] or MAP_MODE.get(m["map"])
            hm = re.search(r"([A-Z][A-Z.:'\-]+(?: [A-Z][A-Z.:'\-]+)?)\s+(\d+)\s*M",
                           (m.get("summary_title") or "").upper())
            m["summary_hero"] = {"hero": snap_words(hm.group(1)) or hm.group(1).title(),
                                 "minutes": int(hm.group(2))} if hm else None
            if m["queue"] is None:
                m["queue"] = "competitive" if m.get("rank_t") else ("quickplay" if m.get("summary_t") else None)

    # 5) heroes over time: TAB side-panel reads label the HUD portrait, the portrait gives the timeline
    for m in matches:
        m["tab_hero_reads"] = tab_reads(cache, m["tab_times"])
    refs = build_refs(cache, frames, t, hud, [r for m in matches for r in m["tab_hero_reads"]])
    own = np.zeros(len(t), bool)    # frames showing the player's own view (not kill cam / spectate)
    for m in matches:
        segs, views, own_ks = match_heroes(cache, frames, t, hud, m["start"], m["end"], m["tab_hero_reads"], refs)
        own[own_ks] = True
        m["hero_final"] = snap_words(m["hero_final"]) or m["hero_final"]
        m["heroes"], m["views"] = segs, views
        played: dict[str, float] = {}
        for sg in segs:
            if sg["hero"]:
                played[sg["hero"]] = played.get(sg["hero"], 0) + sg["seconds"]
        m["hero_main"] = max(played, key=played.get) if played else None
        m["role"] = next((sg["role"] for sg in segs if sg["hero"] == m["hero_main"]), None)
        if len(played) > 1:
            m["flags"].append("multi_hero")

    np.save(cache / "own_view.npy", own)
    out = {"video": idx["video"], "duration": dur, "matches": matches,
           "params": {"HUD_THRESH": HUD_THRESH, "TAB_THRESH": TAB_THRESH,
                      "MERGE_GAP": MERGE_GAP, "ROUND_GAP": ROUND_GAP, "MIN_MATCH": MIN_MATCH}}
    (cache / "matches.json").write_text(json.dumps(out, indent=1))

    labels = {}
    for k, e in enumerate(frames):
        lab = "TAB" if is_tab[k] else ("HUD" if is_hud[k] else "")
        for mm in matches:
            if mm["start"] <= t[k] <= mm["end"]:
                lab = f"M{mm['n']} {lab}"
        labels[e["f"]] = lab.strip()
    (cache / "states.json").write_text(json.dumps({"labels": labels}))
    return out
