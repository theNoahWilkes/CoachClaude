"""Stage 4b: the player's HP and ability states for the whole session, 2 fps, from the roiscan
HUD crops (regions hud_hp / hud_abil, the same two strips a detail still carries).

Why: deaths are a few seconds of a game. The whole-game series turns the coaching focus into
arithmetic: every stretch under half HP (did they recover, press the escape, or die), every
escape press (at what HP), time spent low, and where the fights were (HP changes plus kills
and deaths), which tells the overview readers where to look. Cost: the crops are free (the
roiscan pass decodes every keyframe anyway); reading ~9,000 frames takes about a minute.

Output: <cache>/hud.json
    {"n_frames": N, "rows": [{"k": frame index, "t": session seconds, "m": match n,
      "hero": ..., "hp": current or null, "max": max or null, "conf": 0..1,
      "slots": [[state, countdown or null], ...]}, ...]}
Slot layouts per hero are learned from the hero's own-view frames (sampled) and merged with the
profile cache (hud_layouts.json), so a hero seen for the first time is learned here.
"""
from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .hud import RIGHT_W, hero_layout, load_layouts, read_hp, read_slot, save_layouts
from .overlay import perk_prompt_left, scoreboard
from .scan import frame_path, load_index
from .stats import _templates

LAYOUT_SAMPLE = 160          # frames per hero used to learn the slot layout


def _hero_at(m: dict, t: float) -> str | None:
    for h in m.get("heroes", []):
        if h["from"] - 1 <= t <= h["to"] + 1:
            return h["hero"]
    return m.get("hero_main")


HUD_VERSION = 3              # 2: active slot state, scoreboard / perk-prompt notices, perk-prompt own view; 3: perk box mapping fixed


def hudscan(cache: Path, jobs: int = 8, quiet: bool = False) -> dict:
    p = cache / "hud.json"
    idx = load_index(cache)
    frames = idx["frames"]
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("n_frames") == len(frames) and d.get("version") == HUD_VERSION:
            return d
    cfg = json.loads((cache / "scan.json").read_text())
    H = cfg["crop"][1] if cfg.get("crop") else cfg["probe"]["height"]
    W = cfg["crop"][0] if cfg.get("crop") else cfg["probe"]["width"]
    aspect = W / H
    own = np.load(cache / "own_view.npy")
    matches = json.loads((cache / "matches.json").read_text())["matches"]
    tpl = _templates()
    layouts = load_layouts()
    t = np.array([f["t"] for f in frames])

    def crop(region: str, k: int):
        return cv2.imread(str(cache / "roi" / region / frames[k]["f"]))

    rows = []
    for m in matches:
        in_m = (t >= m["start"]) & (t <= m["end"])
        ks = [int(k) for k in np.where(own & in_m)[0]]
        # own view lost to the SELECT PERK prompt (it covers the nameplate the own-view check
        # reads): a non-own frame whose nameplate area is the orange box and whose HP box reads
        # is the player's view after all (Route 66 d04, 2026-10-16)
        extra = []
        for k in np.where(~own & in_m)[0]:
            left = crop("hud_hp", int(k))
            if left is not None and perk_prompt_left(left, aspect) and read_hp(left, H, tpl)[2] >= 0.7:
                extra.append(int(k))
        ks = sorted(set(ks) | set(extra))
        by_hero: dict[str, list[int]] = {}
        for k in ks:
            by_hero.setdefault(_hero_at(m, float(t[k])) or "", []).append(k)
        for hero, hks in by_hero.items():
            sample = sorted(random.Random(0).sample(hks, min(LAYOUT_SAMPLE, len(hks))))
            rights = [r for r in (crop("hud_abil", k) for k in sample) if r is not None]
            layout = hero_layout(rights, H, layouts.get(hero) if hero else None)
            if hero and layout:
                layouts[hero] = layout
            rw = round(RIGHT_W * H)
            slots_px = [rw - off * H for off in layout]

            def job(k: int):
                left, right = crop("hud_hp", k), crop("hud_abil", k)
                if left is None or right is None:
                    return None
                notes = []
                thumb = cv2.imread(str(frame_path(cache, frames[k])))
                if thumb is not None and scoreboard(thumb):
                    notes.append("scoreboard")          # the health box shows 0 under it: unreadable
                if perk_prompt_left(left, aspect):
                    notes.append("perk_prompt")
                if "scoreboard" in notes:
                    cur, mx, conf, slots = None, None, 0.0, [{"state": "hidden"}] * len(slots_px)
                else:
                    cur, mx, conf = read_hp(left, H, tpl)
                    slots = [read_slot(right, cx, H) for cx in slots_px]
                return {"k": k, "t": float(t[k]), "m": m["n"], "hero": hero or None,
                        "hp": cur, "max": mx, "conf": conf,
                        "slots": [[s["state"], s.get("n")] for s in slots],
                        **({"notices": notes} if notes else {})}

            with ThreadPoolExecutor(jobs) as ex:
                rows += [r for r in ex.map(job, hks) if r]
            if not quiet:
                print(f"  hud match {m['n']} {hero or '?':12s} {len(hks):5d} frames, {len(layout)} slots", flush=True)
    rows.sort(key=lambda r: r["k"])
    save_layouts(layouts)
    d = {"version": HUD_VERSION, "n_frames": len(frames), "rows": rows}
    p.write_text(json.dumps(d), encoding="utf-8")
    return d
