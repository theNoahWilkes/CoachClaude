"""The coaching focus is the player's to choose. The coach proposes; `owcoach focus` applies.

At the end of a session the coach writes <profile>/focus_proposal.md: numbered options, each a
habit with a trigger in bold and the evidence under it (option 1 is always "keep the current
focus", with its grades). The player picks with `owcoach focus 2` (or `owcoach focus 1 4` for
two, or `owcoach focus --set "their own wording"`), and this module rewrites the lessons file:
the chosen options become "## Current focus", the rest become "## Focus options", verbatim. The
coach grades the focus every game but never edits its wording; a change goes through a proposal.

Why: the coach kept sharpening the focus on its own between sessions (2026-10-14, -15, -16), so
the player was being graded against wording they hadn't agreed to. Noah: "let the user and the
agent agree on what the next session's theme will be."

Proposal shape (parsed here; the skill's references/focus-proposal.md says how to write one):

    # Focus proposal, 2026-10-16
    <intro lines>
    ## 1. Keep: <title>
    **<trigger and action, the wording that goes in the lessons file>**
    - Evidence: ...
    ## 2. <title>
    **...**
    - ...
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .config import profile_dir

CURRENT = "## Current focus"
OPTIONS = "## Focus options"
OPTIONS_NOTE = ("<!-- proposed by the coach, not chosen; evidence kept so the next proposal can "
                "build on it -->")


def proposal_path() -> Path:
    return profile_dir() / "focus_proposal.md"


def lessons_path() -> Path:
    return profile_dir() / "lessons.md"


def _read(p: Path) -> tuple[str, str]:
    raw = p.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), nl


def parse_proposal(text: str) -> tuple[str, list[dict]]:
    """-> (label, options). An option: number, title, wording (the first bold line), body (the
    lines after the wording, verbatim, stripped of blank ends)."""
    text = text.replace("\r\n", "\n")
    m = re.search(r"^# (.+)$", text, re.M)
    label = m.group(1).strip() if m else "focus proposal"
    parts = re.split(r"^## (\d+)\.\s*", text, flags=re.M)
    options = []
    for i in range(1, len(parts), 2):
        n, chunk = int(parts[i]), parts[i + 1]
        title, _, body = chunk.partition("\n")
        lines = body.rstrip().split("\n")
        wording, rest = "", lines
        for j, ln in enumerate(lines):
            if ln.strip():
                w = re.fullmatch(r"\*\*(.+?)\*\*\s*", ln.strip())
                if not w:
                    raise ValueError(f"option {n} ({title.strip()}): the first line must be the bold wording")
                wording, rest = w.group(1).strip(), lines[j + 1:]
                break
        if not wording:
            raise ValueError(f"option {n} ({title.strip()}): no wording")
        while rest and not rest[0].strip():
            rest.pop(0)
        options.append({"n": n, "title": title.strip(), "wording": wording, "body": rest})
    if not options:
        raise ValueError("no '## N. title' options in the proposal")
    return label, options


def _entry(o: dict, head: str) -> str:
    lines = [f"- **{o['wording']}** {head}"]
    for ln in o["body"]:
        lines.append(("  " + ln.rstrip()) if ln.strip() else "")
    return "\n".join(lines).rstrip()


def _section_span(text: str, heading: str) -> tuple[int, int] | None:
    m = re.search(rf"^{re.escape(heading)}\s*$", text, re.M)
    if not m:
        return None
    nxt = re.search(r"^## ", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    return m.start(), end


def _set_section(text: str, heading: str, body: str, after: str | None = None) -> str:
    block = f"{heading}\n{body.rstrip()}\n\n"
    span = _section_span(text, heading)
    if span:
        return text[:span[0]] + block + text[span[1]:].lstrip("\n")
    if after and (prev := _section_span(text, after)):
        return text[:prev[1]].rstrip("\n") + "\n\n" + block + text[prev[1]:].lstrip("\n")
    first = re.search(r"^## ", text, re.M)
    at = first.start() if first else len(text)
    return text[:at].rstrip("\n") + "\n\n" + block + text[at:]


def current_focus(text: str) -> str:
    span = _section_span(text.replace("\r\n", "\n"), CURRENT)
    return text[span[0]:span[1]].strip() if span else ""


def apply(choices: list[int], custom: str | None = None, today: str | None = None) -> str:
    """Rewrite the lessons file from the proposal and the player's choice; returns a summary."""
    today = today or dt.date.today().isoformat()
    pp, lp = proposal_path(), lessons_path()
    _, options = ("", []) if not pp.exists() else parse_proposal(pp.read_text(encoding="utf-8"))
    if not pp.exists() and not custom:
        raise FileNotFoundError(f"no proposal at {pp}: the coach writes one at the end of a session")
    by_n = {o["n"]: o for o in options}
    unknown = [n for n in choices if n not in by_n]
    if unknown:
        raise ValueError(f"no option {unknown} in the proposal (it has {sorted(by_n)})")
    if not choices and not custom:
        raise ValueError("pick at least one option number, or --set your own wording")
    chosen = [by_n[n] for n in choices]
    if custom:
        chosen.append({"n": 0, "title": "player's own", "wording": custom.strip().rstrip("."), "body": []})
    heads = [f"Chosen {today}" + (f" (option {o['n']} of the proposal: {o['title']})." if o["n"] else ", in the player's own words.")
             for o in chosen]
    current = "\n".join(_entry(o, h) for o, h in zip(chosen, heads))
    rest = [o for o in options if o["n"] not in choices]
    opts = OPTIONS_NOTE + "\n" + "\n".join(_entry(o, f"Proposed {today}, not chosen ({o['title']}).") for o in rest) if rest else OPTIONS_NOTE
    text, nl = _read(lp) if lp.exists() else ("# Lessons\n\n", "\n")
    text = _set_section(text, CURRENT, current)
    text = _set_section(text, OPTIONS, opts, after=CURRENT)
    lp.write_text(text.replace("\n", nl), encoding="utf-8")
    if pp.exists():
        pp.replace(pp.with_name("focus_proposal.last.md"))
    return (f"focus set ({len(chosen)}): " + "; ".join(o["wording"] for o in chosen)
            + f"\n{len(rest)} option(s) kept under '{OPTIONS[3:]}' in {lp}"
            + (f"\nproposal moved to {pp.with_name('focus_proposal.last.md')}" if options else ""))


def show() -> str:
    out = []
    lp, pp = lessons_path(), proposal_path()
    if lp.exists():
        out.append(current_focus(lp.read_text(encoding="utf-8")) or "(no current focus in the lessons file)")
    if pp.exists():
        label, options = parse_proposal(pp.read_text(encoding="utf-8"))
        out.append(f"\nPending: {label} ({pp})")
        for o in options:
            out.append(f"  {o['n']}. {o['title']}\n     {o['wording']}")
        out.append("\nPick with: owcoach focus N [N]   or   owcoach focus --set \"your wording\"")
    else:
        out.append("\nNo proposal pending.")
    return "\n".join(out)
