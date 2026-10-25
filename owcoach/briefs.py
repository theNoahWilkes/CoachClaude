"""The pieces of a match and their briefs (ADR 0011).

A match is coached as pieces: one reader per two deaths, one per 5 minutes of overview sheets,
one for the ults, then one writer. Each piece's brief is a template from the skill
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
DONE = {"deaths": "## Read", "overview": "## Rejoins", "ults": "## Ults read"}   # a notes file's last section when complete
WRITER_CONSTRAINTS = (
    "Constraints: one game only, no session summary. Read the lessons file as usual but do NOT edit it "
    "(the summary process does that after every game is done): put what you would change under the "
    "'## Lessons' heading at the end of notes/summary.md, as step 4 says. Don't run shell commands; "
    "use Read, Glob and Grep for files."
)


@dataclass
class Piece:
    kind: str            # deaths | overview | ults | writer
    name: str            # d01-d02 | overview_01 | ults | writer
    game: Path
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
    return [p for p in nd.glob("*.md") if re.fullmatch(r"(d\d+|overview_\d+|ults)\.md", p.name)]


def write_all_notes(game: Path) -> Path:
    """Concatenate a game's reader notes into notes/all.md, in reading order, for the writer."""
    nd = game / "packet" / "notes"
    files = sorted(nd.glob("overview_*.md"), key=lambda p: p.name) + sorted(
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


def pieces(game: Path) -> list[Piece]:
    """Every piece of a match, writer last, with its brief filled in."""
    packet_dir = game / "packet"
    packet = json.loads((packet_dir / "packet.json").read_text(encoding="utf-8"))
    lessons = profile_dir() / "lessons.md"
    common = {"PACKET": packet_dir, "PLAYER": packet.get("player", "?"), "FOCUS": focus_wording(lessons), "SKILL_DIR": skill_dir()}
    heroes_line = ", ".join(f"{h['hero']} {h.get('seconds', 0) / 60:.0f} min" for h in packet.get("heroes", [])) or "unknown hero"
    out: list[Piece] = []

    # overview: 5 minutes of first-pass sheets per reader
    sheets = [o for o in packet.get("overview", []) if not o.get("extra")]
    fights = (packet.get("hud_game") or {}).get("fights", [])
    lows = (packet.get("hud_game") or {}).get("low_episodes", [])
    presses = (packet.get("hud_game") or {}).get("presses", [])
    deaths = packet.get("deaths", [])
    ults = packet.get("ults", [])
    chunks = [sheets[i:i + SHEETS_PER_READER] for i in range(0, len(sheets), SHEETS_PER_READER)]
    if len(chunks) > 1 and len(chunks[-1]) < SHEETS_PER_READER // 3:     # a short tail joins the window before it
        tail = chunks.pop()               # pop first: `chunks[-2] += chunks.pop()` reindexes after the pop
        chunks[-1] += tail
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

    # deaths: two per reader, the facts block pasted verbatim
    for i in range(0, len(deaths), DEATHS_PER_READER):
        pair = deaths[i:i + DEATHS_PER_READER]
        blocks = "\n\n".join(f"### {d['id']} at {d['clock']} on {d.get('hero', '?')}\n{(d.get('facts') or '').rstrip()}" for d in pair)
        f = dict(common, DEATHS=blocks, HERO_NOTES=_hero_notes(packet, {d.get("hero") for d in pair if d.get("hero")}))
        name = pair[0]["id"] if len(pair) == 1 else f"{pair[0]['id']}-{pair[-1]['id']}"
        out.append(Piece("deaths", name, game, fill("deaths", f), [packet_dir / "notes" / f"{d['id']}.md" for d in pair]))

    # ults: one reader for the whole match, none if there were no ults
    if ults:
        f = dict(common, HEROES=heroes_line,
                 ULTS=", ".join(f"{u['id']} {u.get('outcome')} held {u.get('held_s')} s" for u in ults))
        out.append(Piece("ults", "ults", game, fill("ults", f), [packet_dir / "notes" / "ults.md"]))

    # the writer, once the readers are done
    f = dict(common, GAME=game, LESSONS=lessons, SESSION=game.parent, CONSTRAINTS=WRITER_CONSTRAINTS)
    out.append(Piece("writer", "writer", game, fill("writer", f), [packet_dir / "coaching.md", packet_dir / "notes" / "summary.md"]))
    return out
