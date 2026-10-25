"""Stage 5: the per-game coaching packet, the input to the generative analysis.

  <game dir>/packet/
      packet.json        game facts, hero timeline, objective, one merged timeline, and one record
                         per death / ult / final blow with its context and the stills that show it
      frames/            stills around each moment: full game area (tonemapped, FRAME_W wide) for
                         context, and "detail" stills (centre of the screen at native resolution with
                         the HP and ability HUD underneath) for the last seconds before a death
      overview/          contact sheets of the whole match, a scan thumbnail every OVERVIEW_STEP s,
                         each cell labelled with the game clock, alive / DEAD and any
                         event in its window: the context between deaths (positioning while alive,
                         fights won, good plays) that the death stills don't show
      scoreboard_final.jpg | summary.jpg | rank.jpg   copied in, so the folder is self-contained
      moments.m3u        VLC playlist: each moment played straight from ../match.mp4 (for the human)
      facts/dNN.md       the facts block per death (also deaths[].facts): HUD, presses, low episode, feed

Times: "t" is seconds since the match start, "clock" is the same as m:ss, "video_t" is the time
in match.mp4. The analyst (Claude) can't watch video, so each moment is a handful of stills:
the lead-in to a death from the player's own view, then the kill cam (the killer's view).
A downscaled ultrawide frame is too small to read (3456 px -> 1568 px leaves HP numbers, names and
ability icons illegible), so the stills that explain a death are crops at native resolution.
"""
from __future__ import annotations

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .config import profile_dir, relpath, session_dir, session_name
from .herowiki import hero_note_path
from .facts import death_facts, slot_names
from .motion import describe as motion_describe, trace as motion_trace
from .hud import death_hud, game_hud, hero_layout, load_layouts, load_stills, save_layouts
from .scan import frame_path, grab_frame, load_index
from .split import match_dirname

FRAME_W = 1568               # px: Claude's native image size; larger is downscaled on arrival anyway
# Deaths are found in the kill feed, but the feed is sometimes read late (up to ~9 s: TAB open,
# feed crowded, environmental kill). The "YOU WERE ELIMINATED BY" banner (assets/eliminated.png,
# grey-scale, cut from a 534 px-high thumbnail) shows within 0.5 s of the death, centre-bottom; its
# height varies with the other notices stacked under it. NCC: banner 0.6..1.0, alive frames <= 0.58
# (65 deaths, 2 sessions); 5 of 65 deaths had none (menus, spectating), and fall back to the feed.
ELIM_SEARCH = (0.449, 0.949, -0.375, 0.375)   # y0, y1 (heights from top), x0, x1 (heights from centre)
ELIM_MIN, ELIM_NEAR = 0.6, 0.55   # onset: a frame >= MIN with another >= NEAR within the next two
ELIM_BEFORE = 14.0           # s before the feed sighting to look for the banner
ELIM_LAG = 0.25              # s from the death to the banner's first thumbnail (0..0.5: thumbnails are 0.5 s apart)
FEED_LAG = 0.5               # s from the death to the feed sighting, when there's no banner
# Stills, relative to the death: two full-screen ones for context, then detail crops every 0.1 s
# over the last 3 s. Only every 0.5 s is the coach's first pass; the rest are marked "extra" and read
# on demand, when the first pass leaves a question (A/B on Havana 2026-10-15: 10 fps fixed one misread,
# but reading all of it cost +84% and made one confident wrong call). Decoding is local and free.
DEATH_CONTEXT = (-10.0, -6.0)
DETAIL_FROM, DETAIL_STEP = -3.0, 0.1
DETAIL_FIRST = 0.5           # s between first-pass detail stills
# Detail crop, in game-area heights: the centre (where the fight is) at native resolution, and
# the bottom corners (HP / ults / cooldowns) under it. 1568 x 1140 px at 1440 p.
DETAIL_CENTRE = (1.089, 0.611)       # w, h
DETAIL_HUD = (0.542, 0.547, 0.181)   # left w, right w, h
# Overview sheets, from the scan thumbnails (no extra decode). Cells at the thumbnails' full 1280 px,
# two per sheet: on Havana 2.5 s cells found fights, saves and pipeline timing errors that 5 s cells
# at 780 px missed (A/B 2026-10-15). Reading all of them was slow, so the first pass is every 5 s
# (overview_NNN.jpg) and the cells halfway between are extras (overview_NNNb.jpg), opened around
# fights. COST: ~6 first-pass sheets a minute.
OVERVIEW_STEP = 2.5          # s between cells; the first pass uses every other one
OVERVIEW_COLS, OVERVIEW_ROWS = 1, 2
OVERVIEW_CELL_W = 1280       # px: the scan thumbnails' native width
OVERVIEW_LABEL_H = 40
KILLCAM_N = 4                # first-pass stills from the kill cam (the killer's view)
KILLCAM_STEP = 0.1           # s: every kill-cam frame at this step is kept as an extra
KILLCAM_PAD = 0.5            # s around the labelled thumbnails, which are 0.5 s apart
KILLCAM_FROM = 2.0           # s after the feed sighting: before this it's the death camera
KILLCAM_TO = 14.0            # s after the feed sighting: kill cams start at +4..6 s and run ~3 s
# The kill cam is found by its "KILL CAM" label (assets/killcam.png, max-channel, cut from a
# 534 px-high thumbnail). NCC: kill cam 0.72..1.0, everything else <= 0.54 (2 sessions).
# Not every death has one (the game skips it sometimes, or the player does).
KC_REF_H = 534
KC_SEARCH = (0.843, 0.964, -0.15, 0.17)   # y0, y1 (heights from top), x0, x1 (heights from centre)
KC_MIN = 0.65
# Respawn = first steady own view after RESPAWN_MIN. Approximate: the death camera and spectating a
# teammate both pass the own-view check (TODO: per-frame nameplate check). Respawns take >= 10 s and
# the feed lags the death by <= 2 s, hence the floor; spectate can still make it read ~1-2 s early.
RESPAWN_MIN = 8.0
BACK_RUN = 4                 # own frames in a row that mean "respawned" (single blips happen while dead)
RESPAWN_MAX = 40.0
ULT_SHOTS = (-3.0, 0.5, 2.5) # s relative to the press: the setup, then the effect
CLIP_LEAD, CLIP_TAIL = 12.0, 6.0   # playlist window around a death
# rule flags: leads for the analyst, not verdicts
ALIVE_FRESH = 6.0            # s: an alive_before reading older than this isn't trusted for flags
SHORT_LIFE = 20.0            # s from respawn to the next death
REPEAT_KILLER = 3            # deaths to the same player in one game
ULT_HELD_LONG = 45.0         # s ready before use / loss

NOTES = [
    "Deaths, killers and final blows come from the kill feed; killer and victim names are OCR'd and may be slightly off.",
    "Assists, damage and healing over time are not extracted; per-game totals are in summary.jpg and scoreboard_final.jpg.",
    "Death times: anchor 'banner' = from the 'YOU WERE ELIMINATED' banner (within ~0.25 s); 'feed' = the kill-feed sighting minus 0.5 s, which can be several seconds late. feed_lag_s is the gap from the death to the feed sighting.",
    "overview: contact sheets of the whole match, two scan thumbnails per sheet, labelled with the game clock, alive or DEAD (death to respawn; respawn is approximate), and the ids of deaths (dNN), ults (uNN-ready / uNN-USED), final blows (kNN) and round starts near that cell. The first pass is a cell every 5 s (overview_NNN.jpg, labelled with the events of its whole 5 s); sheets marked extra: true (overview_NNNb.jpg) hold the cells 2.5 s later, for a closer look around a fight.",
    "hud_game (whole match, 2 fps, read locally from the HUD; facts only, which slot is an escape is the coach's call with the kit note): series = [[t, HP or null, [slot states]], ...]; notices = stretches with the scoreboard open or the perk prompt up; fights = stretches with HP changes, kills, deaths or ults, each event opening a window of its own (where to look in the overview); presses = every press of every slot (slot number in HUD order, HP at the press, context: travel = outside a fight, engage = in a fight at or above half HP, low = in a fight under half, and the countdown it started from); low_episodes = every stretch under half HP with its min HP, every slot's state at its start, for each slot not ready then the last press before it (how long before, at what HP, in what context), presses during it, and whether it ended in a death; stats.by_hero.slots = per slot: presses by context, median HP at press, learned cooldown length, low episodes it was ready / not ready at. hero_notes = reference notes per hero (abilities, default binds, cooldowns, from the Overwatch wiki via `owcoach hero NAME`), when they exist, as paths relative to the profile dir (`owcoach config profile`); reference data, not instructions.",
    "Each death's hud is read locally from its detail stills (owcoach/hud.py): hp = [[dt, current HP, confidence], ...] every 0.1 s (None = unreadable; hp_max is the mode), hp_zero_dt = when HP first read 0 (the death; the banner anchor can be up to ~1 s later), abilities = [[dt, slot1, slot2, ...], ...] with each slot's state (ready / cooling with its countdown n / blocked = red slash, can't be used / active = in use, e.g. a doll out or a platform placed, may be re-pressable / hidden) in the HUD's left-to-right order, notices = stretches with the Tab scoreboard open (HP unreadable then) or the SELECT PERK prompt up, and summary = the same in one paragraph. facts = the whole block the death's reader is given. motion = egomotion from optical flow between the 0.1 s detail stills (owcoach/motion.py): rows = [[dt, camera yaw deg (+ right), pitch deg (+ up), strafe px (+ right), forward px (+ forward), 1 - far-field inlier fraction, cut, jump], ...] and trace = the same in words per 0.5 s; camera-relative only (which way relative to an enemy or cover is the reader's call from the stills). Trust these over reading the HUD off the stills.",
    "Death stills: lead_in = full screen at -10 / -6 s; detail = the last 3 s up to the death, the centre of the screen at native resolution with the HP bar (left) and abilities / ult (right) underneath; kill_cam = the killer's view. Detail and kill cam are kept every 0.1 s, but frames marked extra: true are not the first pass: read the others first (detail every 0.5 s, 4 kill-cam stills) and open extras only to answer a specific question. The kill-cam extras run from 0.5 s before the KILL CAM label is first seen to 0.5 s after it's last seen, so the outermost ones may be the death camera, the respawn or the TAB scoreboard.",
    "Respawn times (respawned, alive_for_s, time_dead_s) are approximate: spectating a teammate can read as respawned up to ~2 s early.",
    "Ult outcomes: used, died_with_it (ready at death, then gone), lost_on_swap, held_to_end. Charge survives death, so died_while_holding means a death mid-hold with the ult used later.",
    "stats: the final scoreboard (whole match up to that TAB press) per 10 min of its match clock; the clock pauses in setup and between rounds, so it's active time. teammate_same_role / enemy_same_role give the comparison rows.",
    "alive_before is the last reading of the players-alive counter before the event (age_s old).",
    "Ult state is ready / not ready only (no charge %); 'used' means the ready icon went away while alive.",
    "Death flags: first_down = 5v5 just before (no teammate down yet), team_ahead / team_behind / even_fight compare the counts; short_life = died within 20 s of respawning; repeat_killer = 3+ deaths to that player. Flags are leads, not verdicts.",
    "focus_tests (owcoach/moments.py): every window where a focus could be tested, in time order: kind low = a low-HP episode, down_two = the team down two or more while the player is alive (from the alive counter), respawn = the 20 s after a respawn; each with from / to, what, and the death it ended in if any. Which kinds test the current focus is matched from its wording when the digest is written. chains = runs of deaths where each came within 20 s of respawning from the one before (one decision and its consequence).",
    "saves (owcoach/saves.py): every 'SAVED <ally>' notice under the crosshair, read locally from the screen: t / clock = when it appeared, by = true for 'SAVED BY <ally>' (a teammate saved the player). Who was saved is not read. Two saves within ~3 s count once. Routine for a support: a save is a moment only when it turned a fight.",
    "Objective numbers: control capture %, push / competitive escort distance in metres; quick-play escort progress isn't read.",
]


def _clock(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


class _Game:
    """Session-time -> game-time helpers for one match."""

    def __init__(self, m: dict, offset: float):
        self.start, self.offset = m["start"], offset

    def at(self, ts: float | None) -> dict:
        if ts is None:
            return {"t": None}
        return {"t": round(ts - self.start, 1), "clock": _clock(ts - self.start), "video_t": round(ts - self.offset, 2)}


def _respawn(own_t: np.ndarray, down: float) -> float | None:
    """First steady return to the player's own view after a death."""
    j = np.searchsorted(own_t, down + RESPAWN_MIN)
    while j + BACK_RUN <= len(own_t) and own_t[j] <= down + RESPAWN_MAX:
        if own_t[j + BACK_RUN - 1] - own_t[j] <= 0.5 * (BACK_RUN - 1) + 0.1:
            return float(own_t[j])
        j += 1
    return None


def killcam_score(thumb: np.ndarray, tpl: np.ndarray) -> float:
    if thumb.shape[0] != KC_REF_H:
        thumb = cv2.resize(thumb, None, fx=KC_REF_H / thumb.shape[0], fy=KC_REF_H / thumb.shape[0],
                           interpolation=cv2.INTER_AREA)
    v = thumb.max(2).astype(np.float32)
    cx = v.shape[1] / 2
    y0, y1, x0, x1 = KC_SEARCH
    win = v[int(y0 * KC_REF_H):int(y1 * KC_REF_H), int(cx + x0 * KC_REF_H):int(cx + x1 * KC_REF_H)]
    return float(cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED).max())


def elim_score(thumb: np.ndarray, tpl: np.ndarray) -> float:
    g = cv2.cvtColor(thumb, cv2.COLOR_BGR2GRAY) if thumb.ndim == 3 else thumb
    if g.shape[0] != KC_REF_H:
        g = cv2.resize(g, None, fx=KC_REF_H / g.shape[0], fy=KC_REF_H / g.shape[0], interpolation=cv2.INTER_AREA)
    cx = g.shape[1] / 2
    y0, y1, x0, x1 = ELIM_SEARCH
    win = g[int(y0 * KC_REF_H):int(y1 * KC_REF_H), int(cx + x0 * KC_REF_H):int(cx + x1 * KC_REF_H)]
    return float(cv2.matchTemplate(win.astype(np.float32), tpl, cv2.TM_CCOEFF_NORMED).max())


def _death_time(t: np.ndarray, score, feed: float, after: float) -> tuple[float, str]:
    """When the player died: from the elimination banner if it's on screen, else from the feed."""
    ks = np.where((t >= max(feed - ELIM_BEFORE, after)) & (t <= feed + 3.0))[0]
    s = [score(k) for k in ks]
    for i, k in enumerate(ks):
        if s[i] >= ELIM_MIN and any(x >= ELIM_NEAR for x in s[i + 1:i + 3]):
            return float(t[k]) - ELIM_LAG, "banner"
    return feed - FEED_LAG, "feed"


def _detail(im: np.ndarray) -> np.ndarray:
    h, w = im.shape[:2]
    cw, ch = (round(x * h) for x in DETAIL_CENTRE)
    lw, rw, hh = (round(x * h) for x in DETAIL_HUD)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    centre = im[y0:y0 + ch, x0:x0 + cw]
    hud = np.hstack([im[h - hh:, :lw], np.zeros((hh, max(0, cw - lw - rw), 3), im.dtype), im[h - hh:, w - rw:]])
    out = np.vstack([centre, hud[:, :cw]])
    if out.shape[1] > FRAME_W:
        out = cv2.resize(out, (FRAME_W, round(out.shape[0] * FRAME_W / out.shape[1])), interpolation=cv2.INTER_AREA)
    return out


def _grab_detail(cache: Path, ts: float, dst: Path) -> None:
    raw = dst.with_suffix(".full.png")
    grab_frame(cache, ts, raw)
    cv2.imwrite(str(dst), _detail(cv2.imread(str(raw))), [cv2.IMWRITE_JPEG_QUALITY, 90])
    for _ in range(20):          # Windows: a scanner can hold the fresh PNG for a moment
        try:
            raw.unlink()
            break
        except PermissionError:
            time.sleep(0.25)


def _overview(cache: Path, index: list, t: np.ndarray, start: float, end: float, dead: list[tuple[float, float]],
              marks: list[tuple[float, str]], clock, odir: Path) -> list[dict]:
    """Tile one thumbnail every OVERVIEW_STEP s into labelled sheets; returns the sheet records.
    Even cells (every 2 * OVERVIEW_STEP) make the first-pass sheets, each labelled with the events
    of its whole 2 * OVERVIEW_STEP so none is missed; odd cells make the extra sheets ("b")."""
    if odir.exists():
        shutil.rmtree(odir)
    odir.mkdir(parents=True)
    times = np.arange(start, end, OVERVIEW_STEP)
    per = OVERVIEW_COLS * OVERVIEW_ROWS

    def cell(ts: float, half: float) -> np.ndarray:
        k = int(np.argmin(np.abs(t - ts)))
        im = cv2.imread(str(frame_path(cache, index[k])))
        h = round(im.shape[0] * OVERVIEW_CELL_W / im.shape[1])
        im = cv2.resize(im, (OVERVIEW_CELL_W, h), interpolation=cv2.INTER_AREA)
        ev = [lab for mt, lab in marks if ts - half <= mt < ts + half]
        down = any(a <= ts < b for a, b in dead)
        text = f"{clock(ts)}  {'DEAD' if down else 'alive'}" + (f"  | {' '.join(ev)}" if ev else "")
        lab = np.full((OVERVIEW_LABEL_H, OVERVIEW_CELL_W, 3), 24, np.uint8)
        cv2.putText(lab, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                    (80, 200, 255) if ev else (235, 235, 235), 1, cv2.LINE_AA)
        return np.vstack([im, lab])

    sheets = []
    for tier, sub, half, suffix in ((0, times[0::2], OVERVIEW_STEP, ""), (1, times[1::2], OVERVIEW_STEP / 2, "b")):
        for si in range(0, len(sub), per):
            cells = [cell(ts, half) for ts in sub[si:si + per]]
            blank = np.zeros_like(cells[0])
            cells += [blank] * (per - len(cells))
            gap = 4
            rows = [np.hstack(sum(([c, np.zeros((c.shape[0], gap, 3), np.uint8)] for c in cells[r:r + OVERVIEW_COLS]), [])[:-1])
                    for r in range(0, per, OVERVIEW_COLS)]
            sheet = np.vstack(sum(([r, np.zeros((gap, r.shape[1], 3), np.uint8)] for r in rows), [])[:-1])
            name = f"overview_{si // per + 1:03d}{suffix}.jpg"
            cv2.imwrite(str(odir / name), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
            t0, t1 = sub[si], sub[min(si + per, len(sub)) - 1]
            sheets.append({"file": f"overview/{name}", "from": clock(t0), "to": clock(t1), **({"extra": True} if tier else {})})
    return sheets


def _killcam_times(t: np.ndarray, killcam: np.ndarray, down: float, dead: float) -> list[tuple[float, bool]]:
    """(dt from the death, extra) for every KILLCAM_STEP over the labelled kill cam. The KILLCAM_N
    first-pass ones are spread over the labelled thumbnails. Times sit on a grid of whole steps from
    the death, so file names never collide."""
    ks = list(np.where((t >= down + KILLCAM_FROM) & (t <= down + KILLCAM_TO) & killcam)[0])
    if not ks:
        return []
    def step(x: float) -> int:
        return round((x - dead) / KILLCAM_STEP)
    pick = np.linspace(0, len(ks) - 1, KILLCAM_N + 2)[1:-1].round().astype(int)
    first = {step(t[ks[p]]) for p in pick}
    grid = range(step(t[ks[0]] - KILLCAM_PAD), step(t[ks[-1]] + KILLCAM_PAD) + 1)
    return [(round(k * KILLCAM_STEP, 1), k not in first) for k in grid]


def build_packet(cache: Path, gdir: Path, m: dict, ev: dict, t: np.ndarray, own: np.ndarray,
                 killcam: np.ndarray, player: str | None, jobs: int = 4, died: dict | None = None,
                 index: list | None = None, hud_all: dict | None = None, refresh: bool = False,
                 saved: list[dict] | None = None) -> dict:
    """refresh: keep the stills and overview sheets already on disk and rewrite packet.json only
    (for changes to the json, the HUD reads or the notes; a full build regrabs every still)."""
    meta = json.loads((gdir / "match.json").read_text())
    G = _Game(m, meta["clip_offset"])
    pdir = gdir / "packet"
    fdir = pdir / "frames"
    refresh = refresh and fdir.exists() and (pdir / "packet.json").exists()
    if not refresh:
        if fdir.exists():
            shutil.rmtree(fdir)
        fdir.mkdir(parents=True)
    own_t = t[own]
    grabs: list[tuple[float, Path, bool]] = []

    def shot(ts: float, name: str, kind: str, rel: float, detail: bool = False, extra: bool = False) -> dict:
        grabs.append((ts, fdir / name, detail))
        return {"file": f"frames/{name}", "kind": kind, "dt": rel, **G.at(ts), **({"extra": True} if extra else {})}

    ults = ev.get("ults", [])
    deaths = []
    prev_back = None
    round_ts = [r["t"] for r in (ev.get("objective") or {}).get("rounds", [])]
    for i, d in enumerate(ev["deaths"], 1):
        down = d["t"]                      # the feed sighting
        dead, anchor = (died or {}).get(down, (down - FEED_LAG, "feed"))
        back = _respawn(own_t, down)
        did = f"d{i:02d}"
        frames = [shot(dead + o, f"{did}_lead{o:+05.1f}.jpg", "lead_in", o) for o in DEATH_CONTEXT]
        n_first = round(DETAIL_FIRST / DETAIL_STEP)
        for k in range(round(DETAIL_FROM / DETAIL_STEP), 1):
            o = round(k * DETAIL_STEP, 1)
            frames.append(shot(dead + o, f"{did}_detail{o:+05.1f}.jpg", "detail", o, True, extra=k % n_first != 0))
        frames += [shot(dead + o, f"{did}_after{o:+05.1f}.jpg", "kill_cam", o, extra=x)
                   for o, x in _killcam_times(t, killcam, down, dead)]
        # events counts deaths up to 2 s after the last ready frame; the feed lags the death by
        # up to 2 s, so a death sighted after the ult went away is "died right after using it"
        mine = [u for u in ults if u["ready_t"] - 1 <= d["t"] and d["t"] in u["deaths_while_ready"]]
        holding = [u for u in mine if u["used_t"] is None or d["t"] < u["used_t"] + 0.5]
        just_used = [u for u in mine if u not in holding]
        deaths.append({
            "id": did, **G.at(dead), "anchor": anchor, "feed_lag_s": round(down - dead, 1),
            "hero": d.get("hero"), "killed_by": d.get("killed_by"),
            "alive_before": d.get("alive_before"), "objective": d.get("objective"),
            # since the last respawn; None for a round's first life (spawn-room time would count)
            "alive_for_s": (round(dead - prev_back, 1) if prev_back is not None
                            and not any(prev_back < rt < dead for rt in round_ts) else None),
            "respawned": G.at(back) if back else None,
            "kill_cam": any(f["kind"] == "kill_cam" for f in frames),
            "ult_ready": bool(holding),
            "ult_held_s": max(0.0, round(down - holding[0]["ready_t"], 1)) if holding else None,
            "ult_used_s_before": round(down - just_used[0]["used_t"], 1) if just_used else None,
            "frames": frames,
        })
        prev_back = back

    killers: dict[str, int] = {}
    for d in deaths:
        if d["killed_by"]:
            killers[d["killed_by"]] = killers.get(d["killed_by"], 0) + 1
    for d in deaths:
        fl = []
        a = d["alive_before"]
        if a and a.get("age_s", 99) <= ALIVE_FRESH and a.get("ally") and a.get("enemy"):
            fl.append("first_down" if a["ally"] == 5 and a["enemy"] == 5 else
                      "team_ahead" if a["ally"] > a["enemy"] else
                      "team_behind" if a["ally"] < a["enemy"] else "even_fight")
        if d["alive_for_s"] is not None and d["alive_for_s"] < SHORT_LIFE:
            fl.append("short_life")
        if d["ult_ready"]:
            fl.append("died_with_ult")
        if d["ult_used_s_before"] is not None:
            fl.append("died_after_ult")
        o = d["objective"] or {}
        if o.get("overtime"):
            fl.append("overtime")
        if o.get("contested"):
            fl.append("contested")
        if killers.get(d["killed_by"], 0) >= REPEAT_KILLER:
            fl.append("repeat_killer")
        d["flags"] = fl

    ult_recs = []
    for i, u in enumerate(ults, 1):
        uid = f"u{i:02d}"
        rec = {"id": uid, "hero": u["hero"], "outcome": u["outcome"], "held_s": u["held_s"],
               "ready": G.at(u["ready_t"]), "used": G.at(u["used_t"]) if u["used_t"] else None,
               "deaths_while_ready": [G.at(x)["t"] for x in u["deaths_while_ready"]],
               "objective_at_ready": u.get("objective_at_ready"), "objective_at_use": u.get("objective_at_use"),
               "frames": []}
        rec["flags"] = ([f"ult_{u['outcome']}"] if u["outcome"] != "used" else []) + (
            ["held_long"] if u["held_s"] >= ULT_HELD_LONG else []) + (
            # charge survives death, so this is a missed chance to use it, not lost charge
            ["died_while_holding"] if u["outcome"] != "died_with_it" and u["deaths_while_ready"] else [])
        if u["used_t"]:
            press = u["used_t"] + 0.25
            rec["frames"] = [shot(press + o, f"{uid}_use{o:+04.1f}.jpg", "ult_use", o) for o in ULT_SHOTS]
        ult_recs.append(rec)

    fbs = [{"id": f"k{i:02d}", **G.at(f["t"]), "hero": f.get("hero"), "victim": f.get("victim"),
            "alive_before": f.get("alive_before"), "objective": f.get("objective")}
           for i, f in enumerate(ev["final_blows"], 1)]

    marks = [(G.start + d["t"], d["id"]) for d in deaths]
    marks += [(u["ready_t"], f"u{i:02d}-ready") for i, u in enumerate(ults, 1)]
    marks += [(u["used_t"], f"u{i:02d}-USED") for i, u in enumerate(ults, 1) if u["used_t"]]
    marks += [(f["t"], f"k{i:02d}") for i, f in enumerate(ev["final_blows"], 1)]
    marks += [(r, "round") for r in round_ts]
    dead = [(G.start + d["t"], G.start + (d["respawned"]["t"] if d["respawned"] else d["t"] + 12.0)) for d in deaths]
    if refresh:
        overview = json.loads((pdir / "packet.json").read_text(encoding="utf-8"))["overview"]
    else:
        overview = _overview(cache, index or load_index(cache)["frames"], t, m["start"], m["end"], dead, sorted(marks),
                             lambda ts: _clock(ts - G.start), pdir / "overview")
        with ThreadPoolExecutor(jobs) as ex:
            list(ex.map(lambda g: _grab_detail(cache, g[0], g[1]) if g[2] else grab_frame(cache, g[0], g[1], width=FRAME_W),
                        grabs))

    # HP and ability states, read off the detail stills (native resolution) once they're on disk
    cfg = json.loads((cache / "scan.json").read_text())
    game_h = cfg["crop"][1] if cfg.get("crop") else cfg["probe"]["height"]
    game_w = cfg["crop"][0] if cfg.get("crop") else cfg["probe"]["width"]
    layouts = load_layouts()
    stills = {d["id"]: load_stills(pdir, d["frames"], game_h) for d in deaths}
    for hero in {d.get("hero") for d in deaths}:
        rights = [st[2] for d in deaths if d.get("hero") == hero for st in stills[d["id"]]]
        slots = hero_layout(rights, game_h, layouts.get(hero) if hero else None)
        if hero and slots:
            layouts[hero] = slots
        for d in deaths:
            if d.get("hero") == hero:
                d["hud"] = death_hud(stills[d["id"]], slots, game_h, aspect=game_w / game_h)
    save_layouts(layouts)
    # egomotion: the camera's turn and the body's motion between the 0.1 s detail stills
    for d in deaths:
        rows = motion_trace([(st[0], st[3]) for st in stills[d["id"]]], game_h)
        d["motion"] = {"rows": rows, "trace": motion_describe(rows, (d.get("hud") or {}).get("hp_zero_dt"))}

    # whole-game HP / ability series (hudscan): low-HP episodes, escape presses, fights, stats
    hud_rows = [r for r in (hud_all or {}).get("rows", []) if r["m"] == m["n"]]
    # anchored death times (the feed can be seconds late), kills and ult presses
    death_ts = [G.start + d["t"] for d in deaths]
    event_ts = death_ts + [f["t"] for f in ev["final_blows"]] + [u["used_t"] for u in ults if u["used_t"]]
    hud_game = game_hud(hud_rows, m["start"], event_ts, death_ts,
                        lambda ts: _clock(ts - m["start"])) if hud_rows else {}

    # the facts block: one text per death for the reader's brief (hud + series + presses + feed)
    facts_dir = pdir / "facts"
    facts_dir.mkdir(exist_ok=True)
    obj = ev.get("objective") or {}
    objective = {
        "rounds": [{**G.at(r["t"]), "side": r["side"]} for r in obj.get("rounds", [])],
        "sides": [{**G.at(s["t"]), "side": s["side"]} for s in obj.get("sides", [])],
        "overtime": [{"from": G.at(r["from"])["t"], "to": G.at(r["to"])["t"]} for r in obj.get("overtime", [])],
        "contested": [{"from": G.at(r["from"])["t"], "to": G.at(r["to"])["t"]} for r in obj.get("contested", [])],
        "score": {sd: [{**G.at(s["t"]), "score": s["score"]} for s in v] for sd, v in obj.get("score", {}).items()},
        "series": {k: [[G.at(a)["t"], b] for a, b in v] for k, v in obj.get("series", {}).items()},
    }
    heroes = [{"hero": h["hero"], "role": h.get("role"), "from": G.at(h["from"])["t"], "to": G.at(h["to"])["t"],
               "seconds": h["seconds"]} for h in m.get("heroes", [])]

    tl = [{"t": h["from"], "event": "hero", "hero": h["hero"]} for h in heroes]
    tl += [{"t": r["t"], "event": "round_start", "side": r["side"]} for r in objective["rounds"]]
    tl += [{"t": r["from"], "event": "overtime", "until": r["to"]} for r in objective["overtime"]]
    tl += [{"t": s["t"], "event": "score", "team": sd, "score": s["score"]}
           for sd, v in objective["score"].items() for s in v if s["score"]]
    tl += [{"t": d["t"], "event": "death", "id": d["id"], "killed_by": d["killed_by"],
            "alive": d["alive_before"] and f"{d['alive_before']['ally']}v{d['alive_before']['enemy']}"} for d in deaths]
    tl += [{"t": d["respawned"]["t"], "event": "respawn", "id": d["id"]} for d in deaths if d["respawned"]]
    tl += [{"t": f["t"], "event": "final_blow", "id": f["id"], "victim": f["victim"]} for f in fbs]
    tl += [{"t": u["ready"]["t"], "event": "ult_ready", "id": u["id"]} for u in ult_recs]
    tl += [{"t": u["used"]["t"], "event": "ult_used", "id": u["id"], "held_s": u["held_s"]} for u in ult_recs if u["used"]]
    tl += [{"t": u["ready"]["t"] + u["held_s"], "event": f"ult_{u['outcome']}", "id": u["id"]}
           for u in ult_recs if u["outcome"] != "used"]
    tl = sorted((x for x in tl if x["t"] is not None), key=lambda x: x["t"])
    for x in tl:
        x["clock"] = _clock(x["t"])
    by_hero = (hud_game.get("stats") or {}).get("by_hero") or {}
    for d in deaths:
        hero = d.get("hero")
        learned = [s.get("cooldown_s") for s in (by_hero.get(hero) or {}).get("slots", [])]
        nslots = len(d["hud"]["abilities"][0]) - 1 if d.get("hud", {}).get("abilities") else len(learned)
        names = slot_names(hero, nslots, learned, hero_note_path(hero) if hero else None)
        d["facts"] = death_facts(d, names, learned, hud_game.get("series", []), hud_game.get("presses", []),
                                 hud_game.get("low_episodes", []), tl,
                                 [[G.at(a["t"])["t"], a["ally"], a["enemy"]] for a in ev.get("alive", [])], _clock,
                                 hud_game.get("notices", []))
        (facts_dir / f"{d['id']}.md").write_text(d["facts"] + "\n", encoding="utf-8")

    for name in ("scoreboard_final.jpg", "summary.jpg", "rank.jpg"):
        if (gdir / name).exists():
            shutil.copy(gdir / name, pdir / name)
    from .stats import game_stats
    time_dead = round(sum(d["respawned"]["t"] - d["t"] for d in deaths if d["respawned"]), 1)
    stats = game_stats(cache, m, gdir, time_dead)
    from coachlib.version import version
    packet = {
        "schema": 1,
        "version": version(),
        "player": player,
        "game": {"map": m.get("map"), "mode": m.get("mode"), "queue": m.get("queue"), "result": m.get("result"),
                 "duration_s": round(m["end"] - m["start"], 1), "clock_at_end": m.get("final_clock"),
                 "role": m.get("role"), "session": Path(meta["session_video"]).stem,
                 "session_start_s": m["start"], "video": "../match.mp4"},
        "overview": overview,
        "images": {n.split(".")[0]: n for n in ("scoreboard_final.jpg", "summary.jpg", "rank.jpg")
                   if (pdir / n).exists()},
        "heroes": heroes,
        "counts": {"deaths": len(deaths), "final_blows": len(fbs), "ults": len(ult_recs), "saves": len(saved or []),
                   "ults_used": sum(u["outcome"] == "used" for u in ult_recs),
                   "deaths_per_10min": round(len(deaths) / max(1.0, (m["end"] - m["start"]) / 600), 1),
                   "time_dead_s": round(sum(d["respawned"]["t"] - d["t"] for d in deaths if d["respawned"]), 1),
                   "killed_by": dict(sorted(killers.items(), key=lambda kv: -kv[1])),
                   "death_flags": {f: sum(f in d["flags"] for d in deaths)
                                   for f in sorted({f for d in deaths for f in d["flags"]})}},
        "stats": stats,
        "objective": objective,
        "timeline": tl,
        "deaths": deaths,
        "hud_game": hud_game,
        "hero_notes": {h["hero"]: relpath(hero_note_path(h["hero"]), profile_dir())
                       for h in heroes if h.get("hero") and hero_note_path(h["hero"])},   # relative to the profile dir
        "ults": ult_recs,
        "final_blows": fbs,
        "saves": [{**G.at(x["t"]), "by": x["by"]} for x in saved or []],
        "alive_series": [[G.at(a["t"])["t"], a["ally"], a["enemy"]] for a in ev.get("alive", [])],
        "notes": NOTES,
    }
    from .moments import chains, focus_tests
    packet["focus_tests"], packet["chains"] = focus_tests(packet), chains(packet)
    (pdir / "packet.json").write_text(json.dumps(packet, indent=1, ensure_ascii=False), encoding="utf-8")
    (pdir / "packet_slim.json").write_text(json.dumps(slim_packet(packet), indent=1, ensure_ascii=False), encoding="utf-8")
    _playlist(pdir, deaths, ult_recs)
    from .history import record
    record(packet, m["n"], pdir / "packet.json")
    return packet


def slim_packet(packet: dict) -> dict:
    """The packet without what the writer never judges from: the frame lists, the 2 fps series,
    the raw per-death HUD and motion arrays, the overview sheet list. Why: the writer read the
    274 KB packet.json in full and then paid for it on every one of its ~40 turns (2.6M cached
    tokens per game, 2026-10-16); the facts text, the HUD summary and the movement trace carry
    everything it uses."""
    out = {k: v for k, v in packet.items() if k not in ("overview", "images")}
    out["deaths"] = [{k: v for k, v in d.items() if k not in ("frames", "hud", "motion")}
                     | {"hud_summary": (d.get("hud") or {}).get("summary"), "hud_notices": (d.get("hud") or {}).get("notices"),
                        "hp_zero_dt": (d.get("hud") or {}).get("hp_zero_dt"), "movement": (d.get("motion") or {}).get("trace")}
                     for d in packet.get("deaths", [])]
    out["ults"] = [{k: v for k, v in u.items() if k != "frames"} for u in packet.get("ults", [])]
    out["hud_game"] = {k: v for k, v in (packet.get("hud_game") or {}).items() if k != "series"}
    out["notes"] = list(packet.get("notes", [])) + [
        "packet_slim.json: the same packet without frames, the 2 fps series, the overview list and the raw per-death hud / motion arrays; "
        "deaths[].facts, hud_summary, hud_notices, hp_zero_dt and movement carry what they held. The writer reads this one."]
    return out


def _playlist(pdir: Path, deaths: list[dict], ults: list[dict]) -> None:
    lines = ["#EXTM3U"]
    # no comma inside a title: EXTINF's first comma ends the duration, and VLC cuts the title at the next one
    items = [(d["video_t"], f"{d['id']} {d['clock']} death: {d['hero']} killed by {d['killed_by']}") for d in deaths]
    items += [(u["used"]["video_t"], f"{u['id']} {u['used']['clock']} ult: {u['hero']} held {u['held_s']:.0f}s")
              for u in ults if u["used"]]
    for vt, title in sorted(items):
        lines += [f"#EXTINF:-1,{title.replace(',', ' ')}", f"#EXTVLCOPT:start-time={max(0.0, vt - CLIP_LEAD):.1f}",
                  f"#EXTVLCOPT:stop-time={vt + CLIP_TAIL:.1f}", "../match.mp4"]
    (pdir / "moments.m3u").write_text("\n".join(lines) + "\n", encoding="utf-8")


def packets(cache: Path, out_root: Path | None = None, only: int | None = None, jobs: int = 4,
            refresh: bool = False) -> list[Path]:
    sess = json.loads((cache / "matches.json").read_text())
    evs = {e["n"]: e for e in json.loads((cache / "events.json").read_text())["matches"]}
    video = Path(sess["video"])
    sdir = out_root / session_name(video) if out_root else session_dir(video)
    frames = load_index(cache)["frames"]
    t = np.array([f["t"] for f in frames])
    own = np.load(cache / "own_view.npy")
    from importlib import resources
    elim_tpl = cv2.imread(str(resources.files("owcoach") / "assets" / "eliminated.png"),
                          cv2.IMREAD_GRAYSCALE).astype(np.float32)
    kc_tpl = cv2.imread(str(resources.files("owcoach") / "assets" / "killcam.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32)
    try:
        from .profile import load
        player = load().get("name")
    except Exception:
        player = None
    from .hudscan import hudscan
    hud_all = hudscan(cache, quiet=True)       # cached in hud.json after the first run
    from .saves import notices, saves
    note_scores = notices(cache)["scores"]     # cached in notices.json
    out = []
    for m in sess["matches"]:
        if only is not None and m["n"] != only:
            continue
        gdir = sdir / match_dirname(m)
        if not (gdir / "match.json").exists():
            raise SystemExit(f"{gdir} has no match.json: run `owcoach split` first")
        kc = np.zeros(len(t), bool)
        for d in evs[m["n"]]["deaths"]:
            for k in np.where((t >= d["t"] + KILLCAM_FROM) & (t <= d["t"] + KILLCAM_TO))[0]:
                kc[k] = killcam_score(cv2.imread(str(frame_path(cache, frames[k]))), kc_tpl) >= KC_MIN
        died, after = {}, -1e9
        for d in evs[m["n"]]["deaths"]:
            died[d["t"]] = _death_time(t, lambda k: elim_score(cv2.imread(str(frame_path(cache, frames[k]))), elim_tpl),
                                       d["t"], after)
            after = d["t"] + 8.0      # don't find the previous death's banner
        build_packet(cache, gdir, m, evs[m["n"]], t, own, kc, player, jobs, died, frames, hud_all, refresh,
                     saves(t, note_scores, m["start"], m["end"]))
        out.append(gdir / "packet")
    return out
