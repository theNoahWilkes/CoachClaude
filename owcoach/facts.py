"""The facts block: everything the pipeline knows about one death, as text the reader is handed.

Why: the death readers were told to find their death's `hud` block inside packet.json and quote
it, and it only covered the last 3 s with slots by number. They still built an HP / abilities
column per still from the images (most of their table), read the lead-in stills' HUD by eye,
and inferred from a window they had assembled themselves. Noah's twelve labelled deaths
(labels/deaths.md) all fault the layer above the facts, so the facts should cost the reader
nothing: one block, pasted into the brief, slots by name, HP from -10 s, every press, the low
episode, the feed. The reader spends its looks on what only eyes give: cover, who is in view,
threats, the kill cam.

Deterministic: assembled from the per-death HUD read (0.1 s), the whole-game 2 fps series,
hud_game's presses and low episodes, the timeline and the hero note. Names come from the hero
note's abilities matched to the learned cooldown length of each HUD slot (the HUD shows ability
1 / 2 / 3 = LSHIFT / E / SPACE left to right; the cooldown match guards against a rebinding).
"""
from __future__ import annotations

import re
from pathlib import Path

HUD_BINDS = ("LSHIFT", "E", "SPACE", "F")    # HUD order, left to right
CD_TOL = 2.5                                 # s: a learned cooldown this close to the note's counts as a match
LEAD_IN = 10.0                               # s before the death that the block covers
WINDOW = 30.0                                # s before the death for presses and the feed


def note_abilities(path: str | Path | None) -> list[dict]:
    """[{name, bind, cooldown, rank}] for the hero note's non-ultimate, non-passive abilities, in
    the order the HUD is likely to show them: the HUD binds (LSHIFT, E, SPACE, F), then abilities
    the note gives no bind for, then weapon-bound ones (LMB / RMB)."""
    if not path or not Path(path).exists():
        return []
    text = Path(path).read_text(encoding="utf-8").split("\n## Perks")[0]
    out = []
    for m in re.finditer(r"^- \*\*(.+?)\*\*(?: \((.+?)\))?,? ([^\n]*)", text, re.M):
        name, bind, rest = m.group(1), (m.group(2) or "").upper(), m.group(3)
        if "ultimate" in rest or "passive" in rest:
            continue
        cd = re.search(r"cooldown (\d+(?:\.\d+)?)", rest)
        if bind not in HUD_BINDS and not cd:
            continue
        rank = HUD_BINDS.index(bind) if bind in HUD_BINDS else (10 if bind in ("", "QUICK MELEE") else 20)
        out.append({"name": name, "bind": bind, "cooldown": float(cd.group(1)) if cd else None, "rank": rank})
    return sorted(out, key=lambda a: a["rank"])


def slot_names(hero: str | None, nslots: int, learned: list[float | None], note_path=None) -> list[str]:
    """One name per HUD slot. A slot with a learned cooldown takes the unassigned note ability
    whose cooldown is nearest (within CD_TOL; ties go to the HUD-bind order). A slot without
    one takes the next ability in bind order, but only among the note's HUD-bound abilities,
    so a slot the note can't account for stays "slot N" rather than get a wrong name."""
    abil = note_abilities(note_path)
    bound = [a for a in abil if a["bind"] in HUD_BINDS]
    names: list[str | None] = [None] * nslots
    free = list(abil)
    for j in range(nslots):
        cd = learned[j] if j < len(learned) else None
        if not cd:
            continue
        cands = [a for a in free if a["cooldown"] and abs(a["cooldown"] - cd) <= CD_TOL]
        if cands:
            hit = min(cands, key=lambda a: (abs(a["cooldown"] - cd), a["rank"]))
            names[j] = hit["name"]
            free.remove(hit)
    for j in range(nslots):
        if names[j] is None and j < len(bound) and bound[j] in free:
            names[j] = bound[j]["name"]
            free.remove(bound[j])
    return [n or f"slot {j + 1}" for j, n in enumerate(names)]


def _st(x) -> str:
    """A slot state as short text, from the 2 fps series ("cooling 4") or the 0.1 s read ({state, n})."""
    if isinstance(x, dict):
        return x["state"] + (f" {x['n']}" if x.get("n") is not None else "")
    return str(x)


def _runs(abil: list[list], j: int) -> list[dict]:
    runs: list[dict] = []
    for row in abil:
        r = row[j + 1]
        if r["state"] == "hidden":
            continue
        if runs and runs[-1]["state"] == r["state"]:
            runs[-1]["to"] = row[0]
            if r.get("n") is not None:
                runs[-1]["ns"].append(r["n"])
        else:
            runs.append({"state": r["state"], "from": row[0], "to": row[0], "ns": [r["n"]] if r.get("n") is not None else []})
    return [x for x in runs if round((x["to"] - x["from"]) * 10) >= 2] or runs[:1]


def death_facts(d: dict, names: list[str], learned: list[float | None], series: list, presses: list,
                low_episodes: list, timeline: list, alive_series: list, clock, notices: list | None = None) -> str:
    """The block for one death. `clock(t)` formats a game-relative time."""
    t0 = d["t"]
    hud = d.get("hud") or {}
    notices = notices or []
    L: list[str] = []
    kc = "yes" if d.get("kill_cam") else "none (the game or the player skipped it)"
    ab = d.get("alive_before") or {}
    team = f"{ab['ally']}v{ab['enemy']} ({ab.get('age_s', 0):.0f} s before)" if ab else "unknown"
    obj = d.get("objective") or {}
    objs = ""
    if obj and obj.get("side"):
        objs = f" On {obj['side']}" + (", overtime" if obj.get("overtime") else "") + (", contested" if obj.get("contested") else "")
        if obj.get("ally_dist") is not None:
            objs += f", objective {obj['ally_dist']:.0f} m from the player"
        objs += "."
    ult = "ready" + (f" for {d['ult_held_s']:.0f} s" if d.get("ult_held_s") else "") if d.get("ult_ready") else (
        f"used {d['ult_used_s_before']:.0f} s before" if d.get("ult_used_s_before") else "not ready")
    L.append(f"{d['id']} {d['clock']}, {d.get('hero') or 'hero unknown'}, killed by {d.get('killed_by') or 'unknown'} "
             f"(feed name; the hero is in the kill cam if any). Kill cam: {kc}. Death time from the {d.get('anchor')}"
             + (f", feed {d['feed_lag_s']:.1f} s late" if d.get("feed_lag_s") else "") + f". Team {team}.{objs}"
             f" Ult {ult}. Flags: {', '.join(d.get('flags') or []) or 'none'}.")
    # slots
    if names:
        L.append("HUD slots, left to right: " + "; ".join(
            f"{j + 1} = {n}" + (f" ({learned[j]:.0f} s cooldown)" if j < len(learned) and learned[j] else "")
            for j, n in enumerate(names)) + ". States: ready; cooling with the countdown; blocked (red slash,"
            " can't be used); active (in use: a doll out, a platform placed; the icon may offer a second press); hidden.")
    gn = [n for n in notices if n["from"] <= t0 + 0.5 and n["to"] >= t0 - WINDOW]
    dn = hud.get("notices") or []
    if gn or dn:
        L.append("On screen: " + "; ".join(
            [f"{n['what'].replace('_', ' ')} {n['from'] - t0:+.0f} to {n['to'] - t0:+.0f} s ({n['clock']})" for n in gn]
            + [f"{n['what'].replace('_', ' ')} {n['from']:+.1f} to {n['to']:+.1f} s (0.1 s read)" for n in dn])
            + ". With the scoreboard open the health box reads 0: HP is unreadable there, not zero.")
    nm = lambda j: names[j] if j < len(names) else f"slot {j + 1}"
    # lead-in from the 2 fps series: -LEAD_IN .. -3 s
    lead = [r for r in series if t0 - LEAD_IN - 0.3 <= r[0] <= t0 - 3.2]
    if lead:
        step = []
        for k in range(-int(LEAD_IN), -3):          # the row nearest each whole second
            r = min(lead, key=lambda r: abs(r[0] - (t0 + k)))
            if abs(r[0] - (t0 + k)) <= 0.3 and r not in step:
                step.append(r)
        L.append("Lead-in (2 fps read): " + "; ".join(
            f"{r[0] - t0:+.0f}s HP {r[1] if r[1] is not None else '?'}, " + ", ".join(f"{nm(j)} {_st(s)}" for j, s in enumerate(r[2]))
            for r in step) + ".")
    else:
        L.append(f"Lead-in: no HUD read between -{LEAD_IN:.0f} and -3 s (not the player's own view: kill cam, spectating, a menu or the scoreboard).")
    # the 0.1 s read
    hp = hud.get("hp") or []
    good = [(dt, v) for dt, v, c in hp if v is not None and c >= 0.7]
    pts = []
    for k in range(-30, 1, 5):
        dt = k / 10
        w = [v for t, v in good if abs(t - dt) <= 0.2]
        if w:
            w.sort()
            pts.append(f"{dt:+.1f}s {w[len(w) // 2]}")
    if pts:
        L.append(f"Last 3 s (0.1 s read), HP max {hud.get('hp_max')}: " + ", ".join(pts)
                 + (f". HP first reads 0 at {hud['hp_zero_dt']:+.1f} s." if hud.get("hp_zero_dt") is not None else ". HP never read 0 (HUD hidden or the death is later than the stills)."))
    elif hp:
        why = ", ".join(sorted({n["what"].replace("_", " ") for n in (hud.get("notices") or [])})) or "kill cam, spectating or a menu"
        L.append(f"Last 3 s (0.1 s read): no HP or slot read in the window (HUD hidden: {why}). The death time rests on the {d.get('anchor')} anchor.")
    abil = hud.get("abilities") or []
    nslots = len(abil[0]) - 1 if abil else 0
    for j in range(nslots):
        runs = _runs(abil, j)
        if not runs:
            continue
        if len(runs) == 1 and runs[0]["state"] == "ready":
            L.append(f"  {nm(j)}: ready throughout the last 3 s.")
            continue
        bits = []
        for i, x in enumerate(runs):
            span = f"{x['from']:+.1f} to {x['to']:+.1f} s"
            if x["state"] == "cooling" and i > 0 and runs[i - 1]["state"] == "ready":
                hp_at = next((v for dt, v in reversed(good) if dt <= x["from"] + 0.05), None)
                bits.append(f"pressed at {x['from']:+.1f} s" + (f" at {hp_at} HP" if hp_at is not None else "") + f", cooling {x['ns'][0] if x['ns'] else '?'} after")
            elif x["ns"]:
                bits.append(f"{x['state']} {x['ns'][0]}->{x['ns'][-1]} ({span})")
            else:
                bits.append(f"{x['state']} ({span})")
        L.append(f"  {nm(j)}: " + ", ".join(bits) + ".")
    mo = d.get("motion") or {}
    if mo.get("trace"):
        L.append("Movement in the last 3 s (camera-relative, from optical flow between the 0.1 s stills; degrees assume the default FOV; "
                 "toward whom or toward what cover is for the stills to say): " + mo["trace"] + ".")
    # presses in the window
    win = [p for p in presses if t0 - WINDOW <= p["t"] <= t0 + 0.5]
    if win:
        L.append(f"Presses in the {WINDOW:.0f} s before: " + "; ".join(
            f"{p['clock']} ({p['t'] - t0:+.0f}s) {nm(p['slot'] - 1)}" + (f" at {p['hp']} HP" if p.get("hp") is not None else " (HP unreadable)") + f", {p['context']}" for p in win) + ".")
    else:
        L.append(f"No presses in the {WINDOW:.0f} s before.")
    # the low episode that ends in this death
    ep = next((e for e in low_episodes if e["from"] <= t0 + 0.5 and e["to"] >= t0 - 3.0), None)
    if ep:
        at = ", ".join(f"{nm(j)} {s}" for j, s in enumerate(ep.get("slots_at_start", [])))
        before = "; ".join(f"{nm(int(k) - 1)} pressed {v['pressed_s_before']:.0f} s earlier at {v['hp']} HP ({v['context']})"
                           for k, v in (ep.get("last_press_before") or {}).items())
        during = ", ".join(f"{nm(p['slot'] - 1)}" + (f" at {p['hp']} HP" if p.get("hp") is not None else "") for p in ep.get("pressed_in", [])) or "nothing"
        L.append(f"Under half HP from {ep['clock']} ({ep['from'] - t0:+.0f}s), min {ep['min_hp']}: at that moment {at}."
                 + (f" Before it: {before}." if before else "") + f" Pressed while low: {during}. Outcome: {ep['outcome']}.")
    else:
        L.append("No low-HP episode recorded before this death (burst from above half, or the HUD was hidden).")
    # earlier low episodes in this life
    prev_death = max((x["t"] for x in timeline if x["event"] == "respawn" and x["t"] < t0), default=None)
    earlier = [e for e in low_episodes if e["to"] < t0 - 3.0 and (prev_death is None or e["from"] >= prev_death)]
    if earlier:
        L.append("Earlier low episodes this life: " + "; ".join(
            f"{e['clock']} min {e['min_hp']}, {e['outcome']}, pressed " + (", ".join(nm(p['slot'] - 1) for p in e.get('pressed_in', [])) or "nothing")
            for e in earlier) + ".")
    # feed and events
    resp = (d.get("respawned") or {}).get("t", t0 + 12)
    ev = [x for x in timeline if t0 - WINDOW <= x["t"] <= resp + 0.5 and not (x["event"] == "death" and x.get("id") == d["id"])]
    if ev:
        def fmt(x):
            e = x["event"]
            if e == "death":
                return f"{x['clock']} {x['id']} the player died ({x.get('alive')})"
            if e == "final_blow":
                return f"{x['clock']} {x['id']} the player's final blow on {x.get('victim')}"
            if e == "respawn":
                return f"{x['clock']} respawn" + (f" ({x['id']})" if x.get("id") == d["id"] else "")
            if e in ("ult_used", "ult_ready"):
                return f"{x['clock']} {x['id']} {e.replace('_', ' ')}"
            if e == "score":
                return f"{x['clock']} score {x.get('team')} {x.get('score')}"
            return f"{x['clock']} {e}" + (f" {x.get('side', '')}" if e == "round_start" else "")
        L.append("Events from -30 s to the respawn: " + "; ".join(fmt(x) for x in ev) + ".")
    al = [a for a in alive_series if t0 - WINDOW <= a[0] <= t0 + 0.5]
    if al:
        L.append("Alive counts (ally v enemy): " + ", ".join(f"{clock(a[0])} {a[1]}v{a[2]}" for a in al) + ".")
    return "\n".join(L)
