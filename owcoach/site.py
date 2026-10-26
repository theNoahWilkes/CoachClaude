"""`owcoach site`: the library as one HTML page, <library>/coaching.html.

This module is the Overwatch collector: it knows the library layout (session.json, packet.json,
coaching.md, frames/, moments.m3u, the profile's lessons and focus proposal, history.sqlite) and
builds the plain tree that `coachlib.site.render` turns into the page. The sidebar is days ->
games; a day page holds the day's session and combined summaries; a game page has the stats table, the scoreboard, a timeline, the
clip seekable from each moment, the report, and every death / ult / final blow with its stills,
facts line and reader notes; Lessons and the Focus proposal are pages. Nothing is copied: every
image and clip is a relative link from the library root.

Rebuilt at the end of `owcoach run` and `owcoach coach`.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from coachlib.launcher import write_link
from coachlib.site import num, slug, write
from coachlib.version import version

from .compress import state as compress_state
from .config import library, profile_dir

PAGE_NAME = "coaching.html"
NOT_READ = "–"
SESSION_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) - (\d{2})\.(\d{2})\.(\d{2})\.(\d+)$")
DATE_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) - (.+)$")
COLUMNS = [{"key": "played", "label": "played", "align": "left"}, {"key": "map", "label": "map", "align": "left"},
           {"key": "mode", "label": "mode", "align": "left"}, {"key": "result", "label": "result", "align": "left"},
           {"key": "hero", "label": "hero", "align": "left"}, {"key": "clock", "label": "clock"},
           {"key": "deaths", "label": "deaths"}, {"key": "d10", "label": "D/10"}, {"key": "dead_pct", "label": "dead %"},
           {"key": "h10", "label": "heal/10"}, {"key": "dmg10", "label": "dmg/10"}, {"key": "focus", "label": "focus"},
           {"key": "coached", "label": "coached"}, {"key": "clip", "label": "clip", "align": "left"}]
STOPLIGHT_RE = re.compile(r"^\s*[-*]\s*(🟢|🟡|🔴|⚪)", re.M)     # a report's "## Focus" lines (ADR 0012)
# A clock (5:18) or a moment id (d04, u02, k07) in a report, optionally after a match (m03) in a
# session summary. Not inside a link's text or target, not part of a longer word or time.
MOMENT_RE = re.compile(r"(?<![\w\[/#@:.])(?:(m\d{2}) )?(?:([duk]\d{2})|(\d{1,2}:\d{2}))(?![\w\]:])")
LEAD_S = {"d": 10.0, "u": 5.0, "k": 5.0, "clock": 3.0}      # seconds of lead-in before a linked moment


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _json(p: Path) -> dict | None:
    s = _read(p)
    if s is None:
        return None
    try:
        return json.loads(s)
    except ValueError:
        return None


def _rel(p: Path) -> str:
    """Library-relative URL (forward slashes, percent-encoded)."""
    return quote(p.relative_to(library()).as_posix(), safe="/")


def _mmss(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"


def _played(session_name: str, start_s: float = 0.0) -> datetime | None:
    m = SESSION_RE.match(session_name)
    if not m:
        return None
    y, mo, d, h, mi, s, _ = map(int, m.groups())
    return datetime(y, mo, d, h, mi, s) + timedelta(seconds=start_s)


def _stills(packet_url: str, frames: list[dict]) -> list[dict]:
    """The sampled stills, not the 0.1 s extras (those stay one click away in the folder)."""
    return [{"src": f"{packet_url}/{quote(f['file'])}", "label": f"{f['dt']:+.1f}", "title": f"{f['kind']} {f['dt']:+.1f} s"}
            for f in frames if not f.get("extra")]


def _clip_index(pk: dict) -> dict:
    """What a report's text can link to in this match's clip: video_t per moment id, and the
    offset from the game clock to the video (constant within a match)."""
    ids: dict[str, float] = {}
    offs = []
    for d in pk.get("deaths") or []:
        if d.get("video_t") is not None:
            ids[d["id"]] = d["video_t"]; offs.append(d["video_t"] - d["t"])
    for k in pk.get("final_blows") or []:
        if k.get("video_t") is not None:
            ids[k["id"]] = k["video_t"]; offs.append(k["video_t"] - k["t"])
    for u in pk.get("ults") or []:
        at = u.get("used") or u.get("ready") or {}
        if at.get("video_t") is not None:
            ids[u["id"]] = at["video_t"]; offs.append(at["video_t"] - at["t"])
    return {"ids": ids, "offset": offs[0] if offs else 0.0, "duration": (pk.get("game") or {}).get("duration_s") or 0}


def link_moments(text: str | None, games: dict[str | None, dict]) -> str | None:
    """Turn the clocks and moment ids in a report into clip links (`#g/<game id>@<s>`).
    `games` maps a match prefix ("m03") to {"id": game id, **_clip_index}; the key None is the
    match a bare clock belongs to (a match report), absent in a session summary."""
    if not text:
        return text

    def sub(m: re.Match) -> str:
        g = games.get(m.group(1)) if m.group(1) else games.get(None)
        if not g:
            return m.group(0)
        if m.group(2):
            vt = g["ids"].get(m.group(2))
            if vt is None:
                return m.group(0)
            vt -= LEAD_S[m.group(2)[0]]
        else:
            mm, ss = m.group(3).split(":")
            t = int(mm) * 60 + int(ss)
            if int(ss) > 59 or (g["duration"] and t > g["duration"] + 30):
                return m.group(0)
            vt = t + g["offset"] - LEAD_S["clock"]
        return f"[{m.group(0)}](#g/{g['id']}@{max(0.0, vt):.1f})"

    # leave code spans alone
    return "".join(part if part.startswith("`") else MOMENT_RE.sub(sub, part) for part in re.split(r"(`[^`\n]*`)", text))


def stoplights(report: str | None) -> str:
    """The stoplight per focus from a report's Focus section, e.g. '🟢🟡'."""
    return "".join(STOPLIGHT_RE.findall(report or ""))


def _stats_table(m: dict) -> dict:
    pl, p10 = m.get("player") or {}, m.get("per10") or {}
    tm, en = m.get("teammate_same_role_per10") or {}, m.get("enemy_same_role_per10") or []
    en_avg = {}
    for k in ("E", "A", "D", "DMG", "H", "MIT"):
        vals = [x[k] for x in en if isinstance(x, dict) and x.get(k) is not None]
        en_avg[k] = sum(vals) / len(vals) if vals else None
    rows = []
    for lab, tot, per, t2, e2, dg in (("Deaths", m.get("deaths"), p10.get("D"), tm.get("D"), en_avg.get("D"), 1),
                                      ("Eliminations", pl.get("E"), p10.get("E"), tm.get("E"), en_avg.get("E"), 1),
                                      ("Assists", pl.get("A"), p10.get("A"), tm.get("A"), en_avg.get("A"), 1),
                                      ("Damage", pl.get("DMG"), p10.get("DMG"), tm.get("DMG"), en_avg.get("DMG"), 0),
                                      ("Healing", pl.get("H"), p10.get("H"), tm.get("H"), en_avg.get("H"), 0),
                                      ("Mitigation", pl.get("MIT"), p10.get("MIT"), tm.get("MIT"), en_avg.get("MIT"), 0)):
        rows.append([lab, num(tot, default=NOT_READ), num(per, dg, NOT_READ), num(t2, dg, NOT_READ), num(e2, dg, NOT_READ)])
    if m.get("saves") is not None:      # from the SAVED notice (saves.py), not the scoreboard
        sv10 = m["saves"] * 600 / m["per10_s"] if m.get("per10_s") else None
        rows.append(["Saves", num(m["saves"]), num(sv10, 1, NOT_READ), "", ""])
    rows.append(["Time dead", f"{num(m.get('time_dead_s'))} s", f"{num(m.get('dead_pct'), 1)} %", "", ""])
    rows.append(["Ults used", f"{num(m.get('ults_used'))} of {num(m.get('ults'))}", "", "", ""])
    note = [f"Final blows {num(m.get('final_blows'))}."]
    if m.get("death_flags"):
        note.append("Death flags: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in m["death_flags"].items()) + ".")
    if m.get("killed_by"):
        note.append("Killed by (kill-feed names): " + ", ".join(f"{k} ×{v}" for k, v in m["killed_by"].items()) + ".")
    note.append("Partner = your team's other player in your role, enemies = the average of theirs, both per 10.")
    note.append(f"A {NOT_READ} means it wasn't read off the final scoreboard.")
    return {"header": ["", "game", "per 10", "partner", "enemies"], "rows": rows,
            "note": " ".join(html.escape(x) for x in note)}


def _game(gdir: Path, session: dict) -> dict:
    pk_dir = gdir / "packet"
    pk = _json(pk_dir / "packet.json")
    mj = _json(gdir / "match.json") or {}
    coached = (pk_dir / "coaching.md").exists()
    g: dict = {"id": f"{session['id']}--{slug(gdir.name)}", "dir": gdir.name, "title": gdir.name, "coached": coached,
               "processed": pk is not None, "result": mj.get("result") or "none", "cells": {}, "warnings": [],
               "tables": [], "images": [], "links": [], "moments": [], "details": []}
    folder = f'<a href="{_rel(gdir)}" target="_blank">folder</a>'
    for name in ("scoreboard_final.jpg", "summary.jpg", "rank.jpg"):
        if (gdir / name).exists():
            g["images"].append({"src": _rel(gdir / name), "alt": name[:-4]})
    if (gdir / "match.mp4").exists():
        g["video"] = _rel(gdir / "match.mp4")
        if (pk_dir / "moments.m3u").exists():
            g["links"].append({"label": "moments.m3u (VLC)", "href": _rel(pk_dir / "moments.m3u")})
        g["links"].append({"label": "match.mp4", "href": g["video"], "blank": True})
    clip_cell = {"compressed": "compressed", "big": "lossless"}.get(compress_state(gdir) or "", "")
    if not pk:
        g["title"] = " · ".join(str(x) for x in (mj.get("map") or gdir.name, (mj.get("result") or "").capitalize()) if x)
        g["nav"] = " · ".join(str(x) for x in (mj.get("map") or gdir.name, mj.get("hero_final")) if x)
        g["sub"] = " · ".join(x for x in (mj.get("mode"), folder) if x)
        g["warnings"].append("No packet for this game (not processed, or no match found in the clip).")
        g["cells"] = {"played": session["date"], "map": {"text": mj.get("map") or gdir.name, "href": f"#g/{g['id']}"},
                      "mode": mj.get("mode") or "", "result": {"text": mj.get("result") or "", "cls": f"res-{mj.get('result')}"},
                      "hero": mj.get("hero_final") or "", "coached": "no packet", "clip": clip_cell}
        return g
    game, counts, stats = pk["game"], pk.get("counts") or {}, pk.get("stats") or {}
    hero_names: list[str] = []
    for h in pk.get("heroes") or []:
        if h["hero"] not in hero_names:
            hero_names.append(h["hero"])
    hero = " → ".join(hero_names)
    played = _played(session["name"], game.get("session_start_s") or 0.0)
    per10 = stats.get("player_per10") or {}
    clock_s = stats.get("clock_s")
    dead_pct = (round(100 * counts["time_dead_s"] / clock_s, 1) if counts.get("time_dead_s") is not None and clock_s else None)
    m = {"deaths": counts.get("deaths"), "time_dead_s": counts.get("time_dead_s"), "dead_pct": dead_pct,
         "ults": counts.get("ults"), "ults_used": counts.get("ults_used"), "final_blows": counts.get("final_blows"),
         "saves": counts.get("saves"), "per10_s": clock_s or game.get("duration_s"),
         "death_flags": counts.get("death_flags") or {}, "killed_by": counts.get("killed_by") or {},
         "player": stats.get("player") or {}, "per10": per10,
         "teammate_same_role_per10": stats.get("teammate_same_role_per10"), "enemy_same_role_per10": stats.get("enemy_same_role_per10")}
    result = game.get("result") or "none"
    g["result"] = result
    g["title"] = " · ".join(x for x in (game.get("map") or gdir.name, result.capitalize() if result != "none" else "", hero) if x)
    g["nav"] = " · ".join(x for x in (game.get("map") or gdir.name, hero) if x)
    g["sub"] = " · ".join(x for x in (game.get("mode"), game.get("queue"), played.strftime("%Y-%m-%d %H:%M") if played else None,
                                      f"clock {stats.get('clock') or game.get('clock_at_end')}" if stats.get("clock") or game.get("clock_at_end") else None,
                                      f"{_mmss(game['duration_s'])} of video" if game.get("duration_s") else None, folder) if x)
    g["cells"] = {"played": played.strftime("%Y-%m-%d %H:%M") if played else session["date"],
                  "map": {"text": game.get("map") or gdir.name, "href": f"#g/{g['id']}"}, "mode": game.get("mode") or "",
                  "result": {"text": result if result != "none" else "", "cls": f"res-{result}"}, "hero": hero,
                  "clock": stats.get("clock") or "", "deaths": num(counts.get("deaths")), "d10": num(counts.get("deaths_per_10min"), 1),
                  "dead_pct": num(dead_pct, 1), "h10": num(per10.get("H")), "dmg10": num(per10.get("DMG")), "coached": "✓" if coached else "", "clip": clip_cell}
    g["tables"].append(_stats_table(m))
    hud = pk.get("hud_game") or {}
    g["timeline"] = {
        "duration": game.get("duration_s") or 0,
        "spans": [{"from": f["from_t"], "to": f["to_t"], "lane": "main", "cls": "tl-fight", "label": f"fight {_mmss(f['from_t'])}–{_mmss(f['to_t'])}"}
                  for f in hud.get("fights") or []]
                 + [{"from": x["from"], "to": x["to"], "lane": "bottom", "cls": "tl-low-died" if x.get("outcome") == "died" else "tl-low",
                     "label": f"under half HP {_mmss(x['from'])}–{_mmss(x['to'])}, min {x.get('min_hp')}, {x.get('outcome')}"}
                    for x in hud.get("low_episodes") or []]
                 + [{"from": (u.get("ready") or {}).get("t"), "to": (u.get("used") or {}).get("t") if u.get("used") else game.get("duration_s") or 0,
                     "lane": "top", "cls": "tl-ult", "label": f"{u['id']} ready {_mmss((u.get('ready') or {}).get('t') or 0)}"
                     + (f", used {_mmss(u['used']['t'])}" if u.get("used") else ", not used")}
                    for u in pk.get("ults") or [] if (u.get("ready") or {}).get("t") is not None],
        "marks": [{"t": u["used"]["t"], "lane": "top", "cls": "tl-ult-use", "label": f"{u['id']} used {_mmss(u['used']['t'])}", "id": u["id"]}
                  for u in pk.get("ults") or [] if u.get("used")]
                 + [{"t": k["t"], "lane": "bottom", "cls": "tl-fb", "label": f"{k['id']} final blow {k['clock']}", "id": k["id"]}
                    for k in pk.get("final_blows") or []],
        "deaths": [{"id": d["id"], "t": d["t"], "to": (d.get("respawned") or {}).get("t"), "label": f"{d['id']} death {d['clock']}"}
                   for d in pk.get("deaths") or []],
    }
    g["clips"] = _clip_index(pk)
    report = _read(pk_dir / "coaching.md")
    g["cells"]["focus"] = stoplights(report)
    g["report_md"] = link_moments(report, {None: {"id": g["id"], **g["clips"]}}) if g.get("video") else report
    if not g["report_md"]:
        g["warnings"].append("Not coached yet. <code>owcoach coach</code> writes the report.")
    purl = _rel(pk_dir)
    for d in pk.get("deaths") or []:
        ab = d.get("alive_before") or {}
        bits = [f"killed by {d.get('killed_by') or '?'}", f"{ab.get('ally', '?')}v{ab.get('enemy', '?')}", (d.get("objective") or {}).get("side") or ""]
        flags = [k for k in ("first_down", "team_behind", "died_with_ult", "repeat_killer", "even_fight", "overtime")
                 if k in (d.get("flags") or []) or d.get(k)]
        if d.get("ult_ready"):
            flags.append("ult ready")
        details = []
        if (f := _read(pk_dir / "facts" / f"{d['id']}.md")):
            details.append({"summary": "Facts (the packet's measured line)", "pre": f})
        if (n := _read(pk_dir / "notes" / f"{d['id']}.md")):
            details.append({"summary": "Reader notes", "md": n})
        g["moments"].append({"id": d["id"], "kind": "death", "t": d["t"], "clock": d["clock"], "video_t": d.get("video_t", d["t"]),
                             "title": f"{d['id']} {d['clock']} · {d.get('hero') or ''} " + " · ".join(b for b in bits if b),
                             "extra": f"respawn {d['respawned']['clock']}" if d.get("respawned") else None,
                             "flags": flags, "stills": _stills(purl, d.get("frames") or []), "details": details})
    for u in pk.get("ults") or []:
        r, s = u.get("ready") or {}, u.get("used") or {}
        held = f"held {u['held_s']:.0f} s" if u.get("held_s") is not None else ""
        g["moments"].append({"id": u["id"], "kind": "ult", "t": s.get("t") if s else r.get("t"), "clock": s.get("clock") or r.get("clock"),
                             "video_t": s.get("video_t") if s else r.get("video_t"),
                             "title": f"{u['id']} {s.get('clock') or r.get('clock')} · {u.get('hero') or ''} ult {u.get('outcome')}"
                                      + (f", ready {r.get('clock')}, {held}" if r and held else ""),
                             "flags": u.get("flags") or [], "stills": _stills(purl, u.get("frames") or []), "details": []})
    for k in pk.get("final_blows") or []:
        ab = k.get("alive_before") or {}
        g["moments"].append({"id": k["id"], "kind": "final_blow", "t": k["t"], "clock": k["clock"], "video_t": k.get("video_t", k["t"]),
                             "title": f"{k['id']} {k['clock']} · final blow on {k.get('victim') or '?'} · {ab.get('ally', '?')}v{ab.get('enemy', '?')}",
                             "flags": [], "stills": [], "details": []})
    g["moments"].sort(key=lambda x: (x["t"] is None, x["t"] or 0))
    if pk.get("overview"):
        cells = "".join(f'<a href="{purl}/{quote(o["file"])}" target="_blank"><img src="{purl}/{quote(o["file"])}" loading="lazy" alt="{o["from"]}"><span>{o["from"]}</span></a>'
                        for o in pk["overview"])
        g["details"].append({"summary": f"Overview stills ({len(pk['overview'])} cells, 10 s apart)", "html": f'<div class="strip wrap">{cells}</div>'})
    for n in ("summary", "ults") + tuple(f"{k}_{i:02d}" for k in ("tests", "overview") for i in range(1, 10)):
        if (t := _read(pk_dir / "notes" / f"{n}.md")):
            g["details"].append({"summary": f"Reader notes: {n}", "md": t})
    if pk.get("notes"):
        g["details"].append({"summary": "What the packet measures (and doesn't)", "html": "<ul>" + "".join(f"<li>{x}</li>" for x in pk["notes"]) + "</ul>"})
    return g


def _trend_table(t: dict | None) -> dict | None:
    if not t or not t.get("metrics"):
        return None
    rows = [[m["label"], num(m.get("recent"), 1), num(m.get("baseline"), 1),
             (f"{m['change_pct']:+.0f} %" if "change_pct" in m else ""), {"text": m["verdict"], "cls": "v-" + slug(m["verdict"])}]
            for m in t["metrics"].values()]
    f = t.get("filter") or {}
    flt = " · ".join(f"{k} {v}" for k, v in f.items() if v)
    return {"title": "Trend", "sub": f"recent {t.get('recent_games')} game(s) vs baseline {t.get('baseline_games')}"
            + (f" · {flt}" if flt else "") + " · per 10 min of match clock, time dead as % of the match",
            "header": ["", "recent", "baseline", "change", "verdict"], "rows": rows}


def _session(sdir: Path) -> dict | None:
    sj = _json(sdir / "session.json")
    summary = _read(sdir / "coaching.md")
    if sj is None and summary is None:
        return None
    m = DATE_RE.match(sdir.name)
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else sdir.name
    label = m.group(4) if m else sdir.name
    if sj is not None and SESSION_RE.match(sdir.name):
        label = label.replace(".", ":", 1)[:5]           # HH:MM
    elif sj is None:
        label = re.sub(r"(\d{2})\.(\d{2})", r"\1:\2", label).replace(" to ", "–")   # '19.40 to 21.10' -> '19:40–21:10'
    kind = "session" if sj is not None else "combined"
    s: dict = {"id": slug(sdir.name), "name": sdir.name, "date": date, "label": label, "kind": kind, "summary_md": summary,
               "title": f"{'Summary' if kind == 'combined' else 'Session'} {date} {label}", "games": [], "tables": []}
    s["sub"] = f'<a href="{_rel(sdir)}" target="_blank">folder</a>' + (f" · recording {(sj or {}).get('video')}" if sj and sj.get("video") else "")
    if sj is not None:
        dirs = {Path(x["dir"]).name for x in sj.get("matches") or [] if x.get("dir")}
        for gdir in sorted(sdir.glob("m[0-9]*")):
            if gdir.is_dir() and (gdir.name in dirs or (gdir / "match.json").exists()):
                s["games"].append(_game(gdir, s))
        if not summary and s["games"]:
            s["warn"] = "No session summary."
        clips = {gd["dir"][:3]: {"id": gd["id"], **gd["clips"]} for gd in s["games"] if gd.get("clips") and gd.get("video")}
        s["summary_md"] = link_moments(summary, clips)
    if (t := _trend_table(_json(sdir / "trend.json"))):
        s["tables"].append(t)
    return s


def day_actions(day: dict) -> list[dict]:
    """One button per day: compress every match of the day that is still a big lossless copy."""
    from .compress import estimate_min
    lib = library()
    dirs = [lib / s["name"] / g["dir"] for s in day["sessions"] for g in s["games"]]
    big = [d for d in dirs if compress_state(d) == "big"]
    if not big:
        return []
    gb = sum((d / "match.mp4").stat().st_size for d in big) / 1e9
    mins = max(1, round(sum(estimate_min(d) for d in big)))
    return [{"text": f"{len(big)} match clip{'s' if len(big) != 1 else ''} from this day {'are' if len(big) != 1 else 'is'} lossless, {gb:.1f} GB. "
                     f"Compressing keeps about a third and looks the same; the GPU is busy for about {mins} min.",
             "label": "Compress this day", "action": "compress", "args": {"dirs": [_rel_dir(d) for d in big]},
             "cmd": f"owcoach compress {day['date']}"}]


def _rel_dir(d: Path) -> str:
    return d.relative_to(library()).as_posix()


def focus_page() -> dict:
    """The Focus page (ADR 0014): every focus item with an on/off toggle, the coach's new ideas
    marked, a box for the player's own, and a nudge at the cap."""
    from .focus import MAX_ACTIVE, items
    try:
        its = items()
    except (OSError, ValueError):
        its = []
    n_on = sum(i["active"] for i in its)
    n_new = sum(i["new"] for i in its)
    acts = []
    for i in its:
        w = html.escape(i["wording"])
        badge = '<span class="flag">new from coaching</span> ' if i["new"] else ""
        ev = "".join(f"<br><small class=dim>{html.escape(x.lstrip('-* '))}</small>" for x in i.get("evidence") or [])
        acts.append({"text": f"{badge}<b>{w}</b>" + (f" <small class=dim>{html.escape(i['note'])}</small>" if i["note"] and not ev else "") + ev,
                     "label": "Active" if i["active"] else "Off", "on": i["active"], "action": "focus",
                     "args": {"wording": i["wording"], "on": not i["active"]},
                     "title": "Click to turn it off" if i["active"] else "Click to make it active",
                     "cmd": f'owcoach focus --{"off" if i["active"] else "on"} "{i["wording"]}"'})
    acts.append({"input": "add", "placeholder": "your own: when <trigger>, <action>", "label": "Add, active",
                 "action": "focus", "cmd": 'owcoach focus --add "{}"'})
    if n_on >= MAX_ACTIVE:
        intro = (f'<span class="nag">{n_on} focus items are active, the most there can be. One or two work better: '
                 "the coach grades each one every match, and it's hard to think about three things in a fight.</span>")
    elif n_on:
        intro = f"{n_on} active. The coach grades each active item every match. Up to {MAX_ACTIVE} can be on; one or two work best."
    else:
        intro = "No active focus. Turn one on, or add your own."
    return {"id": "focus", "title": "Focus", "nav": f"Focus ({n_new} new)" if n_new else "Focus", "intro": intro, "actions": acts}


def collect() -> dict:
    """The whole library as the renderer's tree."""
    lib, prof = library(), profile_dir()
    profile = _json(prof / "profile.json") or {}
    player = profile.get("name") or ""
    sessions = [s for s in (_session(d) for d in sorted(lib.iterdir()) if d.is_dir() and not d.name.startswith(".")) if s]
    days: dict[str, dict] = {}
    for s in sessions:
        days.setdefault(s["date"], {"date": s["date"], "sessions": [], "combined": []})
        days[s["date"]]["combined" if s["kind"] == "combined" else "sessions"].append(s)
    allg = [g for s in sessions for g in s["games"]]
    tables = []
    try:
        from .history import trend
        by_hero = trend("session").get("by_hero") or {}
        if by_hero:
            tables.append({"title": "Per hero, all games", "header": ["hero", "games", "D/10", "dead %", "heal/10", "dmg/10"],
                           "rows": [[h, str(v["games"]), num(v.get("D"), 1), num(v.get("dead_pct"), 1), num(v.get("H")), num(v.get("DMG"))]
                                    for h, v in by_hero.items()]})
    except Exception:            # history is optional for the page
        pass
    focus = focus_page()
    pages = [focus, {"id": "lessons", "title": "Lessons", "md": _read(prof / "lessons.md")}]
    new_focus = focus["nav"] != "Focus"
    other = None
    try:
        from coachlib.config import data_dir
        hots_page = data_dir("hots") / PAGE_NAME
        if hots_page.exists():
            other = {"title": "Heroes of the Storm", "href": hots_page.as_uri()}
    except Exception:
        pass
    return {
        "app": "owcoach", "player": player, "title": f"{player} · Overwatch 2", "nav_home": f"{player} · all games",
        "home_title": f"{player} · Overwatch 2 coaching",
        "home_sub": f"{len(allg)} games in {len([s for s in sessions if s['kind'] == 'session'])} sessions, {sum(1 for g in allg if g['coached'])} coached · "
                    f"library <code>{lib}</code> · profile <code>{prof}</code> · built {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "banner": "The coach has a new focus idea: see [Focus](#focus)." if new_focus else None,
        "columns": COLUMNS, "days": [dict(days[k], actions=day_actions(days[k])) for k in sorted(days, reverse=True)], "pages": pages, "tables": tables,
        "notes": ["Reports and notes are the coach's text, unedited. Stills and clips are read from the library next to this file; nothing is copied.",
                  "Clips are the recording's own HEVC HDR stream. Edge and Chrome play them with the HEVC extension; colours look flat on an SDR "
                  "screen. The VLC link plays the moments properly."],
        "other": other, "generated": datetime.now().isoformat(timespec="minutes"), "version": version(),
    }


def build(out: Path | None = None) -> Path:
    page = write(collect(), out or library() / PAGE_NAME)
    if out is None:
        write_link()
    return page
