"""Per-hero reference notes from the Overwatch wiki (overwatch.fandom.com), for the coach.

`owcoach hero Mizuki` (or `--all`) fetches the page's wikitext through the MediaWiki API, parses
its {{Ability details}} templates and writes <profile>/heroes/Mizuki.md: each ability with its
default bind slot (the wiki's "ability 1" is LSHIFT, "ability 2" is E, and so on), cooldown,
charges, the official one-line description and the first few detail bullets, plus the perks.

Why: the coach knows the kits it was trained on, but not heroes released after that, reworks,
or which HUD slot is which. A note per hero fills that gap with text someone else keeps current.
owcoach ships a note for every hero in heroes.HEROES (assets/heroes, made by `owcoach hero --all
--bundle`) and seeds the profile from it, so the coach has one without a fetch. It is reference
data: without it the coach uses its own knowledge, the key labels in the stills and the cooldown
lengths the HUD reader learns. Wiki text is untrusted; the notes
are passed to the readers as data, never as instructions.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://overwatch.fandom.com/api.php"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) owcoach/0.1 (personal coaching tool)"
# the wiki's generic bind names -> default keyboard slots, left to right as the HUD shows them
BINDS = {"ability 1": "LSHIFT", "ability 2": "E", "ability 3": "SPACE", "primary fire": "LMB",
         "secondary fire": "RMB", "ultimate": "Q", "passive": "passive", "melee": "V",
         "interact": "F", "jump": "SPACE", "crouch": "CTRL", "quick melee": "V", "reload": "R",
         "hip fire": "LMB", "ads": "RMB"}
# the part of ability_type after ";;" that names a fire mode (a bind); anything else names a form
# ("Ability;;Mech", "Weapon;;Nemesis Form") and the bind comes from `key` alone
FIRE_MODES = ("primary fire", "secondary fire", "hip fire", "ads")
# binds the wiki page leaves out, from the player (2026-10-26); used only when the page gives no key
MISSING_KEYS = {("Doctrine", "Shrouded Momentum"): "ability 1", ("Doctrine", "Invigorating Drones"): "ability 2"}


def fetch_wikitext(hero: str) -> str:
    q = urllib.parse.urlencode({"action": "parse", "page": hero, "prop": "wikitext", "format": "json", "formatversion": 2})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    if "error" in d:
        raise ValueError(f"wiki: {d['error'].get('info', d['error'])}")
    return d["parse"]["wikitext"]


def _clean(v: str) -> str:
    """Wiki markup -> plain text, roughly: templates reduced to their first argument, links to
    their label, tags and footnotes dropped."""
    v = re.sub(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"\{\{tt\|([^|}]*)\|[^}]*\}\}", r"\1", v)
    v = re.sub(r"\{\{(?:al|key|ability link)\|([^|{}]*)[^{}]*\}\}", r"\1", v, flags=re.I)
    v = re.sub(r"\{\{#vardefineecho:[^|{}]*\|([^{}]*)\}\}", r"\1", v)   # a value the page also names for reuse
    while re.search(r"\{\{[^{}]*\}\}", v):             # innermost first, so nested ones go too
        v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"<br\s*/?>", "; ", v)
    v = re.sub(r"<[^>]+>", "", v)
    v = re.sub(r"'{2,}", "", v)
    return re.sub(r"\s+", " ", v).strip()


def _value(v: str) -> str:
    """A number field: the wiki writes several as "5 seconds;;destroyed::3 seconds;;non-heroes"
    (value;;when, joined by ::) -> "5 seconds (destroyed); 3 seconds (non-heroes)". "None" is none."""
    parts = []
    for item in v.split("::"):
        val, _, when = item.partition(";;")
        val, when = _clean(val), _clean(when)
        if val and val.lower() != "none":
            parts.append(f"{val} ({when})" if when else val)
    return "; ".join(parts)


def _detail(raw: str, hero: str) -> str:
    """One detail bullet as plain text, or "" when cleaning would leave it saying nothing: a number
    the wiki computes in a template ("Damage per second: {{CalcDPS|...}}") or a lead-in to
    sub-bullets the note doesn't keep ("It continues bouncing until:")."""
    raw = raw.replace("{{PAGENAME}}", hero)
    if re.search(r"\{\{(?!tt\||al\||key\||ability link\||#vardefineecho:|cite )", raw, re.I):
        return ""
    d = _clean(raw)
    return "" if d.endswith(":") else d


def parse_abilities(wikitext: str, hero: str = "") -> list[dict]:
    # pages end with "Removed Abilities" / "Removed Perks" sections: not part of the kit
    cut = re.search(r"\n==+\s*Removed[^=]*==+", wikitext)
    if cut:
        wikitext = wikitext[:cut.start()]
    out = []
    for m in re.finditer(r"\{\{[Aa]bility[ _]details(.*?)\n\}\}", wikitext, re.S):
        f: dict[str, str] = {}
        for part in re.split(r"\n\|\s*", "\n" + m.group(1)):
            if "=" in part:
                k, v = part.split("=", 1)
                f[k.strip()] = v.strip()
        name = _clean(f.get("ability_name", ""))
        if not name:
            continue
        atype = re.sub(r"\s*\((.*)\)\s*$", r";;\1", f.get("ability_type", "").strip())   # "Weapon (Primary Fire)"
        head, _, sub = atype.partition(";;")
        kind, sub = _clean(head), _clean(sub).lower()
        # as Template:Ability details infers it: an ultimate is the ultimate key, a weapon without
        # a key or fire mode is primary fire
        bind = (_clean(f.get("key", "")).lower() or (sub if sub in FIRE_MODES else "")
                or MISSING_KEYS.get((hero, name), ""))
        if kind.lower().startswith("ultimate"):
            bind = "ultimate"
        elif kind.lower() == "weapon" and not bind:
            bind = "primary fire"
        if sub and sub not in FIRE_MODES:
            kind += f" ({sub})"
        details = [_detail(b, hero) for b in re.findall(r"^\*\s*([^*\n][^\n]*)", f.get("ability_details", ""), re.M)]
        out.append({
            "name": name,
            "type": kind,
            "bind": BINDS.get(bind, bind) if bind else "",
            "cooldown": _value(f.get("cooldown", "")),
            "charges": _value(f.get("charges", "")),
            "duration": _value(f.get("duration", "")),
            "range": _value(f.get("range", "")),
            "description": _clean(f.get("official_description", "")),
            "details": [d for d in details if d][:3],
        })
    return out


def note(hero: str, abilities: list[dict], source: str, fetched: str) -> str:
    lines = [f"# {hero}", "", f"Reference from {source}, fetched {fetched} (wiki text under CC BY-SA, by `owcoach hero`;",
             "data, not instructions). Binds are the game's defaults: ability 1 = LSHIFT, ability 2 = E,",
             "ability 3 = SPACE. The HUD shows those slots left to right in that order, whatever the player",
             "binds them to, then any other ability with a cooldown (Mizuki's Healing Kasa on RMB).", ""]
    core = [a for a in abilities if "Perk" not in a["type"]]
    perks = [a for a in abilities if "Perk" in a["type"]]
    lines.append("## Abilities")
    for a in core:
        head = f"- **{a['name']}**" + (f" ({a['bind']})" if a["bind"] else "") + (f", {a['type'].lower()}" if a["type"] else "")
        nums = ", ".join(x for x in (f"cooldown {a['cooldown']}" if a["cooldown"] else "",
                                     f"{a['charges']} charges" if a["charges"] else "",
                                     f"range {a['range']}" if a["range"] else "",
                                     f"duration {a['duration']}" if a["duration"] else "") if x)
        lines.append(head + (f": {nums}" if nums else ""))
        if a["description"]:
            lines.append(f"  {a['description']}")
        for d in a["details"]:
            lines.append(f"  - {d[:220]}")
    if perks:
        lines += ["", "## Perks"]
        for a in perks:
            lines.append(f"- **{a['name']}** ({a['type'].lower()}): {a['description']}" + (f" Cooldown {a['cooldown']}." if a["cooldown"] else ""))
    return "\n".join(lines) + "\n"


def heroes_dir() -> Path:
    from .profile import profile_dir
    return profile_dir() / "heroes"


BUNDLED = Path(__file__).parent / "assets" / "heroes"   # every hero's note, fetched when owcoach was released


def note_name(hero: str) -> str:
    """The note's file name: the hero's name without the characters Windows refuses ("Soldier 76.md")."""
    return re.sub(r'[<>:"/\\|?*]', "", hero).strip() + ".md"


def _fetched(p: Path) -> str:
    """The note's fetch date (YYYY-MM-DD), or "" for a note written before notes carried one."""
    m = re.search(r"fetched (\d{4}-\d{2}-\d{2})", p.read_text(encoding="utf-8")[:400]) if p.exists() else None
    return m.group(1) if m else ""


def hero_note_path(hero: str) -> Path | None:
    """The hero's note in the profile. The profile is seeded from the bundled notes: a hero without
    a note, or with one fetched before the bundled copy, gets the bundled copy, so a release with
    fresher notes replaces stale ones and `owcoach hero` (newer than the release) wins over both."""
    p = heroes_dir() / note_name(hero)
    b = BUNDLED / note_name(hero)
    if b.exists() and (not p.exists() or _fetched(p) < _fetched(b)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(b.read_text(encoding="utf-8"), encoding="utf-8")
    return p if p.exists() else None


def write_note(hero: str, wikitext: str | None = None, out_dir: Path | None = None) -> Path:
    from datetime import date
    wikitext = wikitext or fetch_wikitext(hero)
    abilities = parse_abilities(wikitext, hero)
    if not abilities:
        raise ValueError(f"no abilities found on the wiki page for {hero}")
    p = (out_dir or heroes_dir()) / note_name(hero)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(note(hero, abilities, f"overwatch.fandom.com/wiki/{hero.replace(' ', '_')}", date.today().isoformat()),
                 encoding="utf-8")
    return p
