"""`owcoach site`: one HTML file over the whole library, <library>/coaching.html.

Open it in a browser (file://) and navigate: days -> sessions -> games in the sidebar; a game page
has the facts line, the scoreboard, a timeline of deaths/ults/final blows, the clip (seekable to
each moment), the coaching report, and every moment with its stills, facts and reader notes;
a session page has the session summary and the trend table; Lessons, Focus proposal and an
all-games table are pages of their own. Everything is linked by relative paths from the library
root, so the file works wherever the library is, and nothing is copied.

Two halves, on purpose: `collect()` knows the owcoach layout (packet.json, coaching.md, frames)
and builds a plain tree; `render(tree)` knows nothing about Overwatch and turns the tree into HTML.
The HotS coach gets its own collector in the CoachClaude merge and shares `render`.

Rebuilt automatically at the end of `owcoach run` and `owcoach coach`. Needs markdown-it-py.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .config import library, profile_dir

PAGE_NAME = "coaching.html"
SESSION_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) - (\d{2})\.(\d{2})\.(\d{2})\.(\d+)$")
DATE_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) - (.+)$")


# ----------------------------------------------------------------------------- collect (owcoach)

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


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()


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
    from datetime import timedelta
    return datetime(y, mo, d, h, mi, s) + timedelta(seconds=start_s)


def _moment_stills(frames: list[dict]) -> list[dict]:
    """The stills worth a strip: the sampled ones, not the 0.1 s extras (those stay one click away
    in the folder)."""
    return [{"file": f["file"], "dt": f["dt"], "kind": f["kind"], "clock": f.get("clock")}
            for f in frames if not f.get("extra")]


def _game(gdir: Path, session: dict) -> dict:
    pk_dir = gdir / "packet"
    pk = _json(pk_dir / "packet.json")
    mj = _json(gdir / "match.json") or {}
    g: dict = {"id": f"{session['id']}--{_slug(gdir.name)}", "dir": gdir.name, "path": _rel(gdir),
               "session": session["id"], "title": gdir.name, "coached": (pk_dir / "coaching.md").exists(),
               "processed": pk is not None, "meta": {}, "moments": [], "images": {}, "notes": []}
    if (gdir / "match.mp4").exists():
        g["video"] = _rel(gdir / "match.mp4")
    if (pk_dir / "moments.m3u").exists():
        g["m3u"] = _rel(pk_dir / "moments.m3u")
    for name in ("scoreboard_final.jpg", "summary.jpg", "rank.jpg", "sheet.jpg"):
        if (gdir / name).exists():
            g["images"][name[:-4]] = _rel(gdir / name)
    if not pk:
        g["meta"] = {"map": mj.get("map"), "mode": mj.get("mode"), "result": mj.get("result"),
                     "hero": mj.get("hero_final"), "duration_s": mj.get("duration")}
        g["title"] = " · ".join(str(x) for x in (mj.get("map") or gdir.name, mj.get("result")) if x)
        return g
    game, counts, stats = pk["game"], pk.get("counts") or {}, pk.get("stats") or {}
    heroes = pk.get("heroes") or []
    hero_names = []
    for h in heroes:
        if h["hero"] not in hero_names:
            hero_names.append(h["hero"])
    played = _played(session["name"], game.get("session_start_s") or 0.0)
    per10 = stats.get("player_per10") or {}
    g["meta"] = {
        "map": game.get("map"), "mode": game.get("mode"), "queue": game.get("queue"), "result": game.get("result"),
        "role": game.get("role"), "hero": " → ".join(hero_names), "heroes": heroes,
        "duration_s": game.get("duration_s"), "clock": stats.get("clock") or game.get("clock_at_end"),
        "clock_s": stats.get("clock_s"), "played": played.isoformat(timespec="minutes") if played else None,
        "deaths": counts.get("deaths"), "deaths_per10": counts.get("deaths_per_10min"),
        "time_dead_s": counts.get("time_dead_s"),
        "dead_pct": (round(100 * counts["time_dead_s"] / stats["clock_s"], 1)
                     if counts.get("time_dead_s") is not None and stats.get("clock_s") else None),
        "ults": counts.get("ults"), "ults_used": counts.get("ults_used"), "final_blows": counts.get("final_blows"),
        "death_flags": counts.get("death_flags") or {}, "killed_by": counts.get("killed_by") or {},
        "player": stats.get("player") or {}, "per10": per10,
        "teammate_same_role_per10": stats.get("teammate_same_role_per10"),
        "enemy_same_role_per10": stats.get("enemy_same_role_per10"),
        "scoreboard": stats.get("scoreboard"), "player_row": stats.get("player_row"),
    }
    g["title"] = " · ".join(x for x in (game.get("map") or gdir.name, (game.get("result") or "").capitalize(),
                                         " → ".join(hero_names)) if x)
    g["report_md"] = _read(pk_dir / "coaching.md")
    g["hero_notes"] = {h: str(profile_dir() / p) for h, p in (pk.get("hero_notes") or {}).items()}
    # timeline for the SVG
    g["timeline"] = {
        "duration": game.get("duration_s") or 0,
        "fights": [{"from": f["from_t"], "to": f["to_t"]} for f in (pk.get("hud_game") or {}).get("fights") or []],
        "deaths": [{"id": d["id"], "t": d["t"], "clock": d["clock"], "to": (d.get("respawned") or {}).get("t")}
                   for d in pk.get("deaths") or []],
        "ults": [{"id": u["id"], "ready": (u.get("ready") or {}).get("t"), "used": (u.get("used") or {}).get("t"),
                  "outcome": u.get("outcome")} for u in pk.get("ults") or []],
        "final_blows": [{"id": k["id"], "t": k["t"], "clock": k["clock"]} for k in pk.get("final_blows") or []],
        "alive": pk.get("alive_series") or [],
        "low": [{"from": e["from"], "to": e["to"], "min_hp": e.get("min_hp"), "outcome": e.get("outcome")}
                for e in (pk.get("hud_game") or {}).get("low_episodes") or []],
    }
    # moments: deaths, ults, final blows, in time order
    for d in pk.get("deaths") or []:
        ab = d.get("alive_before") or {}
        bits = [f"killed by {d.get('killed_by') or '?'}", f"{ab.get('ally', '?')}v{ab.get('enemy', '?')}",
                (d.get("objective") or {}).get("side") or ""]
        flags = [k for k in ("first_down", "team_behind", "died_with_ult", "repeat_killer", "even_fight", "overtime")
                 if k in (d.get("flags") or []) or d.get(k)]
        if d.get("ult_ready"):
            flags.append("ult ready")
        g["moments"].append({
            "id": d["id"], "kind": "death", "t": d["t"], "clock": d["clock"], "video_t": d.get("video_t", d["t"]),
            "title": f"{d['id']} {d['clock']} · {d.get('hero') or ''} " + " · ".join(b for b in bits if b),
            "flags": flags, "stills": _moment_stills(d.get("frames") or []),
            "facts_md": _read(pk_dir / "facts" / f"{d['id']}.md"),
            "notes_md": _read(pk_dir / "notes" / f"{d['id']}.md"),
            "respawn": (d.get("respawned") or {}).get("clock"),
        })
    for u in pk.get("ults") or []:
        r, s = u.get("ready") or {}, u.get("used") or {}
        held = f"held {u['held_s']:.0f} s" if u.get("held_s") is not None else ""
        t = s.get("t") if s else r.get("t")
        g["moments"].append({
            "id": u["id"], "kind": "ult", "t": t, "clock": s.get("clock") or r.get("clock"),
            "video_t": s.get("video_t") if s else r.get("video_t"),
            "title": f"{u['id']} {s.get('clock') or r.get('clock')} · {u.get('hero') or ''} ult {u.get('outcome')}"
                     + (f", ready {r.get('clock')}, {held}" if r and held else ""),
            "flags": u.get("flags") or [], "stills": _moment_stills(u.get("frames") or []),
            "facts_md": None, "notes_md": None,
        })
    for k in pk.get("final_blows") or []:
        ab = k.get("alive_before") or {}
        g["moments"].append({
            "id": k["id"], "kind": "final_blow", "t": k["t"], "clock": k["clock"], "video_t": k.get("video_t", k["t"]),
            "title": f"{k['id']} {k['clock']} · final blow on {k.get('victim') or '?'} · {ab.get('ally', '?')}v{ab.get('enemy', '?')}",
            "flags": [], "stills": [], "facts_md": None, "notes_md": None,
        })
    g["moments"].sort(key=lambda m: (m["t"] is None, m["t"] or 0))
    g["moments_video"] = pk.get("game", {}).get("video", "../match.mp4")
    g["overview"] = [{"file": o["file"], "from": o["from"], "to": o["to"]} for o in pk.get("overview") or []]
    g["packet_path"] = _rel(pk_dir)
    for n in ("summary", "ults") + tuple(f"overview_{i:02d}" for i in range(1, 10)):
        p = pk_dir / "notes" / f"{n}.md"
        if p.exists():
            g["notes"].append({"name": n, "md": _read(p)})
    g["pipeline_notes"] = pk.get("notes") or []
    return g


def _session(sdir: Path) -> dict | None:
    sj = _json(sdir / "session.json")
    summary = _read(sdir / "coaching.md")
    if sj is None and summary is None:
        return None
    m = DATE_RE.match(sdir.name)
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else sdir.name
    s: dict = {"id": _slug(sdir.name), "name": sdir.name, "path": _rel(sdir), "date": date,
               "label": m.group(4).replace(".", ":", 1) if m and SESSION_RE.match(sdir.name) else (m.group(4) if m else sdir.name),
               "kind": "session" if sj is not None else "combined", "summary_md": summary,
               "trend": _json(sdir / "trend.json"), "games": [], "recording": (sj or {}).get("video")}
    if sj is not None:
        s["label"] = s["label"][:5]          # HH:MM
        dirs = {Path(x["dir"]).name for x in sj.get("matches") or [] if x.get("dir")}
        for gdir in sorted(sdir.glob("m[0-9]*")):
            if gdir.is_dir() and (gdir.name in dirs or (gdir / "match.json").exists()):
                s["games"].append(_game(gdir, s))
    return s


def _history_rows() -> list[dict]:
    db = profile_dir() / "history.sqlite"
    if not db.exists():
        return []
    try:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute("SELECT * FROM games ORDER BY played").fetchall()]
        con.close()
        return rows
    except sqlite3.Error:
        return []


def collect() -> dict:
    """The whole library as a plain tree (no HTML in it)."""
    lib = library()
    prof = profile_dir()
    profile = _json(prof / "profile.json") or {}
    sessions = [s for s in (_session(d) for d in sorted(lib.iterdir()) if d.is_dir() and not d.name.startswith("."))
                if s]
    days: dict[str, dict] = {}
    for s in sessions:
        days.setdefault(s["date"], {"date": s["date"], "sessions": [], "combined": []})
        days[s["date"]]["combined" if s["kind"] == "combined" else "sessions"].append(s)
    by_hero = {}
    try:
        from .history import trend
        t = trend("session")
        by_hero = t.get("by_hero") or {}
    except Exception:   # history is optional for the page
        pass
    return {
        "app": "owcoach", "player": profile.get("name") or "", "library": str(lib), "profile": str(prof),
        "generated": datetime.now().isoformat(timespec="minutes"),
        "days": [days[k] for k in sorted(days, reverse=True)],
        "lessons_md": _read(prof / "lessons.md"),
        "focus_md": _read(prof / "focus_proposal.md"),
        "history": _history_rows(), "by_hero": by_hero,
        "notes": ["Reports and notes are the coach's text, unedited. Stills and clips are read from the library "
                  "next to this file; nothing is copied.",
                  "Clips are the recording's own HEVC HDR stream. Edge and Chrome play them with the HEVC "
                  "extension; colours look flat on an SDR screen. The VLC link plays the moments properly."],
    }


# ----------------------------------------------------------------------------- render (generic)

def _md(text: str | None) -> str:
    if not text:
        return ""
    from markdown_it import MarkdownIt
    return MarkdownIt("commonmark").enable("table").enable("strikethrough").render(text)


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _n(v, digits=0, default="") -> str:
    if v is None:
        return default
    return f"{v:,.{digits}f}"


def _timeline_svg(tl: dict) -> str:
    dur = tl.get("duration") or 0
    if not dur:
        return ""
    W, H = 1000, 56
    x = lambda t: round(W * max(0.0, min(1.0, (t or 0) / dur)), 1)
    out = [f'<svg class="tl" viewBox="0 0 {W} {H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">']
    out.append(f'<rect x="0" y="22" width="{W}" height="12" class="tl-bar"/>')
    for f in tl.get("fights") or []:
        out.append(f'<rect x="{x(f["from"])}" y="22" width="{max(2, x(f["to"]) - x(f["from"]))}" height="12" class="tl-fight">'
                   f'<title>fight {_mmss(f["from"])}–{_mmss(f["to"])}</title></rect>')
    for e in tl.get("low") or []:
        cls = "tl-low-died" if e.get("outcome") == "died" else "tl-low"
        out.append(f'<rect x="{x(e["from"])}" y="36" width="{max(2, x(e["to"]) - x(e["from"]))}" height="5" class="{cls}">'
                   f'<title>under half HP {_mmss(e["from"])}–{_mmss(e["to"])}, min {e.get("min_hp")}, {e.get("outcome")}</title></rect>')
    for u in tl.get("ults") or []:
        r, s = u.get("ready"), u.get("used")
        if r is not None:
            x1, x2 = x(r), x(s if s is not None else dur)
            out.append(f'<rect x="{x1}" y="14" width="{max(2, x2 - x1)}" height="6" class="tl-ult">'
                       f'<title>{u["id"]} ready {_mmss(r)}' + (f', used {_mmss(s)}' if s is not None else ', not used') + '</title></rect>')
        if s is not None:
            out.append(f'<polygon points="{x(s)},8 {x(s) - 5},16 {x(s) + 5},16" class="tl-ult-use" data-moment="{u["id"]}">'
                       f'<title>{u["id"]} used {_mmss(s)}</title></polygon>')
    for k in tl.get("final_blows") or []:
        out.append(f'<polygon points="{x(k["t"])},48 {x(k["t"]) - 5},42 {x(k["t"]) + 5},42" class="tl-fb" data-moment="{k["id"]}">'
                   f'<title>{k["id"]} final blow {k["clock"]}</title></polygon>')
    for d in tl.get("deaths") or []:
        if d.get("to"):
            out.append(f'<rect x="{x(d["t"])}" y="22" width="{max(2, x(d["to"]) - x(d["t"]))}" height="12" class="tl-dead"/>')
        out.append(f'<circle cx="{x(d["t"])}" cy="28" r="6" class="tl-death" data-moment="{d["id"]}">'
                   f'<title>{d["id"]} death {d["clock"]}</title></circle>')
    out.append("</svg>")
    ticks = "".join(f'<span style="left:{x(t) / 10}%">{_mmss(t)}</span>' for t in range(0, int(dur) + 1, 120))
    return "".join(out) + f'<div class="tl-ticks">{ticks}</div>'


def _game_html(g: dict, s: dict, prev: dict | None, nxt: dict | None) -> str:
    m = g["meta"]
    nav = '<div class="pn">' + (f'<a href="#g/{_e(prev["id"])}">← {_e(prev["title"])}</a>' if prev else "<span></span>") + \
          f'<a href="#s/{_e(s["id"])}">session {_e(s["label"])}</a>' + \
          (f'<a href="#g/{_e(nxt["id"])}">{_e(nxt["title"])} →</a>' if nxt else "<span></span>") + "</div>"
    head = f'<h1>{_e(g["title"])}</h1>'
    sub = " · ".join(_e(x) for x in (m.get("mode"), m.get("queue"), m.get("played", "").replace("T", " "),
                                      f"clock {m['clock']}" if m.get("clock") else None,
                                      f"{_mmss(m['duration_s'])} of video" if m.get("duration_s") else None) if x)
    out = [nav, head, f'<p class="sub">{sub} · <a href="{_e(g["path"])}" target="_blank">folder</a></p>']
    if not g["processed"]:
        out.append('<p class="warn">No packet for this game (not processed, or no match found in the clip).</p>')
    else:
        pl, p10 = m.get("player") or {}, m.get("per10") or {}
        tm, en = m.get("teammate_same_role_per10") or {}, m.get("enemy_same_role_per10") or []
        en_avg = {}
        for k in ("E", "A", "D", "DMG", "H", "MIT"):
            vals = [e[k] for e in en if isinstance(e, dict) and e.get(k) is not None]
            en_avg[k] = sum(vals) / len(vals) if vals else None
        rows = [("Deaths", m.get("deaths"), p10.get("D"), tm.get("D"), en_avg.get("D"), 1),
                ("Eliminations", pl.get("E"), p10.get("E"), tm.get("E"), en_avg.get("E"), 1),
                ("Assists", pl.get("A"), p10.get("A"), tm.get("A"), en_avg.get("A"), 1),
                ("Damage", pl.get("DMG"), p10.get("DMG"), tm.get("DMG"), en_avg.get("DMG"), 0),
                ("Healing", pl.get("H"), p10.get("H"), tm.get("H"), en_avg.get("H"), 0),
                ("Mitigation", pl.get("MIT"), p10.get("MIT"), tm.get("MIT"), en_avg.get("MIT"), 0)]
        tbl = ['<table class="stats"><tr><th></th><th>game</th><th>per 10</th><th>other same role</th><th>enemy same role</th></tr>']
        for lab, tot, per, t2, e2, dg in rows:
            tbl.append(f"<tr><th>{lab}</th><td>{_n(tot)}</td><td>{_n(per, dg)}</td><td>{_n(t2, dg)}</td><td>{_n(e2, dg)}</td></tr>")
        tbl.append(f'<tr><th>Time dead</th><td>{_n(m.get("time_dead_s"))} s</td><td>{_n(m.get("dead_pct"), 1)} %</td><td></td><td></td></tr>')
        tbl.append(f'<tr><th>Ults</th><td>{_n(m.get("ults_used"))} of {_n(m.get("ults"))}</td><td colspan="3">final blows {_n(m.get("final_blows"))}'
                   + (" · flags " + ", ".join(f"{k} {v}" for k, v in m["death_flags"].items()) if m.get("death_flags") else "")
                   + (" · killed by " + ", ".join(f"{k} ×{v}" for k, v in m["killed_by"].items()) if m.get("killed_by") else "")
                   + "</td></tr></table>")
        imgs = "".join(f'<a href="{_e(p)}" target="_blank"><img src="{_e(p)}" loading="lazy" alt="{_e(k)}"></a>'
                       for k, p in g["images"].items() if k in ("scoreboard_final", "summary", "rank"))
        out.append(f'<div class="two"><div>{"".join(tbl)}</div><div class="imgs">{imgs}</div></div>')
        out.append(_timeline_svg(g.get("timeline") or {}))
    if g.get("video"):
        out.append(f'<div class="clip"><video id="v-{_e(g["id"])}" controls preload="none" src="{_e(g["video"])}"></video>'
                   f'<div class="clipbar"><span>Clip: seeks from each moment below.</span>'
                   + (f'<a href="{_e(g["m3u"])}">moments.m3u (VLC)</a>' if g.get("m3u") else "")
                   + f'<a href="{_e(g["video"])}" target="_blank">match.mp4</a></div></div>')
    if g.get("report_md"):
        out.append(f'<h2 id="r-{_e(g["id"])}">Coaching report</h2><div class="md">{_md(g["report_md"])}</div>')
    elif g["processed"]:
        out.append('<p class="warn">Not coached yet. <code>owcoach coach</code> writes the report.</p>')
    if g.get("moments"):
        out.append("<h2>Moments</h2>")
        for mo in g["moments"]:
            vt = mo.get("video_t")
            btn = (f'<button class="seek" data-video="v-{_e(g["id"])}" data-t="{max(0.0, (vt or 0) - 10):.1f}">▶ −10 s</button>'
                   f'<button class="seek" data-video="v-{_e(g["id"])}" data-t="{(vt or 0):.1f}">▶ at {_e(mo["clock"])}</button>') if g.get("video") and vt is not None else ""
            flags = "".join(f'<span class="flag">{_e(f)}</span>' for f in mo.get("flags") or [])
            out.append(f'<div class="moment {mo["kind"]}" id="m-{_e(g["id"])}-{_e(mo["id"])}"><h3>{_e(mo["title"])}'
                       + (f' <small>respawn {_e(mo["respawn"])}</small>' if mo.get("respawn") else "")
                       + f'</h3><div class="mbar">{btn}{flags}</div>')
            if mo["stills"]:
                strip = "".join(
                    f'<a href="{_e(g["packet_path"])}/{_e(quote(st["file"]))}" target="_blank" title="{_e(st["kind"])} {st["dt"]:+.1f} s">'
                    f'<img src="{_e(g["packet_path"])}/{_e(quote(st["file"]))}" loading="lazy" alt="{_e(st["kind"])} {st["dt"]:+.1f}">'
                    f'<span>{st["dt"]:+.1f}</span></a>' for st in mo["stills"])
                out.append(f'<div class="strip">{strip}</div>')
            if mo.get("facts_md"):
                out.append(f'<details><summary>Facts (the packet\'s measured line)</summary><pre class="facts">{_e(mo["facts_md"])}</pre></details>')
            if mo.get("notes_md"):
                out.append(f'<details><summary>Reader notes</summary><div class="md">{_md(mo["notes_md"])}</div></details>')
            out.append("</div>")
    if g.get("overview"):
        cells = "".join(f'<a href="{_e(g["packet_path"])}/{_e(quote(o["file"]))}" target="_blank">'
                        f'<img src="{_e(g["packet_path"])}/{_e(quote(o["file"]))}" loading="lazy" alt="{_e(o["from"])}"><span>{_e(o["from"])}</span></a>'
                        for o in g["overview"])
        out.append(f'<details class="ov"><summary>Overview stills ({len(g["overview"])} cells, 10 s apart)</summary><div class="strip wrap">{cells}</div></details>')
    if g.get("notes"):
        for n in g["notes"]:
            out.append(f'<details><summary>Reader notes: {_e(n["name"])}</summary><div class="md">{_md(n["md"])}</div></details>')
    if g.get("pipeline_notes"):
        out.append('<details><summary>What the packet measures (and doesn\'t)</summary><ul>'
                   + "".join(f"<li>{_e(x)}</li>" for x in g["pipeline_notes"]) + "</ul></details>")
    return "".join(out)


def _trend_html(t: dict | None) -> str:
    if not t or not t.get("metrics"):
        return ""
    rows = "".join(f'<tr><th>{_e(m["label"])}</th><td>{_n(m.get("recent"), 1)}</td><td>{_n(m.get("baseline"), 1)}</td>'
                   f'<td>{(f"{m["change_pct"]:+.0f} %" if "change_pct" in m else "")}</td><td class="v-{_slug(m["verdict"])}">{_e(m["verdict"])}</td></tr>'
                   for m in t["metrics"].values())
    f = t.get("filter") or {}
    flt = " · ".join(f"{k} {v}" for k, v in f.items() if v)
    return (f'<h2>Trend</h2><p class="sub">recent {t.get("recent_games")} game(s) vs baseline {t.get("baseline_games")}'
            + (f" · {flt}" if flt else "") + ' · per 10 min of match clock, time dead as % of the match</p>'
            f'<table class="stats"><tr><th></th><th>recent</th><th>baseline</th><th>change</th><th>verdict</th></tr>{rows}</table>')


def _games_table(games: list[tuple[dict, dict]]) -> str:
    rows = []
    for s, g in games:
        m = g["meta"]
        p10 = m.get("per10") or {}
        rows.append(f'<tr><td>{_e((m.get("played") or s["date"]).replace("T", " "))}</td>'
                    f'<td><a href="#g/{_e(g["id"])}">{_e(m.get("map") or g["dir"])}</a></td><td>{_e(m.get("mode"))}</td>'
                    f'<td class="res-{_e(m.get("result"))}">{_e(m.get("result"))}</td><td>{_e(m.get("hero"))}</td>'
                    f'<td>{_e(m.get("clock"))}</td><td>{_n(m.get("deaths"))}</td><td>{_n(m.get("deaths_per10"), 1)}</td>'
                    f'<td>{_n(m.get("dead_pct"), 1)}</td><td>{_n(p10.get("H"))}</td><td>{_n(p10.get("DMG"))}</td>'
                    f'<td>{"✓" if g["coached"] else ("" if g["processed"] else "no packet")}</td></tr>')
    return ('<table class="stats games"><tr><th>played</th><th>map</th><th>mode</th><th>result</th><th>hero</th><th>clock</th>'
            '<th>deaths</th><th>D/10</th><th>dead %</th><th>heal/10</th><th>dmg/10</th><th>coached</th></tr>' + "".join(rows) + "</table>")


def _session_html(s: dict, day: dict) -> str:
    out = [f'<h1>{"Summary" if s["kind"] == "combined" else "Session"} {_e(s["date"])} {_e(s["label"])}</h1>',
           f'<p class="sub"><a href="{_e(s["path"])}" target="_blank">folder</a>'
           + (f' · recording {_e(s["recording"])}' if s.get("recording") else "") + "</p>"]
    games = [(s, g) for g in s["games"]]
    if s["kind"] == "combined":
        games = [(x, g) for x in day["sessions"] for g in x["games"]]
    if games:
        out.append(_games_table(games))
    if s.get("summary_md"):
        out.append(f'<h2>Session summary</h2><div class="md">{_md(s["summary_md"])}</div>')
    elif s["kind"] == "session" and s["games"]:
        out.append('<p class="warn">No session summary' + (
            " (a one-game session; the evening's combined summary covers it if there is one)." if len(s["games"]) == 1 else ".") + "</p>")
    out.append(_trend_html(s.get("trend")))
    return "".join(out)


def _home_html(tree: dict) -> str:
    allg = [(s, g) for d in tree["days"] for s in d["sessions"] for g in s["games"]]
    coached = sum(1 for _, g in allg if g["coached"])
    out = [f'<h1>{_e(tree["player"])} · coaching</h1>',
           f'<p class="sub">{len(allg)} games in {sum(len(d["sessions"]) for d in tree["days"])} sessions, {coached} coached · '
           f'library <code>{_e(tree["library"])}</code> · profile <code>{_e(tree["profile"])}</code> · built {_e(tree["generated"].replace("T", " "))}</p>']
    if tree.get("focus_md"):
        out.append('<p class="warn">A focus proposal is waiting: see <a href="#focus">Focus proposal</a>, then <code>owcoach focus N</code>.</p>')
    out.append("<h2>All games</h2>" + _games_table(allg))
    if tree.get("by_hero"):
        rows = "".join(f'<tr><th>{_e(h)}</th><td>{v["games"]}</td><td>{_n(v.get("D"), 1)}</td><td>{_n(v.get("dead_pct"), 1)}</td>'
                       f'<td>{_n(v.get("H"))}</td><td>{_n(v.get("DMG"))}</td></tr>' for h, v in tree["by_hero"].items())
        out.append('<h2>Per hero, all games</h2><table class="stats"><tr><th>hero</th><th>games</th><th>D/10</th><th>dead %</th>'
                   f'<th>heal/10</th><th>dmg/10</th></tr>{rows}</table>')
    out.append("<h2>About this page</h2><ul>" + "".join(f"<li>{_e(n)}</li>" for n in tree.get("notes") or []) + "</ul>")
    return "".join(out)


CSS = """
:root{--bg:#141619;--panel:#1c1f24;--ink:#e6e6e6;--dim:#9aa3ad;--line:#2b3038;--acc:#f2a93b;--red:#e05252;--green:#5fbf6a;--blue:#5aa0e6}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;display:grid;grid-template-columns:300px 1fr;min-height:100vh}
nav{background:var(--panel);border-right:1px solid var(--line);padding:12px 0;position:sticky;top:0;height:100vh;overflow:auto;font-size:14px}
nav a{color:var(--ink);text-decoration:none;display:block;padding:3px 14px;border-left:3px solid transparent;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
nav a:hover{background:#242830}nav a.cur{border-left-color:var(--acc);background:#262a32}
nav .day{color:var(--dim);font-weight:600;padding:10px 14px 2px;text-transform:uppercase;font-size:12px;letter-spacing:.04em}
nav .sess{padding-left:22px;color:var(--dim)}nav .game{padding-left:34px}nav .top{font-weight:600}
nav .res-victory::before{content:"W ";color:var(--green)}nav .res-defeat::before{content:"L ";color:var(--red)}nav .res-draw::before{content:"D ";color:var(--dim)}
nav .nc{opacity:.55}
main{padding:20px 36px 80px;max-width:1300px;min-width:0}
.page{display:none}.page.cur{display:block}
h1{font-size:26px;margin:4px 0 2px}h2{font-size:19px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}h3{font-size:16px;margin:0 0 4px}
.sub{color:var(--dim);margin:0 0 14px}a{color:var(--blue)}code{background:#262a32;padding:1px 5px;border-radius:3px;font-size:13px}
.pn{display:flex;justify-content:space-between;gap:12px;color:var(--dim);font-size:13px;margin-bottom:8px}
.warn{background:#2c2415;border-left:3px solid var(--acc);padding:8px 12px}
table.stats{border-collapse:collapse;font-size:14px;margin:8px 0}table.stats th,table.stats td{border:1px solid var(--line);padding:3px 9px;text-align:right}
table.stats th{text-align:left;color:var(--dim);font-weight:500}table.stats tr:first-child th{text-align:right}table.stats tr:first-child th:first-child{text-align:left}
table.games td:nth-child(-n+5){text-align:left}table.games{width:100%}
.res-victory{color:var(--green)}.res-defeat{color:var(--red)}
.v-better{color:var(--green)}.v-worse{color:var(--red)}.v-normal-variation{color:var(--dim)}
.two{display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start}.imgs{flex:1 1 520px;min-width:0}.imgs img{width:100%;max-height:360px;object-fit:contain;object-position:left top;border:1px solid var(--line);display:block;margin-bottom:6px}
.tl{width:100%;height:56px;display:block;margin-top:12px}.tl-bar{fill:#262a32}.tl-fight{fill:#3a4150}.tl-dead{fill:#5a2626}
.tl-death{fill:var(--red);cursor:pointer}.tl-ult{fill:#7a5a1a}.tl-ult-use{fill:var(--acc);cursor:pointer}.tl-fb{fill:var(--green);cursor:pointer}
.tl-low{fill:#a07a2a}.tl-low-died{fill:var(--red)}
.tl-ticks{position:relative;height:16px;font-size:11px;color:var(--dim)}.tl-ticks span{position:absolute;transform:translateX(-50%)}
.clip{margin:14px 0}.clip video{width:100%;max-height:420px;background:#000;border:1px solid var(--line)}
.clipbar{display:flex;gap:16px;font-size:13px;color:var(--dim);margin-top:4px}
.md{max-width:900px}.md table{border-collapse:collapse;font-size:14px}.md th,.md td{border:1px solid var(--line);padding:3px 9px}.md th{color:var(--dim);font-weight:500}
.md h1{font-size:20px;margin-top:16px}.md h2{font-size:17px;border:0;margin-top:20px}.md h3{font-size:15px;margin-top:14px}.md blockquote{color:var(--dim);border-left:3px solid var(--line);margin:0;padding-left:12px}
.md pre{background:#101214;padding:8px;overflow:auto}.md code{font-size:13px}
.moment{border:1px solid var(--line);border-left:4px solid var(--red);border-radius:4px;padding:10px 12px;margin:10px 0;background:var(--panel)}
.moment.ult{border-left-color:var(--acc)}.moment.final_blow{border-left-color:var(--green)}
.moment h3 small{color:var(--dim);font-weight:400;font-size:13px;margin-left:8px}
.mbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0 8px}
button.seek{background:#2a3140;color:var(--ink);border:1px solid var(--line);border-radius:3px;padding:2px 9px;cursor:pointer;font-size:13px}button.seek:hover{background:#364055}
.flag{background:#33261a;color:var(--acc);border-radius:3px;padding:1px 7px;font-size:12px}
.strip{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px}.strip.wrap{flex-wrap:wrap}
.strip a{position:relative;flex:0 0 auto}.strip img{height:120px;display:block;border:1px solid var(--line)}
.strip span{position:absolute;left:3px;bottom:3px;background:rgba(0,0,0,.65);font-size:11px;padding:0 4px;border-radius:2px}
details{margin:6px 0}summary{cursor:pointer;color:var(--dim)}pre.facts{white-space:pre-wrap;font-size:12.5px;background:#101214;padding:8px;line-height:1.4}
@media(max-width:900px){body{grid-template-columns:1fr}nav{position:static;height:auto;max-height:40vh}main{padding:12px 16px}.two{grid-template-columns:1fr}}
"""

JS = """
(function(){
  var pages=document.querySelectorAll('.page'),links=document.querySelectorAll('nav a[data-page]');
  function show(){
    var h=location.hash.slice(1)||'home',id='p-'+h.replace(/\\//g,'--'),hit=false;
    pages.forEach(function(p){var on=p.id===id;p.classList.toggle('cur',on);hit=hit||on;});
    if(!hit){pages.forEach(function(p){p.classList.toggle('cur',p.id==='p-home');});h='home';}
    links.forEach(function(a){var on=a.getAttribute('data-page')===h;a.classList.toggle('cur',on);if(on)a.scrollIntoView({block:'nearest'});});
    window.scrollTo(0,0);
  }
  window.addEventListener('hashchange',show);show();
  function seek(vid,t){var v=document.getElementById(vid);if(!v)return;
    v.scrollIntoView({block:'center'});
    var go=function(){try{v.currentTime=t;}catch(e){}v.play&&v.play().catch(function(){});};
    if(v.readyState>0)go();else{v.addEventListener('loadedmetadata',go,{once:true});v.load();}}
  document.addEventListener('click',function(e){
    var b=e.target.closest('button.seek');if(b){seek(b.getAttribute('data-video'),parseFloat(b.getAttribute('data-t')));return;}
    var m=e.target.closest('[data-moment]');if(m){var pg=m.closest('.page');var el=pg&&pg.querySelector('[id$="-'+m.getAttribute('data-moment')+'"]');if(el)el.scrollIntoView({block:'start'});}
  });
})();
"""


def render(tree: dict) -> str:
    """The tree -> one self-contained HTML page (images and clips stay as relative links)."""
    nav = [f'<a href="#home" data-page="home" class="top">{_e(tree["player"])} · all games</a>',
           '<a href="#lessons" data-page="lessons" class="top">Lessons</a>']
    if tree.get("focus_md"):
        nav.append('<a href="#focus" data-page="focus" class="top">Focus proposal (waiting)</a>')
    pages = [f'<section class="page" id="p-home">{_home_html(tree)}</section>',
             f'<section class="page" id="p-lessons"><h1>Lessons</h1><div class="md">{_md(tree.get("lessons_md")) or "<p class=warn>No lessons file yet.</p>"}</div></section>']
    if tree.get("focus_md"):
        pages.append(f'<section class="page" id="p-focus"><h1>Focus proposal</h1><p class="sub">Pick with <code>owcoach focus N</code> '
                     f'(two numbers for two habits), or <code>owcoach focus --set "..."</code> for your own wording.</p><div class="md">{_md(tree["focus_md"])}</div></section>')
    for day in tree["days"]:
        nav.append(f'<div class="day">{_e(day["date"])}</div>')
        for s in day["combined"]:
            nav.append(f'<a href="#s/{_e(s["id"])}" data-page="s/{_e(s["id"])}" class="sess">Summary: {_e(s["label"])}</a>')
            pages.append(f'<section class="page" id="p-s--{_e(s["id"])}">{_session_html(s, day)}</section>')
        for s in day["sessions"]:
            n = len(s["games"])
            nav.append(f'<a href="#s/{_e(s["id"])}" data-page="s/{_e(s["id"])}" class="sess">{_e(s["label"])} · {n} game{"s" if n != 1 else ""}'
                       + (" · summary" if s.get("summary_md") else "") + "</a>")
            pages.append(f'<section class="page" id="p-s--{_e(s["id"])}">{_session_html(s, day)}</section>')
            for i, g in enumerate(s["games"]):
                cls = "game res-" + _e(g["meta"].get("result") or "none") + ("" if g["coached"] else " nc")
                nav.append(f'<a href="#g/{_e(g["id"])}" data-page="g/{_e(g["id"])}" class="{cls}" title="{_e(g["dir"])}">{_e(g["title"])}</a>')
                prev = s["games"][i - 1] if i else None
                nxt = s["games"][i + 1] if i + 1 < n else None
                pages.append(f'<section class="page" id="p-g--{_e(g["id"])}">{_game_html(g, s, prev, nxt)}</section>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(tree["player"])} · {_e(tree["app"])}</title><style>{CSS}</style></head><body>'
            f'<nav>{"".join(nav)}</nav><main>{"".join(pages)}</main><script>{JS}</script></body></html>')


def build(out: Path | None = None) -> Path:
    tree = collect()
    out = out or library() / PAGE_NAME
    out.write_text(render(tree), encoding="utf-8")
    return out
