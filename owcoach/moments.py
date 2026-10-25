"""Focus tests, death chains and the triage digest (ADR 0012), from packet.json for free.

The coach used to find the moments worth coaching by reading every image: every death's stills
and the whole match as overview sheets. Most of what made a moment worth it was already text.
This module lists it so that a text-only triage can pick the moments before any image is read,
and so readers look at the overview cells of the focus tests only.

- **Focus tests** are the windows where a focus could be tested: every low-HP episode, every
  stretch with the team down two or more while the player is alive, and the 20 s after each
  respawn. They are facts (`packet.json` → `focus_tests`, every kind for every match); which
  kinds test the current focus is matched from its wording when the digest is written.
- **Death chains** are deaths that follow from the one before: a death within `SHORT_LIFE` of
  respawning (the `short_life` flag). One poor decision and its consequence are one moment
  (the player, on m03 Hollywood 2026-10-20: a Fade into the open with ult ready, then a forced
  fight out of spawn 20 s later with the ult that should have been used).
- **The digest** is one match as text for the triage: header, every death's facts block, the
  chains, ults, fights and the focus tests, with the match folder's prefix so every moment can
  be cited as `m03 d04` or `m03 5:18`.
"""
from __future__ import annotations

import re
from pathlib import Path

RESPAWN_WINDOW = 20.0        # s after a respawn: the walk back in, where waiting for the team is tested
DOWN_BY = 2                  # enemies alive minus allies alive that makes a "down two" stretch
MIN_DOWN_S = 2.0             # s: a shorter stretch is a counter blip, not a situation
MERGE_GAP_S = 1.5            # s: two down-two stretches this close are one
DEAD_PAD_S = 12.0            # s of DEAD after a death with no respawn read (the match ended or it was missed)

KINDS = {"low": "under half HP", "down_two": "team down two or more", "respawn": "the 20 s after a respawn"}
# Which focus test kinds a focus's trigger names. Matched on the triggers only (kinds_for), since
# the action half names walls and spawn too ("back off to the last wall toward your spawn").
KIND_WORDS = {
    "low": r"half hp|half health|under half|low hp|low health|\bescape\b|\bwall\b|\bcover\b|line of sight",
    "down_two": r"down two|down 2|two or more|2 or more|\b[1-3]v[3-5]\b",
    "respawn": r"respawn|out of spawn|\bspawn\b",
}


def _clock(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"


def _dead_spans(packet: dict) -> list[tuple[float, float]]:
    return [(d["t"], (d.get("respawned") or {}).get("t") or d["t"] + DEAD_PAD_S) for d in packet.get("deaths") or []]


def _death_in(packet: dict, lo: float, hi: float) -> str | None:
    return next((d["id"] for d in packet.get("deaths") or [] if lo <= d["t"] <= hi), None)


def _minus(spans: list[tuple[float, float]], cut: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for a, b in spans:
        parts = [(a, b)]
        for c, d in cut:
            parts = [p for x, y in parts for p in ((x, min(y, c)), (max(x, d), y)) if p[1] > p[0]]
        out += parts
    return out


def down_two(packet: dict) -> list[tuple[float, float, int, int]]:
    """Stretches with the team down DOWN_BY or more while the player is alive:
    [(from, to, fewest allies, most enemies)]. The counter holds its value until the next reading."""
    rows = [r for r in packet.get("alive_series") or [] if r[0] is not None]
    end = (packet.get("game") or {}).get("duration_s") or (rows[-1][0] if rows else 0)
    raw = []
    for i, (t, ally, enemy) in enumerate(rows):
        nxt = rows[i + 1][0] if i + 1 < len(rows) else end
        if ally is not None and enemy is not None and enemy - ally >= DOWN_BY and nxt > t:
            if raw and t - raw[-1][1] <= MERGE_GAP_S:
                raw[-1] = (raw[-1][0], nxt, min(raw[-1][2], ally), max(raw[-1][3], enemy))
            else:
                raw.append((t, nxt, ally, enemy))
    out = []
    for a, b, ally, enemy in raw:
        for x, y in _minus([(a, b)], _dead_spans(packet)):
            if y - x >= MIN_DOWN_S:
                out.append((x, y, ally, enemy))
    return out


def _alive_at(packet: dict, t: float) -> tuple[int, int] | None:
    last = None
    for r in packet.get("alive_series") or []:
        if r[0] is not None and r[0] <= t:
            last = r
    return (last[1], last[2]) if last and last[1] is not None and last[2] is not None else None


def focus_tests(packet: dict) -> list[dict]:
    """Every focus test window of a match, in time order, with ids f01, f02, ..."""
    tests = []
    for e in (packet.get("hud_game") or {}).get("low_episodes") or []:
        died = e.get("outcome") == "died"
        tests.append({"kind": "low", "from": e["from"], "to": e["to"], "hero": e.get("hero"),
                      "what": f"min {e.get('min_hp')}/{e.get('max')}, {'died' if died else 'recovered'}",
                      "death": _death_in(packet, e["from"] - 1, e["to"] + 2.5) if died else None})
    for a, b, ally, enemy in down_two(packet):
        tests.append({"kind": "down_two", "from": round(a, 1), "to": round(b, 1), "hero": None,
                      "what": f"team down two ({ally}v{enemy} at worst)", "death": _death_in(packet, a, b + 0.5)})
    end = (packet.get("game") or {}).get("duration_s")
    for d in packet.get("deaths") or []:
        r = (d.get("respawned") or {}).get("t")
        if r is None:
            continue
        hi = min(r + RESPAWN_WINDOW, end) if end else r + RESPAWN_WINDOW
        alive = _alive_at(packet, r)
        tests.append({"kind": "respawn", "from": r, "to": round(hi, 1), "hero": d.get("hero"),
                      "what": f"respawn after {d['id']}" + (f", team {alive[0]}v{alive[1]}" if alive else ""),
                      "death": _death_in(packet, r, hi)})
    tests.sort(key=lambda x: (x["from"], x["kind"]))
    for i, x in enumerate(tests, 1):
        x["id"] = f"f{i:02d}"
        x["clock"], x["to_clock"] = _clock(x["from"]), _clock(x["to"])
    return [{k: x[k] for k in ("id", "kind", "from", "to", "clock", "to_clock", "hero", "what", "death")} for x in tests]


def chains(packet: dict) -> list[dict]:
    """Runs of deaths where each one came within SHORT_LIFE of respawning from the one before."""
    out, cur = [], []
    for d in packet.get("deaths") or []:
        if cur and "short_life" in (d.get("flags") or []):
            cur.append(d)
        else:
            if len(cur) > 1:
                out.append(cur)
            cur = [d]
    if len(cur) > 1:
        out.append(cur)
    return [{"deaths": [d["id"] for d in c], "from": c[0]["t"], "to": c[-1]["t"],
             "clock": c[0]["clock"], "to_clock": c[-1]["clock"],
             "alive_for_s": [d.get("alive_for_s") for d in c[1:]]} for c in out]


def triggers(focus: str) -> list[str]:
    """The trigger of each part of a focus: a habit is "when X, do Y", and parts are split by ";".
    The trigger is the text before the first comma ("When you're under half HP and your escape is
    on cooldown"; "on respawn")."""
    return [p.split(",")[0] for p in re.split(r";|\.\s", focus or "") if p.strip()]


def kinds_for(focus: str) -> list[str]:
    """The focus test kinds a focus's triggers name; then its whole wording; every kind when
    neither names one."""
    for text in (" | ".join(triggers(focus)), focus or ""):
        hit = [k for k, rx in KIND_WORDS.items() if re.search(rx, text, re.I)]
        if hit:
            return hit
    return list(KINDS)


def _ab(x: dict | None) -> str:
    return f"{x['ally']}v{x['enemy']}" if x and x.get("ally") is not None else "?"


def digest(packet: dict, prefix: str, focuses: list[str]) -> str:
    """One match as text for the triage. `prefix` is the match folder's (m03); `focuses` the
    current focus bullets (empty when there is none)."""
    g, c = packet.get("game") or {}, packet.get("counts") or {}
    heroes = ", ".join(f"{h['hero']} {h.get('seconds', 0) / 60:.0f} min" for h in packet.get("heroes") or []) or "hero unknown"
    tests = packet.get("focus_tests") or focus_tests(packet)
    chs = packet.get("chains") if "chains" in packet else chains(packet)
    L = [f"# {prefix} {g.get('map') or '?'} {g.get('result') or ''} ({g.get('mode') or '?'}, {_clock(g.get('duration_s') or 0)})".rstrip(),
         f"Heroes: {heroes}. Deaths {c.get('deaths', 0)}, final blows {c.get('final_blows', 0)}, "
         f"ults used {c.get('ults_used', 0)} of {c.get('ults', 0)}.", ""]
    L.append("## Deaths")
    for d in packet.get("deaths") or []:
        L += [f"### {prefix} {d['id']} {d['clock']}", (d.get("facts") or "(no facts block)").rstrip(), ""]
    if not packet.get("deaths"):
        L += ["None.", ""]
    L.append("## Chains (a death within 20 s of respawning from the one before: one story, told from its first death)")
    L += [f"- {prefix} " + " → ".join(ch["deaths"]) + f", {ch['clock']} to {ch['to_clock']}"
          + " (alive " + ", ".join(f"{a:.0f} s" for a in ch["alive_for_s"] if a is not None) + " after respawning)" for ch in chs] or ["None."]
    L += ["", "## Ults"]
    for u in packet.get("ults") or []:
        r, s = u.get("ready") or {}, u.get("used") or {}
        L.append(f"- {prefix} {u['id']} {u.get('hero') or ''}: ready {r.get('clock', '?')}, "
                 + (f"used {s['clock']}" if s else u.get("outcome", "not used")) + f", held {u.get('held_s', 0):.0f} s"
                 + (f"; flags {', '.join(u['flags'])}" if u.get("flags") else ""))
    if not packet.get("ults"):
        L.append("None.")
    L += ["", "## Fights (from the HUD: HP changes, kills, deaths, ults)"]
    fights = (packet.get("hud_game") or {}).get("fights") or []
    L.append(", ".join(f"{f['from']}-{f['to']}" for f in fights) if fights else "None read.")
    L += ["", "## Final blows"]
    fbs = packet.get("final_blows") or []
    L.append(", ".join(f"{k['id']} {k['clock']} {_ab(k.get('alive_before'))}" for k in fbs) if fbs else "None.")
    L += ["", "## Focus tests"]
    if not focuses:
        L.append("No current focus. Every window, for reference:")
        groups = [(None, tests)]
    else:
        groups = [(f, [x for x in tests if x["kind"] in kinds_for(f)]) for f in focuses]
    for f, xs in groups:
        if f:
            L.append(f"Focus: {f}  (kinds: {', '.join(KINDS[k] for k in kinds_for(f))})")
        L += [f"- {prefix} {x['id']} {x['clock']}-{x['to_clock']} {KINDS[x['kind']]}: {x['what']}"
              + (f", {x['hero']}" if x.get("hero") else "") + (f", ends in {x['death']}" if x.get("death") else "") for x in xs] or ["- none"]
    return "\n".join(L).rstrip() + "\n"


def session_digest(session: Path, games: list[Path], focuses: list[str]) -> Path:
    """Every match of the session in one file, <session>/digest.md, for the triage."""
    import json
    parts = []
    for g in games:
        pk = json.loads((g / "packet" / "packet.json").read_text(encoding="utf-8"))
        parts.append(digest(pk, g.name[:3], focuses))
    head = (f"# Digest of {session.name}: {len(games)} match{'es' if len(games) != 1 else ''}\n"
            "Facts only, read locally from each match's packet. Cite a moment as <match> <id> (m03 d04) or <match> <clock> (m03 5:18).\n\n")
    out = session / "digest.md"
    out.write_text(head + "\n".join(parts), encoding="utf-8")
    return out
