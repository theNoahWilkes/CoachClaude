"""owcoach CLI.

  owcoach setup   [--captures DIR] [--library DIR] [--from REC.mp4]   once: tools, config, profile
  owcoach new                                    recordings in the capture folders not in the library yet
  owcoach run     REC.mp4|STEM                   every local stage: scan segment events hud split packet
  owcoach coach   [SESSION ...] [--new]          per-game claude processes + summary (the paid part)
  owcoach config  [KEY]                          the resolved paths
  owcoach migrate --from OLD_DIR                 move the pre-2026-10-17 layout into the library

  owcoach init    CACHE [--name NAME]            onboarding: learn the player's nameplate -> profile
  owcoach scan    SESSION.mp4 [--cache DIR]      decode once -> thumbnail cache
  owcoach sheet   CACHE [--every N]              contact sheets for eyeballing
  owcoach segment CACHE                          classify frames -> matches.json
  owcoach events  CACHE                          kill feed -> deaths / final blows per match
  owcoach hud     CACHE                          HP and ability states at 2 fps
  owcoach split   CACHE [--out DIR]              cut matches out with ffmpeg -c copy
  owcoach packet  CACHE [--game N]               per-game coaching packet (stills + packet.json)
  owcoach digest  SESSION                        every match's deaths, chains and focus tests as text
  owcoach trend   [--games N] [--role R] [--hero H]  per-10 stats: recent vs baseline

CACHE may be the cache folder, the recording, or its bare stem (resolved through the library).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .config import cache_for, resolve_cache


def default_cache(video: Path) -> Path:
    return cache_for(video)


def cmd_scan(a):
    from .scan import scan
    video = Path(a.video)
    cache = Path(a.cache) if a.cache else default_cache(video)
    t0 = time.time()
    idx = scan(video, cache, mode=a.mode, width=a.width, chunk=a.chunk,
               budget=a.budget, jobs=a.jobs, quiet=a.quiet, hwaccel=a.hwaccel)
    if idx:
        print(f"scan complete: {len(idx['frames'])} frames ({time.time() - t0:.0f}s this run) -> {cache}")
    return cache


def cmd_sheet(a):
    from .sheet import contact_sheets
    cache = resolve_cache(a.cache)
    labels = None
    if a.labels and (cache / "states.json").exists():
        st = json.loads((cache / "states.json").read_text())
        labels = st["labels"]
    out = Path(a.out) if a.out else cache / "sheets"
    paths = contact_sheets(cache, out, every=a.every, start=a.start, end=a.end,
                           labels=labels, tile_w=a.tile)
    for p in paths:
        print(p)


def cmd_segment(a):
    from .segment import segment
    cache = resolve_cache(a.cache)
    res = segment(cache)
    for m in res["matches"]:
        print(f"  match {m['n']:2d}  {m['start_hms']} -> {m['end_hms']}  "
              f"({m['duration'] / 60:4.1f} min)  {m.get('result') or '?':8s} {(m.get('queue') or '?')[:4]:4s} "
              f"{(m.get('mode') or '?'):8s} {(m.get('map') or '?'):20s} "
              f"tab x{len(m['tab_times'])}  {' '.join(m['flags'])}")
        for s in m.get("heroes", []):
            print(f"      {s['from'] - m['start']:6.0f}s +{s['seconds']:5.0f}s  {s['hero'] or '?':12s} "
                  f"{s['role'] or '':8s} portrait x{s['portrait_frames']:<4d} tab x{s['tab_votes']}"
                  + (f" (conflicts {s['tab_conflicts']})" if s["tab_conflicts"] else ""))
        if m.get("views"):
            print(f"      + {len(m['views'])} kill-cam/spectate stretches")
    print(f"{len(res['matches'])} matches -> {cache / 'matches.json'}")


def cmd_init(a):
    from .profile import init, profile_dir
    prof = init(resolve_cache(a.cache), name=a.name, assume_yes=a.yes)
    print(f"profile for {prof['name']} -> {profile_dir()}")


def cmd_events(a):
    from .events import events
    cache = resolve_cache(a.cache)
    t0 = time.time()
    res = events(cache)
    sess = {m["n"]: m for m in json.loads((cache / "matches.json").read_text())["matches"]}
    for e in res["matches"]:
        m = sess[e["n"]]
        print(f"  match {e['n']:2d}  {(m.get('map') or '?'):22s} deaths {len(e['deaths']):2d}  "
              f"final blows {len(e['final_blows']):2d}  deployables {len(e['deployables_destroyed'])}")
    print(f"events ({time.time() - t0:.0f}s) -> {cache / 'events.json'}")


def cmd_split(a):
    from .split import split
    cache = resolve_cache(a.cache)
    for p in split(cache, Path(a.out) if a.out else None, pad=a.pad, dry_run=a.dry_run,
                   cut=a.cut):
        print(p)


def cmd_packet(a):
    from .packet import packets
    t0 = time.time()
    for p in packets(resolve_cache(a.cache), Path(a.out) if a.out else None, only=a.game, jobs=a.jobs, refresh=a.refresh):
        pk = json.loads((p / "packet.json").read_text(encoding="utf-8"))
        n = len(list((p / "frames").glob("*.jpg")))
        print(f"  {p.parent.name:42s} deaths {pk['counts']['deaths']:2d}  ults {pk['counts']['ults']}  stills {n:3d}")
    print(f"packets ({time.time() - t0:.0f}s)")


def cmd_hero(a):
    from .herowiki import write_note
    for h in a.hero:
        try:
            print(f"  {h}: {write_note(h.replace('_', ' '))}")
        except Exception as e:      # the wiki is optional; say why and go on
            print(f"  {h}: {e}")


def cmd_hud(a):
    from .hudscan import hudscan
    t0 = time.time()
    d = hudscan(resolve_cache(a.cache), jobs=a.jobs)
    ok = sum(1 for r in d["rows"] if r["hp"] is not None)
    print(f"hud: {len(d['rows'])} own-view frames, HP read on {ok} ({time.time() - t0:.0f}s) -> {resolve_cache(a.cache) / 'hud.json'}")


def cmd_focus(a):
    import sys
    from .focus import apply, show
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        picks = [int(x) for x in ",".join(a.n).replace(" ", ",").split(",") if x]
        print(apply(picks, a.set) if (picks or a.set) else show())
    except (ValueError, FileNotFoundError) as e:
        raise SystemExit(f"focus: {e}")


def cmd_notes(a):
    """Concatenate a game's reader notes into notes/all.md, in reading order, for the writer
    (the driver does this itself; the command is for a hand-run writer)."""
    from .briefs import write_all_notes
    out = write_all_notes(Path(a.game))
    print(f"notes -> {out}")

def cmd_digest(a):
    """Write <session>/digest.md: every match's deaths, chains, ults, fights and focus tests as
    text, for the triage (ADR 0012). Free: it reads the packets, nothing is sent to Claude."""
    import sys
    from .briefs import focus_bullets
    from .coach import game_dirs
    from .config import profile_dir, resolve_session
    from .moments import KINDS, chains, focus_tests, kinds_for, session_digest
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = resolve_session(a.session)
    if not p.is_dir():
        raise SystemExit(f"digest: no session {a.session!r} in the library")
    games = game_dirs(p, a.games.split() if a.games else None)
    focuses = focus_bullets(profile_dir() / "lessons.md")
    out = session_digest(p, games, focuses)
    kinds = sorted({k for f in focuses for k in kinds_for(f)}) or list(KINDS)
    for g in games:
        pk = json.loads((g / "packet" / "packet.json").read_text(encoding="utf-8"))
        tests = [x for x in pk.get("focus_tests") or focus_tests(pk) if x["kind"] in kinds]
        ch = pk["chains"] if "chains" in pk else chains(pk)
        print(f"  {g.name:42s} deaths {len(pk.get('deaths') or []):2d}  chains {len(ch)}  focus tests {len(tests):2d}")
    print(f"digest -> {out} ({len(out.read_text(encoding='utf-8')) // 4:,} tokens, roughly)")


def cmd_trend(a):
    from .history import format_trend, trend
    t = trend("games" if a.games else "session", a.games, a.role, a.hero)
    print(json.dumps(t, indent=1) if a.json else format_trend(t))


def cmd_config(a):
    from .config import resolved
    if a.value is not None:
        if a.key != "dev":
            raise SystemExit("config: only `dev` can be set here (owcoach config dev on|off); the rest comes from setup")
        from coachlib.config import parse_on_off, set_dev
        try:
            on = parse_on_off(a.value)
        except ValueError as e:
            raise SystemExit(f"config: {e}")
        p = set_dev(on)
        print(f"dev: {'on' if on else 'off'} ({p})")
        return
    r = resolved()
    if a.key:
        v = r.get(a.key)
        if v is None:
            raise SystemExit(f"config: no key {a.key!r} (one of {', '.join(r)})")
        print("\n".join(v) if isinstance(v, list) else v)
    else:
        print(json.dumps(r, indent=1))


def cmd_setup(a):
    """Tools, config, profile. The one script a new install runs."""
    import shutil
    import sys
    from . import config
    problems = []
    for tool, hint in (("ffmpeg", "winget install Gyan.FFmpeg"), ("ffprobe", "comes with ffmpeg"),
                       ("tesseract", "winget install UB-Mannheim.TesseractOCR"), ("claude", "npm install -g @anthropic-ai/claude-code")):
        found = shutil.which(tool) or (tool == "tesseract" and a.tesseract and (Path(a.tesseract) / "tesseract.exe").exists())
        print(f"  {tool:10s} {'ok' if found else 'MISSING  -> ' + hint}")
        if not found:
            problems.append(tool)
    for mod in ("cv2", "numpy", "markdown_it"):
        try:
            __import__(mod)
            print(f"  {mod:10s} ok")
        except ImportError:
            print(f"  {mod:10s} MISSING  -> pip install {'opencv-python' if mod == 'cv2' else 'markdown-it-py' if mod == 'markdown_it' else mod}")
            if mod != "markdown_it":
                problems.append(mod)
    cfg = config.load()
    ow = cfg.setdefault("ow", {})
    if a.captures:
        ow["captures"] = [str(Path(c).resolve()) for c in a.captures]
    elif not ow.get("captures"):
        found = [str(c) for c in config.captures()]
        if found:
            ow["captures"] = found
    if a.library:
        ow["library"] = str(Path(a.library).resolve())
    elif not ow.get("library"):
        ow["library"] = str(config.library())
    if a.profile:
        ow["profile"] = str(Path(a.profile).resolve())
    elif not ow.get("profile"):
        ow["profile"] = str(config.profile_dir())
    if a.player:
        ow["player"] = a.player
    if a.tesseract:
        ow["tesseract"] = str(Path(a.tesseract))
    elif not ow.get("tesseract") and not shutil.which("tesseract"):
        t = Path(r"C:\Program Files\Tesseract-OCR")
        if (t / "tesseract.exe").exists():
            ow["tesseract"] = str(t)
    p = config.save(cfg)
    print(f"  config     {p}")
    Path(ow["library"]).mkdir(parents=True, exist_ok=True)
    Path(ow["profile"]).mkdir(parents=True, exist_ok=True)
    for k in ("captures", "library", "profile"):
        print(f"  {k:10s} {ow.get(k)}")
    from coachlib.launcher import write_link
    link = write_link(create=True)
    print(f"  desktop    {link or 'no desktop folder found; the page is <library>/coaching.html'}")
    if not ow.get("captures"):
        print("  no capture folder found: rerun with --captures <folder with the recordings>")
    if problems:
        raise SystemExit(f"setup: install {', '.join(problems)} and rerun")
    if (Path(ow["profile"]) / "profile.json").exists():
        name = json.loads((Path(ow["profile"]) / "profile.json").read_text(encoding="utf-8")).get("name")
        print(f"  profile    {name} (exists)")
        if not ow.get("player") and name:
            ow["player"] = name
            config.save(cfg)
    elif a.from_rec:
        from .profile import init
        from .scan import scan
        video = Path(a.from_rec)
        print(f"  scanning {video.name} to learn your nameplate (a few minutes)")
        scan(video, config.cache_for(video), quiet=True)
        prof = init(config.cache_for(video), name=a.player, assume_yes=a.yes)
        ow["player"] = prof["name"]
        config.save(cfg)
        print(f"  profile    {prof['name']} -> {ow['profile']}")
    else:
        recs = config.recordings()
        hint = f'--from "{recs[0]}"' if recs else "--from <a recording with gameplay>"
        print(f"  no profile yet: rerun `owcoach setup {hint}` to learn your nameplate from a recording")
    sys.stdout.flush()


def cmd_new(a):
    from .config import new_recordings
    for p in new_recordings():
        print(p if a.paths else p.stem)


def _recording(arg: str) -> Path:
    from .config import SESSION_PREFIX, recordings, stem
    p = Path(arg)
    if p.is_file():
        return p
    for r in recordings():
        if stem(r) in (arg, SESSION_PREFIX + arg) or r.name == arg:
            return r
    raise SystemExit(f"no recording {arg!r} in the capture folders (owcoach new lists them)")


def cmd_run(a):
    from .pipeline import NoProfile, run
    try:
        for r in a.recording:
            run(_recording(r), jobs=a.jobs, force=a.force, hud=not a.no_hud)
    except NoProfile as e:
        raise SystemExit(str(e))


def cmd_site(a):
    import sys
    from .site import build
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = build(Path(a.out) if a.out else None)
    print(f"site: {out}")
    if a.open:
        from coachlib.launcher import open_page
        open_page(out)


def cmd_coach(a):
    import sys
    from .coach import coach, estimate, game_dirs
    from .config import dev, new_recordings, resolve_session
    from .pipeline import NoProfile, run
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sessions = []
    if a.new or not a.session:
        new = new_recordings()
        if not new and not a.session:
            raise SystemExit("coach: nothing new in the capture folders (name a session to re-coach one)")
        for r in new:
            print(f"processing {r.name}")
            try:
                sessions.append(run(r, jobs=a.jobs))
            except NoProfile as e:
                raise SystemExit(str(e))
    for s in a.session:
        p = resolve_session(s)
        if not p.is_dir():
            raise SystemExit(f"coach: no session {s!r} in the library")
        sessions.append(p)
    games = a.games.split() if a.games else None
    n = sum(len(game_dirs(s, games)) for s in sessions)
    print(f"{n} game(s) in {len(sessions)} session(s): " + ", ".join(s.name for s in sessions))
    for s in sessions:
        for g in game_dirs(s, games):
            print(f"  {s.name} / {g.name}")
    if dev():                     # the dollar estimate is a development aid, never shown to a player
        cost, per, hist = estimate(n)
        print(f"estimated cost ${cost:.0f} (${per:.2f}/game, {'the mean of ' + str(hist) + ' logged games' if hist else 'no history yet'})"
              + (" + about $1 for the summary" if a.summary else ""))
    else:
        print("this takes several minutes a game")
    if n == 0:
        print("no games to coach")
        return
    if not a.yes:
        try:
            ans = input("coach them? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            raise SystemExit("not started (pass --yes to skip the question)")
    combined = a.sessions_summary or (len(sessions) > 1 and not a.session)   # several new one-game sessions -> one summary
    res = coach(sessions, games, model=a.model, effort=a.effort, writer_effort=a.writer_effort, reader_model=a.reader_model,
                summary=a.summary, combined=combined, role=a.role, parallel=a.parallel)
    print(f"done: {res['games']} games in {res['games_s']}s, total {res['total_s']}s")
    for s in res["summaries"]:
        print(f"  {s}")
    if res.get("site") and a.open:
        from coachlib.launcher import open_page
        open_page(Path(res["site"]))


def cmd_migrate(a):
    from .migrate import migrate, rewrite
    if a.rewrite_only:
        rewrite()
        return
    migrate(Path(a.old) if a.old else None, Path(a.cache) if a.cache else Path.home() / ".cache" / "owcoach",
            Path(a.old_profile) if a.old_profile else Path.home() / ".owcoach", a.dry_run)


def cmd_install_skill(a):
    from coachlib.install import install_skills
    mode = "link" if a.link else "copy" if a.copy else "auto"
    for line in install_skills(mode):
        print(line)


def main(argv=None):
    from coachlib.version import version
    p = argparse.ArgumentParser(prog="owcoach")
    p.add_argument("--version", action="version", version=f"coachclaude {version()}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan")
    s.add_argument("video")
    s.add_argument("--cache")
    s.add_argument("--mode", default="keyframes", help="keyframes | fps=N")
    s.add_argument("--width", type=int, default=1280)
    s.add_argument("--chunk", type=float, default=600, help="seconds of video per resumable chunk")
    s.add_argument("--budget", type=float, help="stop before exceeding this many wall-clock seconds")
    s.add_argument("--jobs", type=int, default=2, help="chunks decoded in parallel")
    s.add_argument("--hwaccel", default="auto", choices=["auto", "cuda", "none"],
                   help="decode on the GPU (NVDEC); auto = cuda if it works on this file")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("sheet")
    s.add_argument("cache")
    s.add_argument("--every", type=int, default=10)
    s.add_argument("--start", type=float, default=0)
    s.add_argument("--end", type=float)
    s.add_argument("--tile", type=int, default=240)
    s.add_argument("--labels", action="store_true", help="burn in state labels")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_sheet)

    s = sub.add_parser("init", help="learn the player's nameplate from a scanned recording")
    s.add_argument("cache")
    s.add_argument("--name", help="your in-game name (skips the prompt)")
    s.add_argument("--yes", action="store_true", help="accept the OCR'd name without asking")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("segment")
    s.add_argument("cache")
    s.set_defaults(fn=cmd_segment)

    s = sub.add_parser("events")
    s.add_argument("cache")
    s.set_defaults(fn=cmd_events)

    s = sub.add_parser("split")
    s.add_argument("cache")
    s.add_argument("--out")
    s.add_argument("--pad", type=float, default=3.0)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--cut", choices=["here", "script", "none"], default="here",
                   help="here: ffmpeg now; script: write cut_matches.ps1 for Windows; none: skip")
    s.set_defaults(fn=cmd_split)

    s = sub.add_parser("hero", help="write <profile>/heroes/<Hero>.md from the Overwatch wiki (reference for the coach)")
    s.add_argument("hero", nargs="+", help="hero names as the wiki spells them, e.g. Mizuki Lifeweaver Wrecking_Ball")
    s.set_defaults(fn=cmd_hero)

    s = sub.add_parser("hud", help="HP and ability states for the whole session (2 fps); run after events")
    s.add_argument("cache")
    s.add_argument("--jobs", type=int, default=8)
    s.set_defaults(fn=cmd_hud)

    s = sub.add_parser("packet", help="per-game coaching packet; run after split")
    s.add_argument("cache")
    s.add_argument("--out")
    s.add_argument("--game", type=int, help="only this match number")
    s.add_argument("--jobs", type=int, default=4, help="stills decoded in parallel")
    s.add_argument("--refresh", action="store_true", help="rewrite packet.json from the stills already on disk (no regrab)")
    s.set_defaults(fn=cmd_packet)

    s = sub.add_parser("notes", help="concatenate a game's reader notes into packet/notes/all.md for the writer")
    s.add_argument("game", help="the game folder (the one with packet/)")
    s.set_defaults(fn=cmd_notes)

    s = sub.add_parser("digest", help="write <session>/digest.md: every match's deaths, chains and focus tests as text (free)")
    s.add_argument("session", help="session folder or name")
    s.add_argument("--games", help='only these games, e.g. "m01 m04"')
    s.set_defaults(fn=cmd_digest, needs_tools=False)

    s = sub.add_parser("focus", help="show the coach's focus proposal, or pick the next focus: owcoach focus 2 [4]")
    s.add_argument("n", nargs="*", help="option number(s) from <profile>/focus_proposal.md, e.g. 2 4 or 2,4")
    s.add_argument("--set", metavar="WORDING", help="your own wording for the focus (with or without numbers)")
    s.set_defaults(fn=cmd_focus)

    s = sub.add_parser("trend", help="per-10 stats of recent games vs the player's baseline")
    s.add_argument("--games", type=int, help="recent = the last N games (default: the latest session)")
    s.add_argument("--role")
    s.add_argument("--hero")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_trend)

    s = sub.add_parser("setup", help="once per install: check the tools, write the config, learn your nameplate")
    s.add_argument("--captures", action="append", metavar="DIR", help="folder with the recordings (repeatable)")
    s.add_argument("--library", metavar="DIR", help="where sessions, clips and packets go (default ~/Videos/owcoach)")
    s.add_argument("--profile", metavar="DIR", help="per-player state (default ~/.local/share/coachclaude/ow)")
    s.add_argument("--player", help="your in-game name")
    s.add_argument("--tesseract", metavar="DIR", help="Tesseract-OCR folder if it isn't on PATH")
    s.add_argument("--from", dest="from_rec", metavar="RECORDING", help="a recording to learn the nameplate from")
    s.add_argument("--yes", action="store_true", help="accept the OCR'd name without asking")
    s.set_defaults(fn=cmd_setup, needs_tools=False)

    s = sub.add_parser("config", help="print the resolved paths (or one: owcoach config library); owcoach config dev on|off")
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?", help="only for dev: on or off")
    s.set_defaults(fn=cmd_config, needs_tools=False)

    s = sub.add_parser("new", help="recordings in the capture folders that have no session in the library yet")
    s.add_argument("--paths", action="store_true", help="full paths instead of stems")
    s.set_defaults(fn=cmd_new, needs_tools=False)

    s = sub.add_parser("run", help="every local stage for a recording: scan segment events hud split packet")
    s.add_argument("recording", nargs="+", help="recording path or stem (owcoach new lists them)")
    s.add_argument("--jobs", type=int, default=2)
    s.add_argument("--force", action="store_true", help="redo stages whose outputs exist")
    s.add_argument("--no-hud", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("site", help="rebuild <library>/coaching.html, the page over every session and game")
    s.add_argument("--out", help="write the page somewhere else")
    s.add_argument("--open", action="store_true", help="open it in the browser")
    s.set_defaults(fn=cmd_site, needs_tools=False)

    s = sub.add_parser("coach", help="coach sessions: one claude process per game, then the summary (paid)")
    s.add_argument("session", nargs="*", help="session folder(s) or name(s); none = every new recording")
    s.add_argument("--new", action="store_true", help="process and coach every new recording as well")
    s.add_argument("--games", help='only these games, e.g. "m01 m04"')
    s.add_argument("--model", default="claude-opus-5-5")
    s.add_argument("--effort", default="low", help="reader effort (low is the default since 2026-10-16)")
    s.add_argument("--writer-effort", default="low")
    s.add_argument("--reader-model", help="the readers' model (sonnet|opus|haiku); the writer keeps --model")
    s.add_argument("--no-summary", dest="summary", action="store_false", help="games only")
    s.add_argument("--sessions-summary", action="store_true", help="one summary over all the sessions given")
    s.add_argument("--role", help="trend filter (e.g. support)")
    s.add_argument("--jobs", type=int, default=2, help="decode jobs for --new processing")
    s.add_argument("--parallel", type=int, default=12, help="claude processes at once (one per piece)")
    s.add_argument("--yes", "-y", action="store_true", help="don't ask before spending")
    s.add_argument("--no-open", dest="open", action="store_false", help="don't open the page in the browser when done")
    s.set_defaults(fn=cmd_coach)

    s = sub.add_parser("migrate", help="move the pre-2026-10-17 layout (<captures>/owcoach, ~/.cache/owcoach, ~/.owcoach) into the library")
    s.add_argument("--from", dest="old", metavar="DIR", help="the old owcoach folder next to the recordings")
    s.add_argument("--cache", metavar="DIR", help="the old cache root (default ~/.cache/owcoach)")
    s.add_argument("--old-profile", metavar="DIR", help="the old profile (default ~/.owcoach)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--rewrite-only", action="store_true", help="only make the stored paths relative")
    s.set_defaults(fn=cmd_migrate, needs_tools=False)

    s = sub.add_parser("install-skill", help="put the ow-coach and hots-coach skills into ~/.claude/skills "
                                             "(linked from a checkout, copied from a release install)")
    s.add_argument("--link", action="store_true", help="link even from an installed package")
    s.add_argument("--copy", action="store_true", help="copy even from a checkout (what a release install does)")
    s.set_defaults(fn=cmd_install_skill, needs_tools=False)

    a = p.parse_args(argv)
    if getattr(a, "needs_tools", True):
        from .probe import ensure_tools
        ensure_tools()
    a.fn(a)


if __name__ == "__main__":
    main()
