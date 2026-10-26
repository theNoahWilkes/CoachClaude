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
MAX_ACTIVE = 3          # focus items at once (ADR 0014)
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
    if len(chosen) + bool(custom) > MAX_ACTIVE:
        raise ValueError(f"at most {MAX_ACTIVE} focus items at once (one or two work best)")
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


# The page's focus list (ADR 0014): every focus item with an active toggle. Active items are the
# entries under "## Current focus", inactive ones those under "## Focus options", and the
# pending proposal's options that neither holds yet are shown as new. At most MAX_ACTIVE are
# active; at MAX_ACTIVE the page suggests cutting down to one or two.


def _entries(section: str) -> tuple[list[str], list[list[str]]]:
    """A section's body -> (lines before the first entry, entries). An entry is a '- **wording**'
    line at column 0 plus the lines under it; lines inside <!-- --> comments are never entries."""
    head: list[str] = []
    entries: list[list[str]] = []
    in_comment = False
    for ln in section.split("\n"):
        starts = not in_comment and ln.startswith("- **")
        if "<!--" in ln and "-->" not in ln.split("<!--", 1)[1]:
            in_comment = True
        elif "-->" in ln:
            in_comment = False
        if starts:
            entries.append([ln])
        elif entries:
            entries[-1].append(ln)
        else:
            head.append(ln)
    for e in entries:
        while e and not e[-1].strip():
            e.pop()
    return head, entries


def _wording(entry: list[str]) -> str:
    m = re.match(r"- \*\*(.+?)\*\*", entry[0])
    return m.group(1).strip() if m else entry[0]


def _section_body(text: str, heading: str) -> str:
    span = _section_span(text, heading)
    return text[span[0]:span[1]].split("\n", 1)[1].strip("\n") if span else ""


def _join(head: list[str], entries: list[list[str]]) -> str:
    h = "\n".join(head).strip("\n")
    return "\n".join(x for x in [h] + ["\n".join(e) for e in entries] if x)


def _lessons() -> tuple[str, str]:
    lp = lessons_path()
    return _read(lp) if lp.exists() else ("# Lessons\n\n", "\n")


def _pending() -> list[dict]:
    pp = proposal_path()
    if not pp.exists():
        return []
    try:
        return parse_proposal(pp.read_text(encoding="utf-8"))[1]
    except ValueError:
        return []


def items() -> list[dict]:
    """Every focus item for the page: {wording, active, new, note}. Active first, then new ones
    from the coach's pending proposal, then the rest."""
    text, _ = _lessons()
    out, seen = [], set()
    for heading, active in ((CURRENT, True), (OPTIONS, False)):
        for e in _entries(_section_body(text, heading))[1]:
            w = _wording(e)
            if w.lower() not in seen:
                seen.add(w.lower())
                also = [m.group(1) for ln in e[1:] if (m := re.fullmatch(r"\s*\*\*(.+?)\*\*\s*", ln))]   # a second habit in the same item
                out.append({"wording": w, "also": also, "active": active, "new": False, "note": e[0].split("**", 2)[-1].strip()})
    new = [{"wording": o["wording"], "active": False, "new": True, "note": o["title"],
            "also": [ln.strip().strip("*") for ln in o["body"] if re.fullmatch(r"\s*\*\*(.+?)\*\*\s*", ln)],
            "evidence": [ln.strip() for ln in o["body"] if ln.strip() and not ln.strip().startswith("**")]}
           for o in _pending() if o["wording"].lower() not in seen]
    return [i for i in out if i["active"]] + new + [i for i in out if not i["active"]]


def _write(current: tuple[list[str], list[list[str]]], options: tuple[list[str], list[list[str]]], nl: str, text: str) -> None:
    text = _set_section(text, CURRENT, _join(*current))
    text = _set_section(text, OPTIONS, _join(*options) or OPTIONS_NOTE, after=CURRENT)
    lessons_path().write_text(text.replace("\n", nl), encoding="utf-8")
    pp = proposal_path()
    if pp.exists():          # its options are in the lessons file now
        pp.replace(pp.with_name("focus_proposal.last.md"))


def _load(today: str):
    """The lessons file's two focus sections, with the pending proposal's new options added to
    "Focus options" (evidence kept). `_write` then retires the proposal: once the player acts on
    the list, every option is in the lessons file."""
    text, nl = _lessons()
    cur = _entries(_section_body(text, CURRENT))
    opt = _entries(_section_body(text, OPTIONS))
    if not opt[0] and not opt[1]:
        opt = ([OPTIONS_NOTE], [])
    have = {_wording(e).lower() for e in cur[1] + opt[1]}
    for o in _pending():
        if o["wording"].lower() not in have:
            opt[1].append(_entry(o, f"Proposed {today} ({o['title']}).").split("\n"))
    return text, nl, cur, opt


def _restamp(entry: list[str], note: str) -> list[str]:
    return [f"- **{_wording(entry)}** {note}"] + entry[1:]


def set_active(wording: str, on: bool, today: str | None = None) -> str:
    """Turn one focus item on or off (moving it between "Current focus" and "Focus options")."""
    today = today or dt.date.today().isoformat()
    text, nl, cur, opt = _load(today)
    key = wording.strip().lower()
    src, dst = (opt, cur) if on else (cur, opt)
    hit = next((e for e in src[1] if _wording(e).lower() == key), None)
    if hit is None:
        if any(_wording(e).lower() == key for e in dst[1]):
            _write(cur, opt, nl, text)
            return f"Already {'active' if on else 'off'}."
        raise ValueError(f"no focus item {wording!r}")
    if on and len(cur[1]) >= MAX_ACTIVE:
        raise ValueError(f"{MAX_ACTIVE} focus items are already active. Turn one off first; one or two work best.")
    src[1].remove(hit)
    dst[1].append(_restamp(hit, f"Active since {today}." if on else f"Set aside {today}."))
    _write(cur, opt, nl, text)
    return f"{'On' if on else 'Off'}: {_wording(hit)}"


def add(wording: str, today: str | None = None) -> str:
    """The player's own focus item, active straight away."""
    today = today or dt.date.today().isoformat()
    w = wording.strip().rstrip(".").replace("**", "")
    if not w:
        raise ValueError("type the focus first")
    text, nl, cur, opt = _load(today)
    if any(_wording(e).lower() == w.lower() for e in cur[1] + opt[1]):
        _write(cur, opt, nl, text)
        return set_active(w, True, today)
    if len(cur[1]) >= MAX_ACTIVE:
        raise ValueError(f"{MAX_ACTIVE} focus items are already active. Turn one off first; one or two work best.")
    cur[1].append([f"- **{w}** Added {today}, in the player's own words."])
    _write(cur, opt, nl, text)
    return f"Added and on: {w}"
