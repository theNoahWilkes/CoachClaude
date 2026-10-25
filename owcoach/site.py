"""`owcoach site`: the library as one HTML page, <library>/coaching.html.

This module is the Overwatch collector: it knows the library layout (session.json, packet.json,
coaching.md, frames/, moments.m3u, the profile's lessons and focus proposal, history.sqlite) and
builds the plain tree that `coachlib.site.render` turns into the page. Days -> sessions (and
combined summaries) -> games; a game page has the stats table, the scoreboard, a timeline, the
clip seekable from each moment, the report, and every death / ult / final blow with its stills,
facts line and reader notes; Lessons and the Focus proposal are pages. Nothing is copied: every
image and clip is a relative link from the library root.

Rebuilt at the end of `owcoach run` and `owcoach coach`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from coachlib.launcher import write_link
from coachlib.site import num, slug, write
from coachlib.version import version

from .config import library, profile_dir

PAGE_NAME = "coaching.html"
SESSION_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) - (\d{2})\.(\d{2})\.(\d{2})\.(\d+)$")
DATE_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) - (.+)$")
COLUMNS = [{"key": "played", "label": "played", "align": "left"}, {"key": "map", "label": "map", "align": "left"},
           {"key": "mode", "label": "mode", "align": "left"}, {"key": "result", "label": "result", "align": "left"},
           {"key": "hero", "label": "hero", "align": "left"}, {"key": "clock", "label": "clock"},
           {"key": "deaths", "label": "deaths"}, {"key": "d10", "label": "D/10"}, {"key": "dead_pct", "label": "dead %"},
           {"key": "h10", "label": "heal/10"}, {"key": "dmg10", "label": "dmg/10"}, {"key": "coached", "label": "coached"}]


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
        rows.append([lab, num(tot), num(per, dg), num(t2, dg), num(e2, dg)])
    rows.append(["Time dead", f"{num(m.get('time_dead_s'))} s", f"{num(m.get('dead_pct'), 1)} %", "", ""])
    extra = f"final blows {num(m.get('final_blows'))}"
    if m.get("death_flags"):
        extra += " · flags " + ", ".join(f"{k} {v}" for k, v in m["death_flags"].items())
    if m.get("killed_by"):
        extra += " · killed by " + ", ".join(f"{k} ×{v}" for k, v in m["killed_by"].items())
    rows.append(["Ults", f"{num(m.get('ults_used'))} of {num(m.get('ults'))}", extra, "", ""])
    return {"header": ["", "game", "per 10", "other same role", "enemy same role"], "rows": rows}


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
    if not pk:
        g["title"] = " · ".join(str(x) for x in (mj.get("map") or gdir.name, (mj.get("result") or "").capitalize()) if x)
        g["sub"] = " · ".join(x for x in (mj.get("mode"), folder) if x)
        g["warnings"].append("No packet for this game (not processed, or no match found in the clip).")
        g["cells"] = {"played": session["date"], "map": {"text": mj.get("map") or gdir.name, "href": f"#g/{g['id']}"},
                      "mode": mj.get("mode") or "", "result": {"text": mj.get("result") or "", "cls": f"res-{mj.get('result')}"},
                      "hero": mj.get("hero_final") or "", "coached": "no packet"}
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
         "death_flags": counts.get("death_flags") or {}, "killed_by": counts.get("killed_by") or {},
         "player": stats.get("player") or {}, "per10": per10,
         "teammate_same_role_per10": stats.get("teammate_same_role_per10"), "enemy_same_role_per10": stats.get("enemy_same_role_per10")}
    result = game.get("result") or "none"
    g["result"] = result
    g["title"] = " · ".join(x for x in (game.get("map") or gdir.name, result.capitalize() if result != "none" else "", hero) if x)
    g["sub"] = " · ".join(x for x in (game.get("mode"), game.get("queue"), played.strftime("%Y-%m-%d %H:%M") if played else None,
                                      f"clock {stats.get('clock') or game.get('clock_at_end')}" if stats.get("clock") or game.get("clock_at_end") else None,
                                      f"{_mmss(game['duration_s'])} of video" if game.get("duration_s") else None, folder) if x)
    g["cells"] = {"played": played.strftime("%Y-%m-%d %H:%M") if played else session["date"],
                  "map": {"text": game.get("map") or gdir.name, "href": f"#g/{g['id']}"}, "mode": game.get("mode") or "",
                  "result": {"text": result if result != "none" else "", "cls": f"res-{result}"}, "hero": hero,
                  "clock": stats.get("clock") or "", "deaths": num(counts.get("deaths")), "d10": num(counts.get("deaths_per_10min"), 1),
                  "dead_pct": num(dead_pct, 1), "h10": num(per10.get("H")), "dmg10": num(per10.get("DMG")), "coached": "✓" if coached else ""}
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
    g["report_md"] = _read(pk_dir / "coaching.md")
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
    for n in ("summary", "ults") + tuple(f"overview_{i:02d}" for i in range(1, 10)):
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
    kind = "session" if sj is not None else "combined"
    s: dict = {"id": slug(sdir.name), "name": sdir.name, "date": date, "label": label, "kind": kind, "summary_md": summary,
               "title": f"{'Summary' if kind == 'combined' else 'Session'} {date} {label}", "games": [], "tables": []}
    s["sub"] = f'<a href="{_rel(sdir)}" target="_blank">folder</a>' + (f" · recording {(sj or {}).get('video')}" if sj and sj.get("video") else "")
    if sj is not None:
        dirs = {Path(x["dir"]).name for x in sj.get("matches") or [] if x.get("dir")}
        for gdir in sorted(sdir.glob("m[0-9]*")):
            if gdir.is_dir() and (gdir.name in dirs or (gdir / "match.json").exists()):
                s["games"].append(_game(gdir, s))
        n = len(s["games"])
        s["nav"] = f"{label} · {n} game{'s' if n != 1 else ''}" + (" · summary" if summary else "")
        if not summary and n:
            s["warn"] = "No session summary" + (" (a one-game session; the evening's combined summary covers it if there is one)." if n == 1 else ".")
    else:
        s["nav"] = f"Summary: {label}"
    if (t := _trend_table(_json(sdir / "trend.json"))):
        s["tables"].append(t)
    return s


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
    focus = _read(prof / "focus_proposal.md")
    pages = [{"id": "lessons", "title": "Lessons", "md": _read(prof / "lessons.md")}]
    if focus:
        pages.append({"id": "focus", "title": "Focus proposal", "nav": "Focus proposal (waiting)",
                      "intro": "Pick with <code>owcoach focus N</code> (two numbers for two habits), or <code>owcoach focus --set \"...\"</code> for your own wording.",
                      "md": focus})
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
        "banner": "A focus proposal is waiting: see [Focus proposal](#focus), then `owcoach focus N`." if focus else None,
        "columns": COLUMNS, "days": [days[k] for k in sorted(days, reverse=True)], "pages": pages, "tables": tables,
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
