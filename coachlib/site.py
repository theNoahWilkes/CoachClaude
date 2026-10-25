"""The page renderer both coaches share: a plain tree in, one self-contained HTML file out.

The renderer knows nothing about either game. A collector (owcoach.site.collect, hotscoach
collect_hots) decides the content and hands over this shape:

  tree:    app, player, title, generated, version, columns [{key, label, align?}], days [...], pages [...],
           tables [...] (home extras), notes [str], other {title, href} | None, banner (md) | None
  day:     date (YYYY-MM-DD), sessions [session], combined [session]   (combined = a summary over sessions)
  session: id, label, date, kind ("session" | "combined"), sub (html), games [game], summary_md,
           tables [table], warn (str), actions [action] (on the day page, after its matches table)
  game:    id, title, nav (sidebar text, without the result) | None, sub (html), result (class suffix),
           coached, processed, cells {key: str | {text, cls}},
           warnings [str], tables [table], images [{src, alt}], timeline | None, video (src) | None,
           links [{label, href}], report_md (+ report_title), notes_md (+ notes_title: a second text
           block, e.g. what the lessons file says about this game), moments [moment], details [detail]
  table:   title?, header [str], rows [[cell]], align_first? (bool: first column is a row header),
           note (html, a line under the table) | None
  timeline: duration, deaths [{id, t, to?, label}], spans [{from, to, lane: main|top|bottom, cls, label}],
           marks [{t, lane: top|bottom, cls, label, id?}], ticks (seconds between tick labels)
  moment:  id, kind (css class), title, extra (small text), flags [str], video_t | None, clock,
           stills [{src, label, title}], details [detail]
  detail:  summary, md | pre | html
  page:    id, title, nav, intro (html) | None, md, actions [action] (above the md)
  action:  label, action (name the local server answers), args {} | None, cmd (the same thing as a
           CLI command, copied when the page is opened as a file), title (hover text) | None,
           input (an args key filled from a text box; cmd has {} where the text goes) | None,
           placeholder | None, text (a line before the button) | None
           game.actions sit under the game's title the same way.

Buttons: an action is a button. Served by coachlib.serve, the page carries a token and a click
POSTs to /api/<action>; opened as a file, a click copies `cmd` to the clipboard instead.

A link to `#g/<game id>@<seconds>` opens that game's page and plays its clip from that time
(the collector writes these into report and summary markdown, so a clock in the text is a clip).

The sidebar lists one row per day, which is one session in the glossary's sense (one sitting):
its date and win-loss record, with that day's matches under it. The day row opens a day page
with every summary of the day; the collector's sessions and combined summaries are not sidebar
rows of their own. The newest day starts open, older days start folded.

Images and clips stay as relative links from the page's folder; nothing is copied. Needs
markdown-it-py for the markdown bodies.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date as _date
from pathlib import Path


def md(text: str | None) -> str:
    if not text:
        return ""
    from markdown_it import MarkdownIt
    return MarkdownIt("commonmark").enable("table").enable("strikethrough").render(text)


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def num(v, digits=0, default="") -> str:
    if v is None:
        return default
    return f"{v:,.{digits}f}"


def mmss(t: float) -> str:
    t = max(0, int(round(t or 0)))
    return f"{t // 60}:{t % 60:02d}"


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()


def _cell(c) -> str:
    if isinstance(c, dict):
        cls = f' class="{e(c.get("cls"))}"' if c.get("cls") else ""
        inner = f'<a href="{e(c["href"])}">{e(c.get("text"))}</a>' if c.get("href") else e(c.get("text"))
        return f"<td{cls}>{inner}</td>"
    return f"<td>{e(c)}</td>"


def table_html(t: dict) -> str:
    out = []
    if t.get("title"):
        out.append(f'<h2>{e(t["title"])}</h2>')
    if t.get("sub"):
        out.append(f'<p class="sub">{t["sub"]}</p>')
    out.append('<table class="stats' + (" games" if t.get("wide") else "") + '"><tr>'
               + "".join(f"<th>{e(h)}</th>" for h in t.get("header") or []) + "</tr>")
    for row in t.get("rows") or []:
        cells = list(row)
        first = f"<th>{e(cells[0])}</th>" if t.get("align_first", True) and cells and not isinstance(cells[0], dict) else _cell(cells[0]) if cells else ""
        out.append("<tr>" + first + "".join(_cell(c) for c in cells[1:]) + "</tr>")
    out.append("</table>")
    if t.get("note"):
        out.append(f'<p class="tnote">{t["note"]}</p>')
    return "".join(out)


def games_table(tree: dict, games: list[dict]) -> str:
    cols = tree.get("columns") or []
    head = "".join(f'<th class="al">{e(c["label"])}</th>' if c.get("align") == "left" else f'<th>{e(c["label"])}</th>' for c in cols)
    rows = []
    for g in games:
        cells = []
        for c in cols:
            v = (g.get("cells") or {}).get(c["key"], "")
            if c.get("align") == "left":
                v = {"text": v.get("text") if isinstance(v, dict) else v, "cls": "al " + ((v.get("cls") or "") if isinstance(v, dict) else ""),
                     "href": v.get("href") if isinstance(v, dict) else None}
            cells.append(_cell(v))
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="stats games"><tr>{head}</tr>{"".join(rows)}</table>'


def timeline_svg(tl: dict | None) -> str:
    if not tl or not tl.get("duration"):
        return ""
    dur = tl["duration"]
    W, H = 1000, 56
    x = lambda t: round(W * max(0.0, min(1.0, (t or 0) / dur)), 1)
    lane_y = {"main": (22, 12), "top": (14, 6), "bottom": (36, 5)}
    out = [f'<svg class="tl" viewBox="0 0 {W} {H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">',
           f'<rect x="0" y="22" width="{W}" height="12" class="tl-bar"/>']
    for s in tl.get("spans") or []:
        y, h = lane_y.get(s.get("lane") or "main", lane_y["main"])
        out.append(f'<rect x="{x(s["from"])}" y="{y}" width="{max(2, x(s["to"]) - x(s["from"]))}" height="{h}" class="{e(s.get("cls") or "tl-span")}">'
                   f'<title>{e(s.get("label"))}</title></rect>')
    for m in tl.get("marks") or []:
        xm = x(m["t"])
        pts = f"{xm},8 {xm - 5},16 {xm + 5},16" if (m.get("lane") or "top") == "top" else f"{xm},48 {xm - 5},42 {xm + 5},42"
        data = f' data-moment="{e(m["id"])}"' if m.get("id") else ""
        out.append(f'<polygon points="{pts}" class="{e(m.get("cls") or "tl-mark")}"{data}><title>{e(m.get("label"))}</title></polygon>')
    for d in tl.get("deaths") or []:
        if d.get("to"):
            out.append(f'<rect x="{x(d["t"])}" y="22" width="{max(2, x(d["to"]) - x(d["t"]))}" height="12" class="tl-dead"/>')
        data = f' data-moment="{e(d["id"])}"' if d.get("id") else ""
        out.append(f'<circle cx="{x(d["t"])}" cy="28" r="6" class="tl-death"{data}><title>{e(d.get("label"))}</title></circle>')
    out.append("</svg>")
    step = tl.get("ticks") or 120
    ticks = "".join(f'<span style="left:{x(t) / 10}%">{mmss(t)}</span>' for t in range(0, int(dur) + 1, step))
    return "".join(out) + f'<div class="tl-ticks">{ticks}</div>'


def actions_html(acts: list[dict] | None) -> str:
    """Buttons for the local server (see coachlib.serve), one row each."""
    rows = []
    for a in acts or []:
        attrs = "" if not a.get("action") else (f'class="act" data-action="{e(a["action"])}" data-args="{e(json.dumps(a.get("args") or {}))}" '
                 f'data-cmd="{e(a.get("cmd") or "")}"' + (f' title="{e(a["title"])}"' if a.get("title") else "")
                 + (f' data-input="{e(a["input"])}"' if a.get("input") else ""))
        box = f'<input type="text" placeholder="{e(a.get("placeholder") or "")}">' if a.get("input") else ""
        text = f'<span>{a["text"]}</span>' if a.get("text") else ""
        btn = f'<button {attrs}>{e(a["label"])}</button>' if a.get("action") else ""
        rows.append(f'<div class="actrow">{text}{box}{btn}</div>')
    return f'<div class="acts">{"".join(rows)}</div>' if rows else ""


def _detail(d: dict) -> str:
    body = (f'<div class="md">{md(d["md"])}</div>' if d.get("md") else
            f'<pre class="facts">{e(d["pre"])}</pre>' if d.get("pre") else d.get("html") or "")
    return f'<details><summary>{e(d["summary"])}</summary>{body}</details>'


def _moment(g: dict, m: dict) -> str:
    vt = m.get("video_t")
    btn = ""
    if g.get("video") and vt is not None:
        btn = (f'<button class="seek" data-video="v-{e(g["id"])}" data-t="{max(0.0, vt - 10):.1f}">▶ −10 s</button>'
               f'<button class="seek" data-video="v-{e(g["id"])}" data-t="{vt:.1f}">▶ at {e(m.get("clock"))}</button>')
    flags = "".join(f'<span class="flag">{e(f)}</span>' for f in m.get("flags") or [])
    out = [f'<div class="moment {e(m.get("kind"))}" id="m-{e(g["id"])}-{e(m["id"])}"><h3>{e(m["title"])}'
           + (f' <small>{e(m["extra"])}</small>' if m.get("extra") else "") + f'</h3><div class="mbar">{btn}{flags}</div>']
    if m.get("stills"):
        out.append('<div class="strip">' + "".join(
            f'<a href="{e(st["src"])}" target="_blank" title="{e(st.get("title"))}"><img src="{e(st["src"])}" loading="lazy" alt="{e(st.get("label"))}">'
            f'<span>{e(st.get("label"))}</span></a>' for st in m["stills"]) + "</div>")
    if m.get("body_md"):
        out.append(f'<div class="md">{md(m["body_md"])}</div>')
    for d in m.get("details") or []:
        out.append(_detail(d))
    out.append("</div>")
    return "".join(out)


def _game(tree: dict, g: dict, day: dict, prev: dict | None, nxt: dict | None) -> str:
    nav = ('<div class="pn">' + (f'<a href="#g/{e(prev["id"])}">← {e(prev["title"])}</a>' if prev else "<span></span>")
           + f'<a href="#d/{e(day["id"])}">{e(day["long"])}</a>'
           + (f'<a href="#g/{e(nxt["id"])}">{e(nxt["title"])} →</a>' if nxt else "<span></span>") + "</div>")
    out = [nav, f'<h1>{e(g["title"])}</h1>']
    if g.get("sub"):
        out.append(f'<p class="sub">{g["sub"]}</p>')
    for w in g.get("warnings") or []:
        out.append(f'<p class="warn">{w}</p>')
    out.append(actions_html(g.get("actions")))
    if g.get("tables") or g.get("images"):
        out.append('<div class="two"><div>' + "".join(table_html(t) for t in g.get("tables") or []) + "</div>"
                   + '<div class="imgs">' + "".join(f'<a href="{e(i["src"])}" target="_blank"><img src="{e(i["src"])}" loading="lazy" alt="{e(i.get("alt"))}"></a>'
                                                    for i in g.get("images") or []) + "</div></div>")
    out.append(timeline_svg(g.get("timeline")))
    if g.get("video"):
        links = "".join(f'<a href="{e(l["href"])}"' + (' target="_blank"' if l.get("blank") else "") + f'>{e(l["label"])}</a>' for l in g.get("links") or [])
        out.append(f'<div class="clip"><video id="v-{e(g["id"])}" controls preload="none" src="{e(g["video"])}"></video>'
                   f'<div class="clipbar"><span>Clip: seeks from each moment below.</span>{links}</div></div>')
    elif g.get("links"):
        out.append('<p class="sub">' + " · ".join(f'<a href="{e(l["href"])}" target="_blank">{e(l["label"])}</a>' for l in g["links"]) + "</p>")
    if g.get("report_md"):
        out.append(f'<h2>{e(g.get("report_title") or "Coaching report")}</h2><div class="md">{md(g["report_md"])}</div>')
    if g.get("notes_md"):
        out.append(f'<h2>{e(g.get("notes_title") or "Notes")}</h2><div class="md notes">{md(g["notes_md"])}</div>')
    if g.get("moments"):
        out.append(f'<h2>{e(g.get("moments_title") or "Moments")}</h2>' + "".join(_moment(g, m) for m in g["moments"]))
    for d in g.get("details") or []:
        out.append(_detail(d))
    return "".join(out)


def day_label(d: str, long: bool = False, this_year: int | None = None) -> str:
    """'2026-10-25' -> 'Sun 25 Oct' (or 'Sunday 25 October 2026'); the year shows on short labels only when it isn't this year."""
    try:
        dt = _date.fromisoformat(d)
    except (TypeError, ValueError):
        return str(d)
    if long:
        return f"{dt:%A} {dt.day} {dt:%B %Y}"
    return f"{dt:%a} {dt.day} {dt:%b}" + ("" if dt.year == (this_year or _date.today().year) else f" {dt.year}")


def record(games: list[dict]) -> str:
    """Win-loss over the games, e.g. '3–1' or '2–2–1' with draws."""
    res = [(g.get("result") or "").lower() for g in games]
    w = sum(r in ("win", "victory") for r in res)
    l = sum(r in ("loss", "defeat") for r in res)
    d = sum(r == "draw" for r in res)
    if not (w or l or d):
        return ""
    return f"{w}–{l}" + (f"–{d}" if d else "")


def _day(tree: dict, day: dict) -> str:
    """One page per day: every match of the day, then each summary the day has (combined first)."""
    parts = list(day.get("combined") or []) + list(day["sessions"])
    games = [g for s in day["sessions"] for g in s["games"]]
    out = [f'<h1>{e(day["long"])}</h1>']
    rec = record(games)
    subs = [s["sub"] if len(parts) == 1 else f'{e(s["label"])} {s["sub"]}' for s in parts if s.get("sub")]
    head = " · ".join(x for x in (f"{len(games)} match{'es' if len(games) != 1 else ''}" if games else "", rec) if x)
    out.append(f'<p class="sub">{" · ".join(x for x in [head] + subs if x)}</p>')
    if games:
        out.append(games_table(tree, games))
    for s in parts:
        out.append(actions_html(s.get("actions")))
    summaries = [s for s in parts if s.get("summary_md")]
    for s in parts:
        if s.get("summary_md"):
            name = e(s.get("summary_title") or "Session summary")
            out.append(f'<h2>{name if len(summaries) == 1 else name + " · " + e(s["label"])}</h2><div class="md">{md(s["summary_md"])}</div>')
        if s.get("notes_md"):
            out.append(f'<h2>{e(s.get("notes_title") or "Notes")}</h2><div class="md notes">{md(s["notes_md"])}</div>')
        for t in s.get("tables") or []:
            out.append(table_html(t))
    if not summaries and len(games) > 1:
        warn = next((s["warn"] for s in parts if s.get("warn")), None)
        if warn:
            out.append(f'<p class="warn">{e(warn)}</p>')
    return "".join(out)


def _home(tree: dict) -> str:
    allg = [g for d in tree["days"] for s in d["sessions"] for g in s["games"]]
    out = [f'<h1>{e(tree.get("home_title") or tree["title"])}</h1>']
    if tree.get("home_sub"):
        out.append(f'<p class="sub">{tree["home_sub"]}</p>')
    if tree.get("banner"):
        out.append(f'<div class="warn md">{md(tree["banner"])}</div>')
    out.append("<h2>All games</h2>" + games_table(tree, allg))
    for t in tree.get("tables") or []:
        out.append(table_html(t))
    notes = list(tree.get("notes") or [])
    if tree.get("version") or tree.get("generated"):
        notes.append(f"Built by coachclaude {tree.get('version') or '?'}" + (f" on {tree['generated']}" if tree.get("generated") else "") + ".")
    if notes:
        out.append("<h2>About this page</h2><ul>" + "".join(f"<li>{e(n)}</li>" for n in notes) + "</ul>")
    return "".join(out)


CSS = """
:root{--bg:#141619;--panel:#1c1f24;--ink:#e6e6e6;--dim:#9aa3ad;--line:#2b3038;--acc:#f2a93b;--red:#e05252;--green:#5fbf6a;--blue:#5aa0e6}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;display:grid;grid-template-columns:300px 1fr;min-height:100vh}
nav{background:var(--panel);border-right:1px solid var(--line);padding:12px 0;position:sticky;top:0;height:100vh;overflow:auto;font-size:14px}
nav a{color:var(--ink);text-decoration:none;display:block;padding:3px 14px;border-left:3px solid transparent;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
nav a:hover{background:#242830}nav a.cur{border-left-color:var(--acc);background:#262a32}
nav details.day{margin-top:6px}nav summary{list-style:none;display:flex;align-items:center;cursor:pointer;padding-left:4px}nav summary::-webkit-details-marker{display:none}
nav summary::before{content:"▸";color:var(--dim);width:12px;flex:0 0 12px;font-size:11px}nav details[open]>summary::before{content:"▾"}
nav summary a{flex:1;font-weight:600;padding-left:6px;display:flex;justify-content:space-between}nav .rec{color:var(--dim);font-weight:400;font-variant-numeric:tabular-nums}
nav .game{padding-left:34px}nav .top{font-weight:600}nav .other{color:var(--dim);margin-top:14px;border-top:1px solid var(--line);padding-top:10px}
nav .res-victory::before,nav .res-win::before{content:"W ";color:var(--green)}nav .res-defeat::before,nav .res-loss::before{content:"L ";color:var(--red)}nav .res-draw::before{content:"D ";color:var(--dim)}
nav .nc{opacity:.55}
main{padding:20px 36px 80px;max-width:1300px;min-width:0}
.page{display:none}.page.cur{display:block}
h1{font-size:26px;margin:4px 0 2px}h2{font-size:19px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}h3{font-size:16px;margin:0 0 4px}
.sub{color:var(--dim);margin:0 0 14px}a{color:var(--blue)}code{background:#262a32;padding:1px 5px;border-radius:3px;font-size:13px}
.pn{display:flex;justify-content:space-between;gap:12px;color:var(--dim);font-size:13px;margin-bottom:8px}
.warn{background:#2c2415;border-left:3px solid var(--acc);padding:8px 12px}.warn p{margin:0}
table.stats{border-collapse:collapse;font-size:14px;margin:8px 0}table.stats th,table.stats td{border:1px solid var(--line);padding:3px 9px;text-align:right}
table.stats th{text-align:left;color:var(--dim);font-weight:500}table.stats tr:first-child th{text-align:right}table.stats tr:first-child th:first-child,table.stats th.al,table.stats td.al{text-align:left}
table.games{width:100%}
.res-victory,.res-win{color:var(--green)}.res-defeat,.res-loss{color:var(--red)}
.v-better{color:var(--green)}.v-worse{color:var(--red)}.v-normal-variation{color:var(--dim)}
.two{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:24px;align-items:start}.imgs{min-width:0}
.tnote{color:var(--dim);font-size:13px;margin:4px 0;max-width:46em}.imgs img{width:100%;max-height:360px;object-fit:contain;object-position:left top;border:1px solid var(--line);display:block;margin-bottom:6px}
.two h2{margin-top:8px}
.tl{width:100%;height:56px;display:block;margin-top:12px}.tl-bar{fill:#262a32}.tl-fight{fill:#3a4150}.tl-dead{fill:#5a2626}.tl-span{fill:#3a4150}
.tl-death{fill:var(--red);cursor:pointer}.tl-ult{fill:#7a5a1a}.tl-ult-use{fill:var(--acc);cursor:pointer}.tl-fb{fill:var(--green);cursor:pointer}.tl-mark{fill:var(--blue);cursor:pointer}
.tl-low{fill:#a07a2a}.tl-low-died{fill:var(--red)}.tl-obj{fill:var(--blue)}.tl-camp{fill:#6b7a8f}.tl-struct{fill:#8f6b6b}
.tl-ticks{position:relative;height:16px;font-size:11px;color:var(--dim)}.tl-ticks span{position:absolute;transform:translateX(-50%)}
.clip{margin:14px 0}.clip video{width:100%;max-height:420px;background:#000;border:1px solid var(--line)}
.clipbar{display:flex;gap:16px;font-size:13px;color:var(--dim);margin-top:4px}
.md{max-width:900px}.md table{border-collapse:collapse;font-size:14px}.md th,.md td{border:1px solid var(--line);padding:3px 9px}.md th{color:var(--dim);font-weight:500}
.md h1{font-size:20px;margin-top:16px}.md h2{font-size:17px;border:0;margin-top:20px}.md h3{font-size:15px;margin-top:14px}.md blockquote{color:var(--dim);border-left:3px solid var(--line);margin:0;padding-left:12px}
.md pre{background:#101214;padding:8px;overflow:auto}.md code{font-size:13px}
.md.notes p{border-left:3px solid var(--line);padding-left:12px;margin:8px 0}
.moment{border:1px solid var(--line);border-left:4px solid var(--red);border-radius:4px;padding:10px 12px;margin:10px 0;background:var(--panel)}
.moment.ult{border-left-color:var(--acc)}.moment.final_blow{border-left-color:var(--green)}.moment.objective{border-left-color:var(--blue)}.moment.note{border-left-color:var(--dim)}
.moment h3 small{color:var(--dim);font-weight:400;font-size:13px;margin-left:8px}
.mbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0 8px}.mbar:empty{display:none}
button.seek{background:#2a3140;color:var(--ink);border:1px solid var(--line);border-radius:3px;padding:2px 9px;cursor:pointer;font-size:13px}button.seek:hover{background:#364055}
.flag{background:#33261a;color:var(--acc);border-radius:3px;padding:1px 7px;font-size:12px}
.strip{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px}.strip.wrap{flex-wrap:wrap}
.strip a{position:relative;flex:0 0 auto}.strip img{height:120px;display:block;border:1px solid var(--line)}
.strip span{position:absolute;left:3px;bottom:3px;background:rgba(0,0,0,.65);font-size:11px;padding:0 4px;border-radius:2px}
details{margin:6px 0}summary{cursor:pointer;color:var(--dim)}pre.facts{white-space:pre-wrap;font-size:12.5px;background:#101214;padding:8px;line-height:1.4}
.acts{margin:10px 0 14px}.actrow{display:flex;gap:10px;align-items:center;margin:6px 0;max-width:900px}.actrow span{flex:1}
.dim{color:var(--dim)}#jobs a{margin-left:6px;cursor:pointer}
.actrow input{flex:1;background:#101214;color:var(--ink);border:1px solid var(--line);border-radius:3px;padding:4px 8px;font:inherit}
button.act{background:#3a2f18;color:var(--ink);border:1px solid var(--acc);border-radius:3px;padding:4px 12px;cursor:pointer;font:inherit;font-size:14px;white-space:nowrap}
button.act:hover{background:#4a3a1c}button.act:disabled{opacity:.5;cursor:wait}button.act.on{background:var(--acc);color:#141619}
#toast{position:fixed;right:16px;bottom:16px;max-width:460px;background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--green);padding:10px 14px;display:none;z-index:9;white-space:pre-wrap}
#toast.bad{border-left-color:var(--red)}#toast.on{display:block}
#jobs{position:fixed;left:16px;bottom:16px;background:var(--panel);border:1px solid var(--line);padding:6px 12px;font-size:13px;color:var(--dim);display:none;z-index:9}#jobs.on{display:block}
@media(max-width:900px){.two{grid-template-columns:1fr}body{grid-template-columns:1fr}nav{position:static;height:auto;max-height:40vh}main{padding:12px 16px}}
"""

JS = """
(function(){
  var pages=document.querySelectorAll('.page'),links=document.querySelectorAll('nav a[data-page]');
  function show(){
    var h=location.hash.slice(1)||'home',at=h.indexOf('@'),t=at<0?null:parseFloat(h.slice(at+1));
    if(at>=0)h=h.slice(0,at);
    var id='p-'+h.replace(/\\//g,'--'),hit=false;
    pages.forEach(function(p){var on=p.id===id;p.classList.toggle('cur',on);hit=hit||on;});
    if(!hit){pages.forEach(function(p){p.classList.toggle('cur',p.id==='p-home');});h='home';}
    links.forEach(function(a){var on=a.getAttribute('data-page')===h;a.classList.toggle('cur',on);
      if(on){var d=a.closest('details');if(d)d.open=true;a.scrollIntoView({block:'nearest'});}});
    window.scrollTo(0,0);
    if(hit&&t!==null&&!isNaN(t)&&h.indexOf('g/')===0)seek('v-'+h.slice(2),t);
  }
  window.addEventListener('hashchange',show);
  function seek(vid,t){var v=document.getElementById(vid);if(!v)return;
    v.scrollIntoView({block:'center'});
    var go=function(){try{v.currentTime=t;}catch(e){}v.play&&v.play().catch(function(){});};
    if(v.readyState>0)go();else{v.addEventListener('loadedmetadata',go,{once:true});v.load();}}
  document.addEventListener('click',function(e){
    var b=e.target.closest('button.seek');if(b){seek(b.getAttribute('data-video'),parseFloat(b.getAttribute('data-t')));return;}
    var a=e.target.closest('a[href^="#"]');if(a&&a.getAttribute('href')==location.hash&&a.getAttribute('href').indexOf('@')>0){e.preventDefault();show();return;}
    var m=e.target.closest('[data-moment]');if(m){var pg=m.closest('.page');var el=pg&&pg.querySelector('[id$="-'+m.getAttribute('data-moment')+'"]');if(el)el.scrollIntoView({block:'start'});}
  });
  show();

  // Buttons (coachlib.serve). Served: POST with the page's token. A file: copy the command.
  var API=window.COACH_API,toastT;
  function toast(msg,bad){var t=document.getElementById('toast');t.textContent=msg;t.className='on'+(bad?' bad':'');
    clearTimeout(toastT);toastT=setTimeout(function(){t.className='';},bad?12000:6000);}
  function copy(text){
    if(navigator.clipboard&&navigator.clipboard.writeText)return navigator.clipboard.writeText(text).catch(function(){fallback(text);});
    fallback(text);}
  function fallback(text){var ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');}catch(e){}ta.remove();}
  function post(name,args){
    return fetch('/api/'+name,{method:'POST',headers:{'Content-Type':'application/json','X-Coach-Token':API.token},body:JSON.stringify(args)})
      .then(function(r){return r.json();});}
  function act(b){
    var args=JSON.parse(b.getAttribute('data-args')||'{}'),key=b.getAttribute('data-input'),cmd=b.getAttribute('data-cmd');
    if(key){var inp=b.parentNode.querySelector('input'),v=(inp&&inp.value||'').trim();
      if(!v){toast('Type it in the box first.',true);return;}args[key]=v;cmd=cmd.replace('{}',v.replace(/"/g,'\\\\"'));}
    if(!API){copy(cmd);toast('Copied: '+cmd+'\\nPaste it in a terminal. Opened from the CoachClaude desktop shortcut, this button does it for you.');return;}
    b.disabled=true;
    post(b.getAttribute('data-action'),args)
      .then(function(j){toast(j.message||'Done.',!j.ok);if(j.ok&&j.reload)setTimeout(function(){location.reload();},1200);else b.disabled=false;poll();})
      .catch(function(){toast('The CoachClaude server has stopped. Open it again from the desktop shortcut.',true);b.disabled=false;});
  }
  document.addEventListener('click',function(e){var b=e.target.closest('button.act');if(b)act(b);});
  document.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target.matches('.actrow input')){var b=e.target.parentNode.querySelector('button.act');if(b)act(b);}});
  var pollT,wasBusy=false;
  function poll(){
    if(!API)return;clearTimeout(pollT);
    fetch('/api/ping').then(function(r){return r.json();}).then(function(j){
      var q=j.jobs||{},busy=!!(q.current||(q.queued||[]).length),el=document.getElementById('jobs');
      el.className=busy?'on':'';
      el.innerHTML='';if(busy){el.appendChild(document.createTextNode('Working on '+(q.current||'…')+((q.queued||[]).length?' · queued:':'')));
        (q.queued||[]).forEach(function(j){var a=document.createElement('a');a.textContent=j.label+' ✕';a.title='Cancel this one';
          a.onclick=function(){post('cancel',{key:j.key}).then(function(r){toast(r.message,!r.ok);poll();});};el.appendChild(a);});}
      if(wasBusy&&!busy){toast((q.log||[]).slice(-1)[0]||'Done.');setTimeout(function(){location.reload();},1500);}
      wasBusy=busy;pollT=setTimeout(poll,busy?5000:60000);
    }).catch(function(){pollT=setTimeout(poll,60000);});
  }
  poll();
})();
"""


def render(tree: dict) -> str:
    """The tree -> one HTML page (images and clips stay as relative links)."""
    nav = [f'<a href="#home" data-page="home" class="top">{e(tree.get("nav_home") or tree["title"])}</a>']
    pages = [f'<section class="page" id="p-home">{_home(tree)}</section>']
    for pg in tree.get("pages") or []:
        nav.append(f'<a href="#{e(pg["id"])}" data-page="{e(pg["id"])}" class="top">{e(pg.get("nav") or pg["title"])}</a>')
        pages.append(f'<section class="page" id="p-{e(pg["id"])}"><h1>{e(pg["title"])}</h1>'
                     + (f'<p class="sub">{pg["intro"]}</p>' if pg.get("intro") else "") + actions_html(pg.get("actions"))
                     + f'<div class="md">{md(pg.get("md")) or "<p class=warn>Nothing here yet.</p>"}</div></section>')
    days = [d for d in tree["days"] if d["sessions"] or d.get("combined")]
    for i, day in enumerate(days):
        day = dict(day, id=slug(day["date"]), long=day_label(day["date"], long=True))
        games = [g for s in day["sessions"] for g in s["games"]]
        rec = record(games)
        nav.append(f'<details class="day"{" open" if i == 0 else ""}><summary><a href="#d/{e(day["id"])}" data-page="d/{e(day["id"])}">'
                   f'{e(day_label(day["date"]))}' + (f'<span class="rec">{e(rec)}</span>' if rec else "") + "</a></summary>")
        pages.append(f'<section class="page" id="p-d--{e(day["id"])}">{_day(tree, day)}</section>')
        for j, g in enumerate(games):
            cls = "game res-" + e(g.get("result") or "none") + ("" if g.get("coached") else " nc")
            nav.append(f'<a href="#g/{e(g["id"])}" data-page="g/{e(g["id"])}" class="{cls}" title="{e(g["title"])}">{e(g.get("nav") or g["title"])}</a>')
            pages.append(f'<section class="page" id="p-g--{e(g["id"])}">'
                         f'{_game(tree, g, day, games[j - 1] if j else None, games[j + 1] if j + 1 < len(games) else None)}</section>')
        nav.append("</details>")
    if tree.get("other"):
        nav.append(f'<a href="{e(tree["other"]["href"])}" class="other">{e(tree["other"]["title"])} →</a>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(tree["title"])}</title><style>{CSS}</style></head><body>'
            f'<nav>{"".join(nav)}</nav><main>{"".join(pages)}</main><div id="toast"></div><div id="jobs"></div><script>{JS}</script></body></html>')


def write(tree: dict, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(tree), encoding="utf-8")
    return out
