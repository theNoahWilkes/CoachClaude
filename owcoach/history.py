"""Per-game stat history (SQLite in the profile dir) and trends.

Every `owcoach packet` run upserts one row per game. `owcoach trend` compares the most recent
games with the player's earlier ones, per 10 minutes of match clock:

  deaths, time dead (% of the match), healing, damage (+ eliminations, assists, mitigation)

Rates over a set of games are time-weighted: sum(stat) * 600 / sum(clock). A change is called
meaningful when the recent rate differs from the baseline by at least MIN_REL and by at least
Z_MIN standard errors (baseline game-to-game spread / sqrt(recent games)), with at least
MIN_BASE baseline games. Otherwise it's reported as normal variation or "not enough history".
Hero and role mix move these numbers a lot, so trends can be filtered by role or hero.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .config import library, relpath

MIN_BASE = 5
MIN_REL = 0.10
Z_MIN = 2.0
# metric -> (label, higher is better)
METRICS = {"D": ("deaths", False), "dead_pct": ("time dead %", False), "H": ("healing", True),
           "DMG": ("damage", True), "E": ("eliminations", True), "A": ("assists", True), "MIT": ("mitigation", True)}

SCHEMA = """CREATE TABLE IF NOT EXISTS games (
  session TEXT, n INTEGER, played TEXT, map TEXT, mode TEXT, queue TEXT, result TEXT,
  hero_main TEXT, hero_share REAL, role TEXT, clock_s REAL,
  E INTEGER, A INTEGER, D INTEGER, DMG INTEGER, H INTEGER, MIT INTEGER,
  time_dead_s REAL, deaths_feed INTEGER, death_flags TEXT, packet TEXT,
  PRIMARY KEY (session, n))"""


def db() -> sqlite3.Connection:
    from .profile import profile_dir
    con = sqlite3.connect(profile_dir() / "history.sqlite")
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def _played(session: str, start_s: float) -> str | None:
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2}) - (\d{2})\.(\d{2})\.(\d{2})", session)
    if not m:
        return None
    t0 = datetime(*map(int, m.groups()))
    return (t0 + timedelta(seconds=start_s)).isoformat(timespec="seconds")


def record(packet: dict, n: int, packet_path: Path) -> None:
    g, st = packet["game"], packet.get("stats") or {}
    me = st.get("player") or {}
    heroes = packet.get("heroes") or []
    secs: dict[str, float] = {}
    for h in heroes:
        secs[h["hero"]] = secs.get(h["hero"], 0.0) + h["seconds"]
    main = max(secs.items(), key=lambda kv: kv[1]) if secs else None
    main = main and {"hero": main[0], "seconds": main[1]}
    total = sum(secs.values()) or 1
    with db() as con:
        con.execute("INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            g["session"], n, _played(g["session"], g["session_start_s"]), g["map"], g["mode"], g["queue"], g["result"],
            main and main["hero"], main and round(main["seconds"] / total, 2), g.get("role"), st.get("clock_s"),
            me.get("E"), me.get("A"), me.get("D"), me.get("DMG"), me.get("H"), me.get("MIT"),
            st.get("time_dead_s"), packet["counts"]["deaths"], json.dumps(packet["counts"].get("death_flags", {})),
            relpath(packet_path, library())))       # relative to the library, so it can move


def _rate(rows: list, k: str) -> float | None:
    if k == "dead_pct":
        rs = [r for r in rows if r["time_dead_s"] is not None and r["clock_s"]]
        return 100 * sum(r["time_dead_s"] for r in rs) / sum(r["clock_s"] for r in rs) if rs else None
    rs = [r for r in rows if r[k] is not None and r["clock_s"]]
    return sum(r[k] for r in rs) * 600 / sum(r["clock_s"] for r in rs) if rs else None


def _per_game(rows: list, k: str) -> list[float]:
    if k == "dead_pct":
        return [100 * r["time_dead_s"] / r["clock_s"] for r in rows if r["time_dead_s"] is not None and r["clock_s"]]
    return [r[k] * 600 / r["clock_s"] for r in rows if r[k] is not None and r["clock_s"]]


def trend(recent: str = "session", last: int | None = None, role: str | None = None,
          hero: str | None = None) -> dict:
    """recent = "session" (the latest session) or "games" (the last `last` games)."""
    with db() as con:
        rows = con.execute("SELECT * FROM games WHERE clock_s IS NOT NULL ORDER BY played").fetchall()
    if role:
        rows = [r for r in rows if r["role"] == role]
    if hero:
        rows = [r for r in rows if (r["hero_main"] or "").lower() == hero.lower()]
    if not rows:
        return {"games": 0}
    if recent == "games":
        k = last or 3
        rec, base = rows[-k:], rows[:-k]
    else:
        sess = rows[-1]["session"]
        rec, base = [r for r in rows if r["session"] == sess], [r for r in rows if r["session"] != sess]
    out = {"filter": {"role": role, "hero": hero}, "recent_games": len(rec), "baseline_games": len(base),
           "recent": [dict(map=r["map"], result=r["result"], hero=r["hero_main"], clock=r["clock_s"]) for r in rec],
           "metrics": {}}
    for k, (label, up_good) in METRICS.items():
        rr, rb = _rate(rec, k), _rate(base, k)
        m = {"label": label, "per": "% of match" if k == "dead_pct" else "per 10 min",
             "recent": rr and round(rr, 1), "baseline": rb and round(rb, 1)}
        pg = _per_game(base, k)
        if rr is None or rb is None or len(pg) < MIN_BASE:
            m["verdict"] = "not enough history"
        else:
            sd = float(np.std(pg, ddof=1)) or 1e-6
            z = (rr - rb) / (sd / np.sqrt(len(rec)))
            rel = (rr - rb) / rb if rb else 0.0
            m |= {"change_pct": round(100 * rel, 1), "z": round(float(z), 2)}
            if abs(z) >= Z_MIN and abs(rel) >= MIN_REL:
                m["verdict"] = "better" if (rr > rb) == up_good else "worse"
            else:
                m["verdict"] = "normal variation"
        out["metrics"][k] = m
    # per-hero rates over all games, for context on hero mix
    out["by_hero"] = {}
    for h in sorted({r["hero_main"] for r in rows if r["hero_main"]}):
        hr = [r for r in rows if r["hero_main"] == h]
        out["by_hero"][h] = {"games": len(hr), **{k: (lambda v: v and round(v, 1))(_rate(hr, k)) for k in ("D", "dead_pct", "H", "DMG")}}
    return out


def format_trend(t: dict) -> str:
    if not t.get("games", 1):
        return "no games in history"
    f = t["filter"]
    head = f"recent {t['recent_games']} game(s) vs baseline {t['baseline_games']}" + \
        (f"  [role={f['role']}]" if f["role"] else "") + (f"  [hero={f['hero']}]" if f["hero"] else "")
    lines = [head, f"{'':16s}{'recent':>9s}{'baseline':>10s}{'change':>9s}  verdict"]
    for k, m in t["metrics"].items():
        ch = f"{m['change_pct']:+.0f}%" if "change_pct" in m else ""
        fmt = (lambda v: "-" if v is None else f"{v:,.1f}")
        lines.append(f"{m['label']:16s}{fmt(m['recent']):>9s}{fmt(m['baseline']):>10s}{ch:>9s}  {m['verdict']}")
    lines.append("(per 10 min of match clock; time dead as % of the match)")
    lines.append("by hero (all games): " + "; ".join(
        f"{h} x{v['games']}: D {v['D']}, dead {v['dead_pct']}%, H {v['H']:,}, DMG {v['DMG']:,}"
        for h, v in t["by_hero"].items() if v["H"] is not None and v["DMG"] is not None))
    return "\n".join(lines)
