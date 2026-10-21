"""`owcoach migrate`: move an old layout into the library / profile the config names.

Old (until 2026-10-17): sessions in <captures>/owcoach/<session>/, cache in ~/.cache/owcoach/<stem>/,
profile in ~/.owcoach/. Everything is moved, nothing deleted; then the paths stored inside the
data are rewritten: session.json matches[].dir (absolute -> folder name), history.sqlite packet
(absolute -> relative to the library), packet.json hero_notes (absolute -> relative to the profile).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from .config import library, profile_dir, relpath

SESSION_RE = r"\d{4}\.\d{2}\.\d{2} - "


def plan(old_root: Path | None, old_cache: Path | None, old_profile: Path | None) -> list[tuple[str, Path, Path]]:
    """(kind, from, to) for every move."""
    moves = []
    if old_root and old_root.is_dir():
        import re
        for d in sorted(old_root.iterdir()):
            if d.is_dir() and re.match(SESSION_RE, d.name):
                moves.append(("session", d, library() / d.name))
    if old_cache and old_cache.is_dir():
        for d in sorted(old_cache.iterdir()):
            if d.is_dir() and (d / "scan.json").exists():
                moves.append(("cache", d, library() / ".cache" / d.name))
    if old_profile and old_profile.is_dir() and old_profile.resolve() != profile_dir().resolve():
        moves.append(("profile", old_profile, profile_dir()))
    return moves


def rewrite(log=print) -> dict:
    """Make every stored path relative (idempotent; safe to run on an already-clean library)."""
    n = {"session.json": 0, "packet.json": 0, "history": 0}
    for sj in library().glob("*/session.json"):
        sess = json.loads(sj.read_text(encoding="utf-8"))
        changed = False
        for m in sess.get("matches", []):
            d = m.get("dir")
            if d and ("/" in d or "\\" in d):
                m["dir"] = Path(d).name
                changed = True
        if changed:
            sj.write_text(json.dumps(sess, indent=1), encoding="utf-8")
            n["session.json"] += 1
    for pj in library().glob("*/m[0-9]*/packet/packet.json"):
        raw = pj.read_text(encoding="utf-8")
        pk = json.loads(raw)
        hn = pk.get("hero_notes") or {}
        new = {h: (f"heroes/{Path(p).name}" if ("/" in p or "\\" in p) else p) for h, p in hn.items()}
        if new != hn:
            pk["hero_notes"] = new
            pj.write_text(json.dumps(pk, indent=1, ensure_ascii=False), encoding="utf-8")
            slim = pj.with_name("packet_slim.json")
            if slim.exists():
                sp = json.loads(slim.read_text(encoding="utf-8"))
                sp["hero_notes"] = new
                slim.write_text(json.dumps(sp, indent=1, ensure_ascii=False), encoding="utf-8")
            n["packet.json"] += 1
    db = profile_dir() / "history.sqlite"
    if db.exists():
        with sqlite3.connect(db) as con:
            rows = con.execute("SELECT session, n, packet FROM games").fetchall()
            for session, k, p in rows:
                if p and Path(p).is_absolute():
                    # the old absolute path may no longer exist; rebuild from its tail
                    parts = Path(p).parts
                    i = next((j for j in range(len(parts)) if parts[j].endswith("packet.json")), None)
                    tail = Path(*parts[-4:]) if i is not None else None     # <session>/<game>/packet/packet.json
                    newp = relpath(library() / tail, library()) if tail and (library() / tail).exists() else p
                    if newp != p:
                        con.execute("UPDATE games SET packet=? WHERE session=? AND n=?", (newp, session, k))
                        n["history"] += 1
    log(f"rewrote paths: {n}")
    return n


def migrate(old_root: Path | None, old_cache: Path | None, old_profile: Path | None, dry_run: bool, log=print) -> int:
    def empty(d: Path) -> bool:
        return d.is_dir() and not any(d.iterdir())

    moves = plan(old_root, old_cache, old_profile)
    for kind, src, dst in moves:
        log(f"  {kind:8s} {src}  ->  {dst}" + ("  (exists, skipped)" if dst.exists() and not empty(dst) else ""))
    if dry_run:
        log(f"dry run: {len(moves)} moves, nothing done")
        return len(moves)
    library().mkdir(parents=True, exist_ok=True)
    (library() / ".cache").mkdir(exist_ok=True)
    for kind, src, dst in moves:
        if empty(dst):              # setup creates the empty folders first
            dst.rmdir()
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    rewrite(log)
    return len(moves)
