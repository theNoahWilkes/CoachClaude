"""The pieces of a match and their briefs (ADR 0011, ADR 0012).

A session starts with one triage piece: it reads the session's digest (`moments.py`, text only)
and shortlists about eight moments. A match is then coached as pieces: one reader per two
shortlisted deaths, one per 30 sheets of the overview cells that cover its focus tests and the
shortlisted moments without a death, one for the shortlisted ults, then one writer. The full
read (every death, the whole match in overview sheets, every ult) stays as the dev-mode
yardstick, `pieces(game, picks=None)`. Each piece's brief is a template from the skill
(`coachlib/skills/ow-coach/briefs/<kind>.md`, `{{FIELD}}` markers) filled in here from
`packet.json` and the lessons file: the facts are the CLI's to give (ADR 0004), and filling a
template is not judgement. The driver (`coach.py`) runs one `claude -p` per piece.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import profile_dir, skill_dir
from .focus import current_focus

DEATHS_PER_READER = 2
SHEETS_PER_READER = 30          # first-pass sheets of 2 cells 5 s apart: 5 min of clock
DONE = {"deaths": "## Read", "overview": "## Rejoins", "ults": "## Ults read", "tests": "## Tests read",
        "triage": "## Shortlist"}   # a notes file's last section when complete
SHORTLIST_N = 8             # moments the triage shortlists for a session (the summary keeps about five)
TEST_PAD_S = 3.0            # s of cells read either side of a focus test window
MOMENT_PAD_S = 10.0         # s either side of a shortlisted moment that has only a clock
WRITER_CONSTRAINTS = (
    "Constraints: one game only, no session summary. Read the lessons file as usual but do NOT edit it "
    "(the summary process does that after every game is done): put what you would change under the "
    "'## Lessons' heading at the end of notes/summary.md, as step 4 says. Don't run shell commands; "
    "use Read, Glob and Grep for files."
)


@dataclass
class Piece:
    kind: str            # triage | deaths | overview | tests | ults | writer
    name: str            # triage | d01-d02 | overview_01 | tests_01 | ults | writer
    game: Path           # the match folder (the session folder for the triage)
    prompt: str
    notes: list[Path]    # the files whose completion marks the piece done

    def done(self) -> bool:
        if self.kind == "writer":
            rep, summ = self.game / "packet" / "coaching.md", self.game / "packet" / "notes" / "summary.md"
            if not (rep.exists() and summ.exists()):
                return False
            newest = max((n.stat().st_mtime for n in reader_notes(self.game)), default=0)
            return min(rep.stat().st_mtime, summ.stat().st_mtime) >= newest
        return all(_complete(n, DONE[self.kind]) for n in self.notes)


def reader_notes(game: Path) -> list[Path]:
    nd = game / "packet" / "notes"
    return [p for p in nd.glob("*.md") if re.fullmatch(r"(d\d+|overview_\d+|tests_\d+|ults)\.md", p.name)]


def write_all_notes(game: Path) -> Path:
    """Concatenate a game's reader notes into notes/all.md, in reading order, for the writer."""
    nd = game / "packet" / "notes"
    files = sorted(nd.glob("overview_*.md"), key=lambda p: p.name) + sorted(nd.glob("tests_*.md"), key=lambda p: p.name) + sorted(
        (p for p in nd.glob("d*.md") if re.fullmatch(r"d\d+\.md", p.name)), key=lambda p: p.name) + [p for p in [nd / "ults.md"] if p.exists()]
    parts = [f"<!-- {p.name} -->\n" + p.read_text(encoding="utf-8").rstrip() + "\n" for p in files]
    out = nd / "all.md"
    out.write_text(f"# All notes for {game.name} ({len(files)} files, in reading order)\n\n" + "\n".join(parts), encoding="utf-8")
    return out


def _complete(path: Path, marker: str) -> bool:
    if not path.exists():
        return False
    heads = re.findall(r"^## .*$", path.read_text(encoding="utf-8", errors="replace"), re.M)
    return bool(heads) and heads[-1].strip() == marker


def _template(kind: str) -> str:
    return (skill_dir() / "briefs" / f"{kind}.md").read_text(encoding="utf-8")


def fill(kind: str, fields: dict) -> str:
    text = _template(kind)
    for k, v in fields.items():
        text = text.replace("{{" + k + "}}", str(v))
    left = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if left:
        raise ValueError(f"{kind} brief: unfilled fields {sorted(set(left))}")
    return text


def focus_bullets(lessons: Path) -> list[str]:
    """The current focus, one entry per bullet: the bold wording(s) under '## Current focus'."""
    if not lessons.exists():
        return []
    section = re.sub(r"<!--.*?-->", "", current_focus(lessons.read_text(encoding="utf-8")), flags=re.S)
    bold = [" ".join(b.split()) for b in re.findall(r"\*\*(.+?)\*\*", section, re.S)]
    if bold:
        return bold
    first = next((ln for ln in section.splitlines()[1:] if ln.strip()), "")
    first = first.strip().lstrip("- ").strip()
    return [first] if first else []


def focus_wording(lessons: Path) -> str:
    """The current focus as the readers see it, all bullets in one line."""
    return " ".join(focus_bullets(lessons)) or "none set"


def _secs(clock: str) -> float:
    m, s = str(clock).split(":")
    return int(m) * 60 + float(s)


def _in(t: float | None, lo: float, hi: float) -> bool:
    return t is not None and lo <= t <= hi


def _hero_notes(packet: dict, heroes: set[str]) -> str:
    notes = packet.get("hero_notes") or {}
    found = [f"{h}: {profile_dir() / notes[h]}" for h in sorted(heroes) if h in notes]
    return "; ".join(found) if found else "none"


def triage_piece(session: Path, games: list[Path]) -> Piece:
    """The session's triage: writes the digest (code), then one process picks the moments."""
    from .moments import session_digest
    lessons = profile_dir() / "lessons.md"
    digest = session_digest(session, games, focus_bullets(lessons))
    player = next((json.loads((g / "packet" / "packet.json").read_text(encoding="utf-8")).get("player") for g in games), "?")
    out = session / "triage.md"
    f = {"DIGEST": digest, "LESSONS": lessons, "PLAYER": player or "?", "FOCUS": focus_wording(lessons), "SKILL_DIR": skill_dir(),
         "N": SHORTLIST_N, "OUT": out, "SESSION_NAME": session.name}
    return Piece("triage", "triage", session, fill("triage", f), [out])


PICK_RE = re.compile(r"^\s*[-*]\s*(m\d{2})\s+([duk]\d{2}(?:\s*\+\s*[duk]\d{2})*|\d{1,2}:\d{2})", re.M)


def shortlist(session: Path) -> dict[str, dict]:
    """The triage's picks per match prefix: {"m03": {"ids": {"d03", "d04", "u02"}, "clocks": [575.0]}}."""
    path = session / "triage.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    text = text[text.find("## Shortlist"):] if "## Shortlist" in text else ""
    picks: dict[str, dict] = {}
    for m, what in PICK_RE.findall(text):
        p = picks.setdefault(m, {"ids": set(), "clocks": []})
        if ":" in what:
            p["clocks"].append(_secs(what))
        else:
            p["ids"].update(x.strip() for x in what.split("+"))
    return picks


def _chunks(sheets: list[dict]) -> list[list[dict]]:
    """SHEETS_PER_READER sheets per reader; a short tail joins the chunk before it."""
    chunks = [sheets[i:i + SHEETS_PER_READER] for i in range(0, len(sheets), SHEETS_PER_READER)]
    if len(chunks) > 1 and len(chunks[-1]) < SHEETS_PER_READER // 3:
        tail = chunks.pop()               # pop first: `chunks[-2] += chunks.pop()` reindexes after the pop
        chunks[-1] += tail
    return chunks


def _windows(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def pieces(game: Path, picks: dict | None = None) -> list[Piece]:
    """Every piece of a match, writer last, with its brief filled in. `picks` is the triage's
    shortlist for this match ({"ids", "clocks"}); None is the full read (dev mode)."""
    packet_dir = game / "packet"
    packet = json.loads((packet_dir / "packet.json").read_text(encoding="utf-8"))
    lessons = profile_dir() / "lessons.md"
    common = {"PACKET": packet_dir, "PLAYER": packet.get("player", "?"), "FOCUS": focus_wording(lessons), "SKILL_DIR": skill_dir()}
    heroes_line = ", ".join(f"{h['hero']} {h.get('seconds', 0) / 60:.0f} min" for h in packet.get("heroes", [])) or "unknown hero"
    if picks is not None:
        return _lean_pieces(game, packet, lessons, common, heroes_line, picks)
    out: list[Piece] = []

    # overview: 5 minutes of first-pass sheets per reader
    sheets = [o for o in packet.get("overview", []) if not o.get("extra")]
    fights = (packet.get("hud_game") or {}).get("fights", [])
    lows = (packet.get("hud_game") or {}).get("low_episodes", [])
    presses = (packet.get("hud_game") or {}).get("presses", [])
    deaths = packet.get("deaths", [])
    ults = packet.get("ults", [])
    chunks = _chunks(sheets)
    for i, chunk in enumerate(chunks):
        nn = f"{i + 1:02d}"
        lo, hi = _secs(chunk[0]["from"]), _secs(chunk[-1]["to"])
        f = dict(common, NN=nn, FROM=chunk[0]["from"], TO=chunk[-1]["to"], HEROES=heroes_line,
                 SHEETS=", ".join(o["file"] for o in chunk),
                 DEATHS=", ".join(f"{d['id']} {d['clock']}" for d in deaths if _in(d.get("t"), lo, hi)) or "none",
                 ULTS=", ".join(x for u in ults for x in (
                     [f"{u['id']} ready {u['ready']['clock']}"] if _in((u.get("ready") or {}).get("t"), lo, hi) else []) + (
                     [f"{u['id']} used {u['used']['clock']}"] if _in((u.get("used") or {}).get("t"), lo, hi) else [])) or "none",
                 FIGHTS=", ".join(f"{x['from']}-{x['to']}" for x in fights if x.get("to_t", 0) >= lo and x.get("from_t", 0) <= hi) or "none",
                 LOW_EPISODES="; ".join(
                     f"{e.get('clock')} {e.get('hero', '')}, min HP {e.get('min_hp')}/{e.get('max')}, slots at start {e.get('slots_at_start')}, "
                     f"last press before {json.dumps(e.get('last_press_before') or {})}, pressed during {json.dumps(e.get('pressed_in') or [])}, "
                     f"outcome {e.get('outcome')}" for e in lows if _in(e.get("from"), lo, hi)) or "none",
                 PRESSES="; ".join(f"{p.get('clock')} {p.get('hero', '')} slot {p.get('slot')} {p.get('context')} HP {p.get('hp')}"
                                   for p in presses if _in(p.get("t"), lo, hi)) or "none")
        out.append(Piece("overview", f"overview_{nn}", game, fill("overview", f), [packet_dir / "notes" / f"overview_{nn}.md"]))

    out += _death_pieces(game, packet, common, deaths)

    # ults: one reader for the whole match, none if there were no ults
    if ults:
        f = dict(common, HEROES=heroes_line,
                 ULTS=", ".join(f"{u['id']} {u.get('outcome')} held {u.get('held_s')} s" for u in ults))
        out.append(Piece("ults", "ults", game, fill("ults", f), [packet_dir / "notes" / "ults.md"]))

    out.append(_writer(game, common, lessons, "every death, the whole match in overview sheets and every ult (the full read)"))
    return out


def _writer(game: Path, common: dict, lessons: Path, read: str) -> Piece:
    """The writer, once the readers are done."""
    packet_dir = game / "packet"
    f = dict(common, GAME=game, LESSONS=lessons, SESSION=game.parent, CONSTRAINTS=WRITER_CONSTRAINTS, READ=read)
    return Piece("writer", "writer", game, fill("writer", f), [packet_dir / "coaching.md", packet_dir / "notes" / "summary.md"])


def _death_pieces(game: Path, packet: dict, common: dict, deaths: list[dict]) -> list[Piece]:
    """Two deaths per reader, the facts block pasted verbatim."""
    out = []
    for i in range(0, len(deaths), DEATHS_PER_READER):
        pair = deaths[i:i + DEATHS_PER_READER]
        blocks = "\n\n".join(f"### {d['id']} at {d['clock']} on {d.get('hero', '?')}\n{(d.get('facts') or '').rstrip()}" for d in pair)
        f = dict(common, DEATHS=blocks, HERO_NOTES=_hero_notes(packet, {d.get("hero") for d in pair if d.get("hero")}))
        name = pair[0]["id"] if len(pair) == 1 else f"{pair[0]['id']}-{pair[-1]['id']}"
        out.append(Piece("deaths", name, game, fill("deaths", f), [game / "packet" / "notes" / f"{d['id']}.md" for d in pair]))
    return out


def _lean_pieces(game: Path, packet: dict, lessons: Path, common: dict, heroes_line: str, picks: dict) -> list[Piece]:
    """ADR 0012: the shortlisted deaths and ults, and the overview cells of the focus tests."""
    from .moments import KINDS, focus_tests, kinds_for
    packet_dir = game / "packet"
    ids = picks.get("ids") or set()
    out = _death_pieces(game, packet, common, [d for d in packet.get("deaths", []) if d["id"] in ids])

    # focus tests and clock-only moments: the first-pass sheets that cover them, 30 per reader
    focuses = focus_bullets(lessons)
    kinds = {k for f in focuses for k in kinds_for(f)}
    tests = [x for x in packet.get("focus_tests") or focus_tests(packet) if x["kind"] in kinds]
    moments = sorted(picks.get("clocks") or []) + sorted(
        k["t"] for k in packet.get("final_blows", []) if k["id"] in ids)
    spans = _windows([(x["from"] - TEST_PAD_S, x["to"] + TEST_PAD_S) for x in tests]
                     + [(t - MOMENT_PAD_S, t + MOMENT_PAD_S) for t in moments])
    sheets = [o for o in packet.get("overview", []) if not o.get("extra")
              and any(_secs(o["from"]) <= b and _secs(o["to"]) + 5 >= a for a, b in spans)]
    lows = {(e["from"], e["to"]): e for e in (packet.get("hud_game") or {}).get("low_episodes", [])}
    chunks = _chunks(sheets)
    for i, chunk in enumerate(chunks):
        nn = f"{i + 1:02d}"
        lo, hi = _secs(chunk[0]["from"]), _secs(chunk[-1]["to"]) + 5

        def line(x: dict) -> str:
            s = f"- {x['id']} {x['clock']}-{x['to_clock']} {KINDS[x['kind']]}: {x['what']}" + (f", ends in {x['death']}" if x.get("death") else "")
            e = lows.get((x["from"], x["to"])) if x["kind"] == "low" else None
            if e:
                s += (f"; slots at start {e.get('slots_at_start')}, last press before {json.dumps(e.get('last_press_before') or {})},"
                      f" pressed during {json.dumps(e.get('pressed_in') or [])}")
            return s
        mine = [x for x in tests if x["to"] + TEST_PAD_S >= lo and x["from"] - TEST_PAD_S <= hi]
        f = dict(common, NN=nn, HEROES=heroes_line, SHEETS=", ".join(o["file"] for o in chunk),
                 WINDOWS=", ".join(f"{_clock(a)}-{_clock(b)}" for a, b in spans if b >= lo and a <= hi),
                 TESTS="\n".join(line(x) for x in mine) or "- none in these sheets",
                 MOMENTS="\n".join(f"- {_clock(t)}" for t in moments if lo - MOMENT_PAD_S <= t <= hi + MOMENT_PAD_S) or "- none")
        out.append(Piece("tests", f"tests_{nn}", game, fill("tests", f), [packet_dir / "notes" / f"tests_{nn}.md"]))

    ults = [u for u in packet.get("ults", []) if u["id"] in ids]
    if ults:
        f = dict(common, HEROES=heroes_line,
                 ULTS=", ".join(f"{u['id']} {u.get('outcome')} held {u.get('held_s')} s" for u in ults))
        out.append(Piece("ults", "ults", game, fill("ults", f), [packet_dir / "notes" / "ults.md"]))

    read = (f"the triage's shortlisted deaths ({', '.join(sorted(i for i in ids if i.startswith('d'))) or 'none'}), "
            f"the overview cells of the focus tests ({len(tests)} tests in {len(sheets)} sheets)"
            + (f" and the shortlisted ults ({', '.join(u['id'] for u in ults)})" if ults else ""))
    out.append(_writer(game, common, lessons, read))
    return out


def _clock(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"
