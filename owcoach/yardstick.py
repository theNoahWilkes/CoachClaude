"""The dev-mode yardstick (ADR 0012): a triage run of a session against a full read of it.

Both are coached copies of the same session: one by `owcoach coach`, one by `owcoach coach
--full-read`. This compares them for free, from what they wrote:

- **Moments.** Each of the full read's session moments is *found* when a moment of the triage
  run's summary cites it (in its heading or its body: one story can cover two deaths), *dropped* when the triage shortlisted it or a match writer nominated it but the
  summary left it out, and *missed* otherwise: the triage never saw it. Two moments are the same
  when they are in the same match and share a death or ult id or come within MATCH_S seconds.
- **Focus grades.** The stoplight per focus in each match report, side by side.
- **Labels.** The player's labelled deaths (docs/ow/labels/deaths.md) in this session: whether
  each run read the death (a notes file) and whether its summary cites it. The labels referee
  both, but judging what a run said against them is a reader's job, not this module's.
- **Cost**, from each copy's `.coach` logs.

Every miss is a fix to the facts block, the preprocessor or the triage brief.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .briefs import _secs, shortlist
from .coach import _logged_cost, game_dirs
from .moments import KINDS, kinds_for

MATCH_S = 10.0           # s: two moments of one match this close are the same moment
LABELS = Path(__file__).resolve().parent.parent / "docs" / "ow" / "labels" / "deaths.md"

CITE_RE = re.compile(r"(?<![\w:])(?:(m\d{2})\s+)?(?:([duk]\d{2})|(\d{1,2}:\d{2})(?:\s*-\s*(\d{1,2}:\d{2}))?)(?![\w:])")
LABEL_RE = re.compile(r"^###\s+(.+?)\s+/\s+(.+?)\s+(d\d{2})\b", re.M)
LIGHT_RE = re.compile(r"^\s*[-*]?\s*(🟢|🟡|🔴|⚪)\s*\*\*(.+?)\*\*", re.M)


def _section(text: str, name: str) -> str:
    """The body of `## name` up to the next `## ` heading."""
    m = re.search(rf"^##\s+{re.escape(name)}\b.*$", text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^##\s", text[m.end():], re.M)
    return text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]


def _times(game: Path) -> dict[str, float]:
    """Death and ult ids of a match -> match clock in seconds, from its packet."""
    pk = json.loads((game / "packet" / "packet.json").read_text(encoding="utf-8"))
    out = {d["id"]: _secs(d["clock"]) for d in pk.get("deaths") or [] if d.get("clock")}
    for u in pk.get("ults") or []:
        at = (u.get("used") or u.get("ready") or {}).get("clock")
        if at:
            out[u["id"]] = _secs(at)
    return out


def _cites(text: str, default: str | None = None) -> dict[str, dict]:
    """Every cited moment in a text, per match prefix: {"m03": {"ids": {...}, "clocks": [(from, to)]}}.
    A clock is a span (a point or a range, 3:11-3:58). A bare id or clock belongs to `default`
    (the match of a heading), or to the last match named."""
    out: dict[str, dict] = {}
    cur = default
    for m, mid, clock, to in CITE_RE.findall(text):
        cur = m or cur
        if not cur:
            continue
        p = out.setdefault(cur, {"ids": set(), "clocks": []})
        if mid:
            p["ids"].add(mid)
        else:
            p["clocks"].append((_secs(clock), _secs(to or clock)))
    return out


def moments(summary: str) -> list[dict]:
    """A session summary's `## Moments`: [{"title", "match", "ids", "clocks", "cited"}] per `### N.`
    entry. A moment is what its heading cites; "cited" adds its body, where other moments are
    often mentioned in passing ("same story as m03 d02")."""
    body = _section(summary, "Moments")
    parts = re.split(r"^###\s+", body, flags=re.M)[1:]
    out = []
    for part in parts:
        title = part.splitlines()[0].strip()
        head = re.search(r"\b(m\d{2})\b", title)
        if not head:
            continue
        k = head.group(1)
        c = _cites(title, k).get(k, {"ids": set(), "clocks": []})
        body = _cites(part, k).get(k, {"ids": set(), "clocks": []})
        out.append({"title": title, "match": k, "ids": c["ids"], "clocks": c["clocks"], "cited": body})
    return out


def _same(a: dict, b: dict, times: dict[str, float]) -> bool:
    """Two citations of one match name the same moment: a shared id, or spans (an id counts as
    its clock) within MATCH_S of each other."""
    if a["ids"] & b["ids"]:
        return True
    ta = a["clocks"] + [(times[i], times[i]) for i in a["ids"] if i in times]
    tb = b["clocks"] + [(times[i], times[i]) for i in b["ids"] if i in times]
    return any(max(x0, y0) - min(x1, y1) <= MATCH_S for x0, x1 in ta for y0, y1 in tb)


def _nominations(game: Path) -> dict:
    """What a match's writer nominated (notes/summary.md `## Moments`), as citations."""
    p = game / "packet" / "notes" / "summary.md"
    if not p.exists():
        return {"ids": set(), "clocks": []}
    return _cites(_section(p.read_text(encoding="utf-8", errors="replace"), "Moments"),
                  game.name[:3]).get(game.name[:3], {"ids": set(), "clocks": []})


def lights(game: Path) -> list[tuple[str, str]]:
    """A match report's `## Focus` stoplights: [(stoplight, focus)]."""
    p = game / "packet" / "coaching.md"
    text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    return LIGHT_RE.findall(_section(text, "Focus"))


def by_kind(lines: list[tuple[str, str]]) -> dict[str, tuple[str, bool]]:
    """Stoplights per focus test kind: {kind: (stoplight, shared)}. A line names the kinds its
    focus triggers on (moments.kinds_for); `shared` when one line grades several kinds, since the
    writer merged them and its light is not one test's. A kind graded twice keeps the first."""
    out: dict[str, tuple[str, bool]] = {}
    for light, focus in lines:
        kinds = kinds_for(focus)
        for kind in kinds:
            out.setdefault(kind, (light, len(kinds) > 1))
    return out


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if c.isalnum())


def labelled(session: Path, games: list[Path], labels: Path = LABELS) -> list[tuple[Path, str, str]]:
    """The labelled deaths of this session: [(match folder, death id, heading)]."""
    if not labels.exists():
        return []
    out = []
    for rec, where, did in LABEL_RE.findall(labels.read_text(encoding="utf-8")):
        if _fold(rec) not in _fold(session.name):
            continue
        for g in games:
            if _fold(where) in _fold(g.name):
                out.append((g, did, f"{rec} / {where} {did}"))
    return out


def cost(session: Path) -> float:
    return sum(_logged_cost(f) for f in (session / ".coach").rglob("*.jsonl"))


def _read(game: Path, did: str) -> bool:
    return (game / "packet" / "notes" / f"{did}.md").exists()


def compare(triage: Path, full: Path) -> str:
    """The yardstick report, as Markdown."""
    tg = {g.name[:3]: g for g in game_dirs(triage)}
    fg = {g.name[:3]: g for g in game_dirs(full)}
    times = {k: _times(g) for k, g in fg.items()}
    picks = shortlist(triage)
    t_mom = moments((triage / "coaching.md").read_text(encoding="utf-8", errors="replace")
                    if (triage / "coaching.md").exists() else "")
    f_mom = moments((full / "coaching.md").read_text(encoding="utf-8", errors="replace")
                    if (full / "coaching.md").exists() else "")
    L = [f"# Yardstick: {triage.name}", "",
         f"Triage run `{triage}` against full read `{full}`.", ""]

    L += ["## Moments (the full read's, and what the triage run did with each)", ""]
    tally = {"found": 0, "dropped": 0, "missed": 0}
    for m in f_mom:
        t = times.get(m["match"], {})
        if any(x["match"] == m["match"] and _same(x["cited"], m, t) for x in t_mom):
            verdict = "found"
        elif m["match"] in tg and (_same(picks.get(m["match"], {"ids": set(), "clocks": []}), m, t)
                                   or _same(_nominations(tg[m["match"]]), m, t)):
            verdict = "dropped"
        else:
            verdict = "missed"
        tally[verdict] += 1
        L.append(f"- **{verdict}**: {m['title']}")
    if not f_mom:
        L.append("The full read's summary has no `## Moments`.")
    extra = [x for x in t_mom if not any(x["match"] == m["match"] and _same(x, m, times.get(m["match"], {})) for m in f_mom)]
    L += ["", f"{tally['found']} of {len(f_mom)} found, {tally['dropped']} shortlisted or nominated but dropped, "
          f"{tally['missed']} missed at triage.", ""]
    if extra:
        L += ["Only in the triage run:"] + [f"- {x['title']}" for x in extra] + [""]

    L += ["## Focus grades (paired by what each line tests: under half HP, down two, respawn)", "",
          "| match | test | full read | triage | |", "|---|---|---|---|---|"]
    agree = total = 0
    for k in sorted(fg):
        a, b = by_kind(lights(fg[k])), by_kind(lights(tg[k]) if k in tg else [])
        for kind in [x for x in KINDS if x in a or x in b]:
            (x, xs), (y, ys) = a.get(kind, ("–", False)), b.get(kind, ("–", False))
            note = "one line for several tests" if xs or ys else ("" if x == y else "differs")
            if x != "–" and y != "–" and not (xs or ys):
                total += 1
                agree += x == y
            L.append(f"| {k} | {KINDS[kind]} | {x} | {y} | {note} |")
    L += ["", f"{agree} of {total} comparable grades agree (both runs graded the test on a line of its own).", ""]

    L += ["## Labelled deaths", ""]
    lab = labelled(full, list(fg.values()))
    if not lab:
        L.append("None of this session's deaths are labelled.")
    else:
        L += ["| death | full read: read / cited | triage: read / cited |", "|---|---|---|"]
        for g, did, head in lab:
            k = g.name[:3]
            death = {"ids": {did}, "clocks": []}
            cited_f, cited_t = (any(m["match"] == k and _same(m["cited"], death, times[k]) for m in ms) for ms in (f_mom, t_mom))
            read_t = k in tg and _read(tg[k], did)
            L.append(f"| {head} | {'yes' if _read(g, did) else 'no'} / {'yes' if cited_f else 'no'} "
                     f"| {'yes' if read_t else 'no'} / {'yes' if cited_t else 'no'} |")
        L += ["", "Judge what each run said against the label by hand or with a grader: this table only "
              "says whether it looked."]

    L += ["", "## Cost", "", f"Full read ${cost(full):.2f}, triage run ${cost(triage):.2f}, from each copy's `.coach` logs. "
          "A copy that reused another run's reader notes shows only what it ran itself."]
    return "\n".join(L).rstrip() + "\n"
