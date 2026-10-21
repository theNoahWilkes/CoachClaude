"""Overlays that hide or fake the HUD: the Tab scoreboard and the SELECT PERK prompt.

Why (2026-10-16, Route 66 d04): with the scoreboard open the health box shows "0 | 250", and
the HUD reader believed it, so a death was dated 4 s early. With an unspent perk, the orange
SELECT PERK box sits over the player's nameplate, so the own-view check (the nameplate under
the health bar) failed for 10 s of live play and the 2 fps series, the fight and the low-HP
episode for that stretch were all missing.

Both detectors are colour fractions in fixed regions, written in game-area heights (h) so they
work on a thumbnail, a full frame or the detail still's centre crop alike:
- scoreboard: the ally panel is a block of saturated blue rows, the enemy panel of saturated
  red rows, both left of centre. Open: both fractions >= 0.5 (0.8-0.9 measured; a busy red and
  blue scene gave 0.27 / 0.23 at most over 3,300 sampled frames).
- perk prompt: saturated orange filling the nameplate area (>= 0.25; 0.3-0.65 measured with
  the prompt up, 99th percentile 0.19-0.26 without, which is the orange of the health bar
  edge, so the threshold is tight: a frame near it is checked again by HP legibility).
"""
from __future__ import annotations

import cv2
import numpy as np

from .profile import NAME_ROI

SB_BLUE = (-0.61, 0.18, 0.18, 0.47)      # x0, y0, x1, y1: x relative to the frame centre, y from the top, in h
SB_RED = (-0.61, 0.55, 0.18, 0.85)
SB_MIN = 0.5
PERK_MIN = 0.25


def _frac(img: np.ndarray, hue: tuple[int, int], s_min: int, v_min: int) -> float:
    if img.size == 0:
        return 0.0
    H, S, V = cv2.split(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))
    lo, hi = hue
    m = ((H >= lo) & (H <= hi)) if lo <= hi else ((H >= lo) | (H <= hi))
    return float((m & (S > s_min) & (V > v_min)).mean())


def _region(img: np.ndarray, h: float, cx: float, ytop: float, box: tuple) -> np.ndarray | None:
    x0, y0, x1, y1 = box
    X0, X1 = int(cx + x0 * h), int(cx + x1 * h)
    Y0, Y1 = int(ytop + y0 * h), int(ytop + y1 * h)
    Hh, W = img.shape[:2]
    cX0, cX1, cY0, cY1 = max(0, X0), min(W, X1), max(0, Y0), min(Hh, Y1)
    if (cX1 - cX0) < 0.6 * (X1 - X0) or (cY1 - cY0) < 0.6 * (Y1 - Y0):
        return None                  # the region is mostly outside this image: can't tell
    return img[cY0:cY1, cX0:cX1]


def scoreboard(img: np.ndarray, h: float | None = None, cx: float | None = None, ytop: float = 0.0) -> bool:
    """img shows a frame (or a horizontal centre crop of one): is the Tab scoreboard open?
    h = the frame's height in px, cx = the x of the frame's centre in img, ytop = the y of the
    frame's top edge in img (negative when img is a crop that starts below it)."""
    h = h or img.shape[0]
    cx = img.shape[1] / 2 if cx is None else cx
    b = _region(img, h, cx, ytop, SB_BLUE)
    r = _region(img, h, cx, ytop, SB_RED)
    if b is None or r is None:
        return False
    return _frac(b, (95, 125), 90, 60) >= SB_MIN and _frac(r, (170, 8), 90, 60) >= SB_MIN


def perk_prompt(img: np.ndarray) -> bool:
    """img = a full frame or thumbnail: is the SELECT PERK box over the nameplate?"""
    hh, w = img.shape[:2]
    x0, y0, x1, y1 = NAME_ROI
    return _frac(img[int(y0 * hh):int(y1 * hh), int(x0 * w):int(x1 * w)], (5, 22), 150, 150) >= PERK_MIN


def perk_prompt_left(left: np.ndarray, aspect: float, strip_h: float = 0.181, strip_w: float = 0.542) -> bool:
    """left = the bottom-left HUD strip (the hud_hp ROI / a detail still's left strip), which is
    strip_w game heights wide; aspect = the game area's width / height, since NAME_ROI's x is
    a fraction of the width (a wrong mapping here read the box's edge only, 2026-10-16)."""
    hh, w = left.shape[:2]
    x0, y0, x1, y1 = NAME_ROI
    top = 1.0 - strip_h
    sx = aspect / strip_w                    # width fraction -> fraction of the strip's width
    c = left[int((y0 - top) / strip_h * hh):int((y1 - top) / strip_h * hh), int(x0 * sx * w):int(min(1.0, x1 * sx) * w)]
    return _frac(c, (5, 22), 150, 150) >= PERK_MIN
