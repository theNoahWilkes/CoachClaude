"""Egomotion: which way the player turned and moved, from optical flow between the 0.1 s
detail stills of a death.

Why (labels/deaths.md, 2026-10-16): the readers' clearest misses were movement. "Stayed in
the same spot" when the player flew through a tunnel; "dashed into the Roadhog" when they
broke for their Zarya; a Dash at a stairwell missed entirely. Stills are snapshots, so the
rubric made movement "inference however many frames you read". Flow between frames 0.1 s
apart is not: it gives the camera's turn and, through parallax, the body's motion.

How: dense flow (DIS) on the centre crop above the HUD strips, with the weapon / hands and the
reticle masked. Camera yaw and pitch are the median flow of the far field (the upper part of
the frame: sky, far walls), which rotation moves uniformly whatever the depth. Translation
shows as parallax: the near ground (lower part) moves more than the far field, so
    strafe  = median dx(near) - median dx(far)      (scene flows left -> player moved right)
    forward = median dy(near) - median dy(far)      (ground flows down -> player moved forward)
Pixels are turned into degrees with the game's default FOV (103° horizontal at 16:9, which is
a vertical FOV of ~70.5°, so f = (H/2) / tan(35.25°)); the player's FOV setting may differ, so
degrees are approximate and said so. A pair with no usable flow (teleport, a dash with motion
blur, the death cam, a menu) is a "cut": with a wholesale pixel change it is a "jump" (a teleport, the death cam, a freeze
or a menu); without one it is "no stable read". A Lifeweaver Dash or a Fade is not separable
from close-quarters chaos by flow (2026-10-16: Havana d08's Dash and Nepal d07's Winston in
the face look the same), so a dash is reported by the HUD's press record, not by this.

Everything here is camera-relative. Which way is "toward the enemy" or "to cover" is still the
reader's call from what it sees in the stills; the trace only says the player backed up,
strafed left, turned right, or jumped.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

FLOW_W = 480                 # px: flow is computed on frames downscaled to this width
V_FOV = 70.5                 # degrees, the default 103° horizontal at 16:9
FAR_BAND = (0.03, 0.45)      # rows of the crop (fractions) that count as far field
NEAR_BAND = (0.60, 0.90)     # rows that count as near ground
WEAPON = (0.50, 0.35)        # x from, y from (fractions): the weapon / hands box to mask, to the right and bottom edges
HANDS = 0.90                 # rows below this fraction are masked everywhere (hands, melee)
RETICLE = 0.06               # half-size of the central mask, in crop heights
INLIER_PX = 6.0              # px (at FLOW_W): a far-field flow vector this close to the global shift is an inlier
INLIER_MIN = 0.30            # far-field inlier fraction below this = a cut (teleport, dash blur, camera change)
JUMP_DIFF = 45.0             # mean |pixel difference| (0-255, at FLOW_W) between a cut's two frames above which the
                             # scene changed wholesale (teleport, dash blur, death cam); normal play measures 20-25
MOVE_MIN = 6.0               # px per 0.1 s (at FLOW_W) of near-ground parallax that counts as moving
TURN_MIN = 2.0               # degrees per 0.1 s that counts as turning


def _dis():
    d = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    d.setUseSpatialPropagation(True)
    return d


def _prep(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    s = FLOW_W / w
    g = cv2.cvtColor(cv2.resize(img, (FLOW_W, int(round(h * s))), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (3, 3), 0)


def _masks(h: int, w: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:h, 0:w]
    keep = np.ones((h, w), bool)
    keep[(yy >= WEAPON[1] * h) & (xx >= WEAPON[0] * w)] = False                  # weapon / hands
    keep[yy >= HANDS * h] = False                                                # hands along the bottom
    keep[(np.abs(yy - h / 2) < RETICLE * h) & (np.abs(xx - w / 2) < RETICLE * h)] = False   # reticle
    far = keep & (yy >= FAR_BAND[0] * h) & (yy < FAR_BAND[1] * h)
    near = keep & (yy >= NEAR_BAND[0] * h) & (yy < NEAR_BAND[1] * h)
    return far, near


def pair(a: np.ndarray, b: np.ndarray, dis=None, frame_h: float | None = None) -> dict:
    """Flow from a to b (consecutive frames) -> yaw_deg, pitch_deg (camera; + = right / up),
    strafe, forward (parallax px at FLOW_W; + = right / forward), err (1 - far-field inlier
    fraction), cut. The global shift (the camera's turn) comes from phase correlation of the
    far band, which survives large turns and moving characters; the dense flow then gives
    the parallax after that shift is removed."""
    dis = dis or _dis()
    ga, gb = _prep(a), _prep(b)
    h, w = ga.shape
    far, near = _masks(h, w)
    flow = dis.calc(ga, gb, None)
    fx, fy = flow[..., 0], flow[..., 1]
    # the global shift = the median far-field flow (a moving character or a flash is a minority
    # of the far band; the median ignores it where phase correlation does not)
    yaw_px = float(np.median(fx[far])) if far.any() else 0.0
    pitch_px = float(np.median(fy[far])) if far.any() else 0.0
    inl = float(np.mean(np.hypot(fx[far] - yaw_px, fy[far] - pitch_px) < INLIER_PX)) if far.any() else 0.0
    resp = inl
    err = round(1.0 - inl, 2)
    near_dx = float(np.median(fx[near])) if near.any() else yaw_px
    near_dy = float(np.median(fy[near])) if near.any() else pitch_px
    keep = far | near
    diff = float(np.abs(ga[keep].astype(np.float32) - gb[keep].astype(np.float32)).mean()) if keep.any() else 0.0
    # pixels of rotation -> degrees: the crop is FLOW_W wide; at the frame's scale the focal
    # length is f = (H/2) / tan(V_FOV/2) in frame px; the crop was downscaled by FLOW_W / crop_w
    scale = FLOW_W / a.shape[1]
    f_px = ((frame_h or a.shape[0] / 0.611) / 2) / math.tan(math.radians(V_FOV / 2)) * scale
    yaw = -math.degrees(math.atan(yaw_px / f_px))        # scene flows left = camera turned right
    pitch = math.degrees(math.atan(pitch_px / f_px))     # scene flows down = camera tilted up
    cut = inl < INLIER_MIN
    # a cut with a large flow is a jump (teleport, dash, blink); a cut with a small one is a
    # frame with no stable far field (close quarters, looking at the ground, a menu)
    return {"yaw": round(yaw, 1), "pitch": round(pitch, 1), "strafe": round(-(near_dx - yaw_px), 1),
            "forward": round(near_dy - pitch_px, 1), "err": err, "cut": cut, "jump": bool(cut and diff >= JUMP_DIFF)}


def trace(frames: list[tuple[float, np.ndarray]], frame_h: float | None = None) -> list[list]:
    """frames = [(dt, centre crop), ...] in time order -> rows [dt_to, yaw, pitch, strafe, forward, err, cut]."""
    dis = _dis()
    rows = []
    for (ta, a), (tb, b) in zip(frames, frames[1:]):
        if a is None or b is None or a.shape != b.shape:
            continue
        r = pair(a, b, dis, frame_h)
        rows.append([round(tb, 1), r["yaw"], r["pitch"], r["strafe"], r["forward"], r["err"], r["cut"], r["jump"]])
    return rows


def _label(yaw: float, strafe: float, forward: float) -> list[str]:
    out = []
    if forward >= MOVE_MIN:
        out.append("forward")
    elif forward <= -MOVE_MIN:
        out.append("backing up")
    if strafe >= MOVE_MIN:
        out.append("strafing right")
    elif strafe <= -MOVE_MIN:
        out.append("strafing left")
    if abs(yaw) >= TURN_MIN:
        out.append(f"turning {'right' if yaw > 0 else 'left'}")
    return out or ["still"]


def describe(rows: list[list], zero_dt: float | None = None, step: float = 0.5) -> str:
    """Rows -> a short trace in windows of `step` s: what the camera did, the turn in degrees,
    and cuts. Rows after zero_dt (HP 0) are the death cam and are left out."""
    if not rows:
        return "no movement read (fewer than two detail stills)"
    rows = [r for r in rows if zero_dt is None or r[0] <= zero_dt + 0.05]
    if not rows:
        return "no movement read before HP hit 0"
    parts = []
    t0 = rows[0][0] - 0.1
    k = 0
    while k < len(rows):
        win = [r for r in rows if t0 + k * step - 0.05 < r[0] <= t0 + (k + 1) * step + 0.05]
        k += 1
        if not win:
            if t0 + k * step > rows[-1][0]:
                break
            continue
        cuts = [r for r in win if r[6]]
        jumps = [r for r in win if len(r) > 7 and r[7]]
        good = [r for r in win if not r[6]]
        a, b = win[0][0] - 0.1, win[-1][0]
        span = f"{a:+.1f} to {b:+.1f} s"
        if len(cuts) >= max(1, len(win) // 2):
            if len(jumps) >= max(1, len(cuts) // 2):
                parts.append(f"{span}: the scene changed wholesale in {len(jumps)} of {len(win)} frames (a teleport, a freeze, the death cam, or a menu)")
            else:
                parts.append(f"{span}: no stable read in {len(cuts)} of {len(win)} frames (close quarters, looking at the ground, a dash blur, or an overlay)"
                             + (f", {len(jumps)} changed wholesale" if jumps else ""))
            continue
        yaw = sum(r[1] for r in good)
        strafe = sum(r[3] for r in good) / len(good)
        fwd = sum(r[4] for r in good) / len(good)
        lab = _label(yaw / len(good), strafe, fwd)
        turn = f", turned {abs(yaw):.0f}° {'right' if yaw > 0 else 'left'}" if abs(yaw) >= 10 else ""
        parts.append(f"{span}: " + ", ".join(lab) + turn + (f" ({len(jumps)} frame{'s' if len(jumps) > 1 else ''} changed wholesale)" if jumps else ""))
    return "; ".join(parts)
