"""Who the player is: name, nameplate template, portrait library.

The nameplate under the health bar is what tells your own first-person view apart from
kill cam (your killer's) and spectating (a teammate's). Its font can't be reproduced, so
the template is taken from the player's own footage at onboarding:

  1. full-res nameplate crops from HUD frames spread over a recording
  2. each crop -> text mask (bright, unsaturated text on the teal plate) cut to the glyphs
  3. the mask that matches the most other crops is the player: you're in first person far
     more often than you're watching someone else
  4. OCR proposes the name; the player confirms or types it

Profile dir: see config.profile_dir() ($OWCOACH_PROFILE, the config file, else
~/.local/share/coachclaude/ow): profile.json, nameplate.png, portraits.npz.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .scan import grab_frame, load_index

NAME_ROI = (0.088, 0.885, 0.165, 0.945)  # nameplate under the health bar, fractions of the game area
INIT_SAMPLES = 48                        # nameplate crops taken at onboarding
INIT_HUD = 0.60                          # HUD score for frames used at onboarding
SAME_NAME = 0.60                         # mask match above this = the same nameplate
MIN_SHARE = 0.40                         # the player's nameplate must be at least this share of samples


def profile_dir() -> Path:
    from .config import profile_dir as _pd
    return _pd()


class NoProfile(RuntimeError):
    pass


def load() -> dict:
    p = profile_dir() / "profile.json"
    if not p.exists():
        raise NoProfile(f"no player profile at {p.parent}: run `owcoach init CACHE` first")
    return json.loads(p.read_text(encoding="utf-8"))


def nameplate_tpl() -> np.ndarray:
    load()
    return (cv2.imread(str(profile_dir() / "nameplate.png"), cv2.IMREAD_GRAYSCALE) > 127).astype(np.float32)


def text_mask(img: np.ndarray, frac: float) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    s, v = hsv[..., 1], hsv[..., 2]
    return ((v > max(90.0, float(np.percentile(v, 99)) * frac)) & (s < 80)).astype(np.float32)


def nameplate_score(img: np.ndarray, tpl: np.ndarray) -> float:
    """img = NAME_ROI crop at full res. Best match over a few brightness cut-offs."""
    best = 0.0
    for frac in (0.75, 0.6, 0.45):
        m = text_mask(img, frac)
        if m.shape[0] >= tpl.shape[0] and m.shape[1] >= tpl.shape[1] and m.any():
            best = max(best, float(cv2.matchTemplate(m, tpl, cv2.TM_CCOEFF_NORMED).max()))
    return best


def glyphs(img: np.ndarray) -> np.ndarray | None:
    """Text mask cut to the name's glyphs: components of text height on the name's row."""
    m = text_mask(img, 0.75)
    H = m.shape[0]
    n, _, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
    comp = [st[i] for i in range(1, n) if 0.12 * H <= st[i, 3] <= 0.35 * H and st[i, 4] >= 0.005 * H * H]
    if len(comp) < 2:
        return None
    mid = np.median([c[1] + c[3] / 2 for c in comp])
    comp = [c for c in comp if abs(c[1] + c[3] / 2 - mid) < 0.1 * H]
    if len(comp) < 2:
        return None
    x0 = max(0, min(c[0] for c in comp) - 2)
    y0 = max(0, min(c[1] for c in comp) - 2)
    x1 = max(c[0] + c[2] for c in comp) + 2
    y1 = max(c[1] + c[3] for c in comp) + 2
    return m[y0:y1, x0:x1]


def ocr_name(tpl: np.ndarray) -> str:
    b = np.where(tpl > 0, 0, 255).astype(np.uint8)
    b = cv2.copyMakeBorder(cv2.resize(b, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST),
                           12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    _, buf = cv2.imencode(".png", b)
    txt = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7"],
                         input=buf.tobytes(), capture_output=True).stdout.decode(errors="replace")
    return re.sub(r"[^A-Za-z0-9_]", "", txt).upper()


def find_player(cache: Path) -> dict:
    """-> {crops, masks, best, members, share, names}: the most common nameplate in the recording."""
    idx = load_index(cache)
    feats = np.load(cache / "features.npy")
    t, hud = feats[:, 0], feats[:, 1]
    ks = np.where(hud >= INIT_HUD)[0]
    if len(ks) < INIT_SAMPLES:
        raise ValueError(f"only {len(ks)} HUD frames in {cache}; onboard from a recording with gameplay")
    pick = ks[np.linspace(0, len(ks) - 1, INIT_SAMPLES).round().astype(int)]
    td = tempfile.TemporaryDirectory()

    def grab(i_k):
        i, k = i_k
        return cv2.imread(str(grab_frame(cache, float(t[k]), Path(td.name) / f"n{i}.png", roi=NAME_ROI)))

    with td, ThreadPoolExecutor(6) as ex:
        crops = list(ex.map(grab, enumerate(pick)))
    masks = [glyphs(c) for c in crops]
    ok = [i for i, m in enumerate(masks) if m is not None]
    members = {i: [j for j in ok if nameplate_score(crops[j], masks[i]) >= SAME_NAME] for i in ok}
    best = max(ok, key=lambda i: len(members[i])) if ok else None
    if best is None:
        raise ValueError("no readable nameplates found")
    names = Counter(n for n in (ocr_name(masks[j]) for j in members[best][:9]) if len(n) >= 2)
    return {"crops": crops, "masks": masks, "best": best, "members": members[best],
            "share": len(members[best]) / len(crops), "names": names, "times": [float(t[k]) for k in pick]}


def init(cache: Path, name: str | None = None, assume_yes: bool = False) -> dict:
    found = find_player(cache)
    best, share = found["best"], found["share"]
    guess = found["names"].most_common(1)[0][0] if found["names"] else ""
    d = profile_dir()
    d.mkdir(parents=True, exist_ok=True)
    preview = d / "nameplate_preview.png"
    crop = found["crops"][best]
    cv2.imwrite(str(preview), cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
    print(f"most common nameplate: {len(found['members'])}/{len(found['crops'])} samples "
          f"({share:.0%}), reads as {guess or '?'!r}   preview: {preview}")
    if share < MIN_SHARE:
        print(f"warning: below {MIN_SHARE:.0%}. Lots of spectating, or a recording of someone else? "
              "Check the preview before confirming.")

    if name:
        confirmed = name.strip()
    elif assume_yes:
        confirmed = guess
    else:
        try:
            ans = input(f"Is this you: {guess or '?'}? [Y = yes / type your name / n = abort] ").strip()
        except EOFError:
            raise SystemExit(f"no answer on stdin: rerun with --name {guess or 'NAME'} (or --yes) to confirm")
        if ans.lower() == "n":
            raise SystemExit("aborted; nothing written")
        confirmed = guess if ans.lower() in ("", "y", "yes") else ans
    if not confirmed:
        raise SystemExit("no name read; rerun with --name NAME")

    cv2.imwrite(str(d / "nameplate.png"), (found["masks"][best] * 255).astype(np.uint8))
    prof = {"name": confirmed, "ocr_guess": guess, "onboarded_from": load_index(cache)["video"],
            "onboarded_at": time.strftime("%Y-%m-%d %H:%M:%S"), "nameplate_share": round(share, 2),
            "nameplate_roi": NAME_ROI}
    (d / "profile.json").write_text(json.dumps(prof, indent=1), encoding="utf-8")
    return prof
