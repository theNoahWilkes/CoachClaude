"""`owcoach coach`: the headless coaching driver (ADR 0011).

One `claude -p` process per piece: the driver cuts each match into pieces (`briefs.py`: two
deaths, 5 min of overview, the ults, the writer), fills a brief per piece from the packet and
the lessons file, and runs the readers through a pool, longest pieces first. A match's writer
starts as soon as its readers are done and `notes/all.md` is written. Then one process does
the session summary, the lessons file and the focus proposal (ADR 0006). No Claude context
orchestrates a match: the per-match main process was a quarter of every match's cost, re-reading
its context 20 times to paste facts blocks into briefs (issue #20).

Pieces whose notes are complete are skipped, so a cut-off run resumes. Match processes never
edit lessons.md (the writer puts its changes under `## Lessons` in notes/summary.md).

Logs: <session>/.coach/<match>/<piece>.jsonl (stream-json, for cost and timing), summary.jsonl,
times.txt.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .briefs import Piece, pieces, write_all_notes
from .config import library, profile_dir, repo_dir, skill_dir, tesseract_dir

READER_TOOLS = ["Read", "Glob", "Grep", "Write"]
WRITER_TOOLS = ["Read", "Glob", "Grep", "Write", "Edit"]
SUMMARY_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Skill", "Bash(python:*)", "Bash(ls:*)"]
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_PARALLEL = 12       # processes at once; overview pieces first because they take longest
DEFAULT_COST = 6.0          # $/game when no history is on disk (7 games, 2026-10-16: $4.4-8.0)
ORDER = {"overview": 0, "deaths": 1, "ults": 2, "writer": -1}


def claude_exe() -> str:
    """The claude binary. npm's claude.cmd wraps an exe; call that directly so arguments and
    the prompt don't go through cmd.exe."""
    w = shutil.which("claude")
    if not w:
        raise SystemExit("claude (Claude Code) not found on PATH")
    if w.lower().endswith(".cmd"):
        exe = Path(w).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.exists():
            return str(exe)
    return w


def game_dirs(session: Path, games: list[str] | None = None) -> list[Path]:
    out = []
    for g in sorted(session.glob("m[0-9]*")):
        if not g.is_dir() or not (g / "packet" / "packet.json").exists():
            continue
        if games and g.name[:3] not in games:
            continue
        out.append(g)
    return out


RECENT_LOGS = 10


def _logged_cost(path: Path) -> float:
    """total_cost_usd from a stream-json log's result event (the last line that has one)."""
    try:
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if '"type":"result"' not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result" and ev.get("total_cost_usd"):
                return float(ev["total_cost_usd"])
    except OSError:
        pass
    return 0.0


def cost_history() -> list[float]:
    """Cost per match of the most recent logged matches (RECENT_LOGS by time): per-piece logs
    under .coach/<match>/ summed, and the older one-log-per-match layout as it is."""
    matches: list[tuple[float, float]] = []
    for d in library().glob("*/.coach/m[0-9]*"):
        if d.is_dir():
            logs = list(d.glob("*.jsonl"))
            if logs:
                matches.append((max(f.stat().st_mtime for f in logs), sum(_logged_cost(f) for f in logs)))
        elif d.suffix == ".jsonl":
            matches.append((d.stat().st_mtime, _logged_cost(d)))
    return [c for _, c in sorted(matches)[-RECENT_LOGS:] if c]


def estimate(n_games: int) -> tuple[float, float, int]:
    """(total, per game, logged games the rate comes from)."""
    h = cost_history()
    per = sum(h) / len(h) if h else DEFAULT_COST
    return per * n_games, per, len(h)


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # A piece lives a few minutes and nothing reads its cache afterwards, so the 5-minute cache
    # is the right one. Left unset, Claude Code writes 1-hour cache on a subscription, billed at
    # 2x the input price instead of 1.25x: on the five labelled matches that was $8.80 of $34
    # (issue #21). Subagents always wrote 5-minute cache, which is why the old per-match
    # process looked cheaper per reader than it was.
    env.setdefault("CLAUDE_CODE_PROMPT_CACHE_TTL", "5m")
    if tesseract_dir():
        env["PATH"] = os.pathsep.join([env.get("PATH", ""), str(tesseract_dir())])
    return env


def _launch(name: str, prompt: str, dirs: list[Path], log_dir: Path, model: str, tools: list[str],
            effort: str | None = None, cwd: Path | None = None) -> subprocess.Popen:
    cmd = [claude_exe(), "-p", "--model", model, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "acceptEdits", "--allowedTools", *tools]
    if effort and effort != "default":
        cmd += ["--effort", effort]
    for d in [*dirs, profile_dir(), skill_dir()]:
        cmd += ["--add-dir", str(d)]
    log_dir.mkdir(parents=True, exist_ok=True)
    out = open(log_dir / f"{name}.jsonl", "wb")
    err = open(log_dir / f"{name}.err", "wb")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=str(cwd or repo_dir()), env=_env())
    try:
        p.stdin.write(prompt.encode("utf-8"))    # the prompt goes in on stdin: no quoting, any length
        p.stdin.close()
    except (BrokenPipeError, OSError):           # claude exited before reading (seen once: an auto-update swapped the
        pass                                     # binary mid-run); the piece shows as unfinished and is retried once
    p._owcoach = (name, time.time(), out, err, log_dir)   # type: ignore[attr-defined]
    return p


def _finish(p: subprocess.Popen) -> float:
    name, t0, out, err, log_dir = p._owcoach        # type: ignore[attr-defined]
    out.close(); err.close()
    wall = time.time() - t0
    with open(log_dir / "times.txt", "a", encoding="utf-8") as f:
        f.write(f"{name} exit {p.returncode} wall {wall:.0f}s\n")
    return wall


def summary_prompt(sessions: list[Path], out: Path) -> str:
    where = (f"session {sessions[0]}" if len(sessions) == 1
             else "these sessions, played the same evening and summarised together: " + ", ".join(str(s) for s in sessions))
    return f"""Use the ow-coach skill. Every game of {where} has already been coached by a separate process: each game folder has packet/coaching.md and packet/notes/summary.md (the summary ends with a '## Lessons' section of what that game's writer would change in the lessons file). Do the session part only:
1. Read each game's packet/notes/summary.md and {out}/trend.json. Don't re-read the game reports, notes or stills, and don't launch readers or writers.
2. Write the session summary to {out}/coaching.md (skill section 4, 'For a multi-game session'). Name every game's folder in it.
3. Update the lessons file (skill section 5) from the games' '## Lessons' sections: if this session already has entries in it, replace them rather than adding to them, so nothing is counted twice. Add grades under the current focus; do NOT change its wording.
4. Write the focus proposal to the profile's focus_proposal.md (skill section 5 and references/focus-proposal.md). Nobody is at the keyboard: don't ask, don't run owcoach focus; say in chat and at the end of {out}/coaching.md that the proposal is waiting for 'owcoach focus'.
5. Give the short version in chat.
Shell commands other than python will be denied."""


def combined_dir(sessions: list[Path]) -> Path:
    """One folder for a summary over several sessions: '<date> - <HH.MM> to <HH.MM>'."""
    names = sorted(s.name for s in sessions)
    m = [re.match(r"(\d{4}\.\d{2}\.\d{2}) - (\d{2})\.(\d{2})", n) for n in names]
    if all(m) and len({x.group(1) for x in m}) == 1:
        return library() / f"{m[0].group(1)} - {m[0].group(2)}.{m[0].group(3)} to {m[-1].group(2)}.{m[-1].group(3)}"
    return library() / (names[0] + f" +{len(names) - 1}")


def write_trend(out: Path, n_games: int | None, role: str | None) -> None:
    from .history import trend
    t = trend("games" if n_games else "session", n_games, role, None)
    (out / "trend.json").write_text(json.dumps(t, indent=1), encoding="utf-8")


class _Match:
    """One match's pieces and where they stand."""

    def __init__(self, game: Path, log=print):
        self.game = game
        all_pieces = pieces(game)
        self.writer = next(p for p in all_pieces if p.kind == "writer")
        self.readers = [p for p in all_pieces if p.kind != "writer"]
        self.pending = {p.name for p in self.readers if not p.done()}
        self.retried: set[str] = set()
        self.writer_launched = False
        skipped = len(self.readers) - len(self.pending)
        if skipped:
            log(f"  {game.name}: {skipped} piece(s) already read, {len(self.pending)} to go")

    @property
    def written(self) -> bool:
        return self.writer.done() and not self.pending


def run_pieces(matches: list[_Match], model: str, reader_model: str | None, effort: str, writer_effort: str,
               parallel: int, log=print) -> None:
    """Readers through a pool, each match's writer as soon as its readers are done."""
    queue: list[tuple[_Match, Piece]] = [(m, p) for m in matches for p in m.readers if p.name in m.pending]
    queue.sort(key=lambda mp: ORDER[mp[1].kind])
    for m in matches:                                # matches with every reader done already: writer first
        if not m.pending and not m.written:
            queue.insert(0, (m, m.writer)); m.writer_launched = True
    running: list[tuple[subprocess.Popen, _Match, Piece]] = []

    def launch(m: _Match, p: Piece) -> None:
        log_dir = m.game.parent / ".coach" / m.game.name
        if p.kind == "writer":
            write_all_notes(m.game)
            proc = _launch(p.name, p.prompt, [m.game.parent], log_dir, model, WRITER_TOOLS, writer_effort, cwd=m.game)
        else:
            proc = _launch(p.name, p.prompt, [m.game.parent], log_dir, reader_model or model, READER_TOOLS, effort, cwd=m.game)
        running.append((proc, m, p))
        log(f"  launched {m.game.name} / {p.name}")

    while queue or running:
        while queue and len(running) < parallel:
            launch(*queue.pop(0))
        time.sleep(2)
        still = []
        for proc, m, p in running:
            if proc.poll() is None:
                still.append((proc, m, p)); continue
            wall = _finish(proc)
            if p.done():
                log(f"  done {m.game.name} / {p.name} ({wall:.0f}s)")
            elif p.name not in m.retried:                 # one retry: the piece resumes from whatever it wrote
                m.retried.add(p.name)
                log(f"  {m.game.name} / {p.name} exited {proc.returncode} without finishing; relaunching once")
                queue.insert(0, (m, p)); continue
            else:
                log(f"  {m.game.name} / {p.name} still incomplete after a retry; the writer will work from what there is")
            if p.kind != "writer":
                m.pending.discard(p.name)
                if not m.pending and not m.writer_launched:
                    m.writer_launched = True
                    queue.insert(0, (m, m.writer))
        running = still


def coach(sessions: list[Path], games: list[str] | None = None, model: str = DEFAULT_MODEL, effort: str = "low",
          writer_effort: str = "low", reader_model: str | None = None, summary: bool = True,
          combined: bool = False, role: str | None = None, parallel: int = DEFAULT_PARALLEL, log=print) -> dict:
    """Coach every match of each session (pieces pooled across all of them), then the summary:
    one per session, or one over all of them when `combined`."""
    per = {s: game_dirs(s, games) for s in sessions}
    t0 = time.time()
    matches: list[_Match] = []
    for s, gs in per.items():
        (s / ".coach").mkdir(exist_ok=True)
        if not combined:
            write_trend(s, None, role)
        for g in gs:
            m = _Match(g, log)
            if m.written:
                log(f"  {g.name}: already written, skipping")
                continue
            matches.append(m)
    if combined:
        out = combined_dir(sessions)
        out.mkdir(parents=True, exist_ok=True)
        (out / ".coach").mkdir(exist_ok=True)
        write_trend(out, sum(len(gs) for gs in per.values()), role)
    run_pieces(matches, model, reader_model, effort, writer_effort, parallel, log)
    t1 = time.time()
    res = {"games": sum(len(gs) for gs in per.values()), "games_s": round(t1 - t0), "summaries": [],
           "unfinished": [f"{m.game.name}/{p.name}" for m in matches for p in [*m.readers, m.writer] if not p.done()]}
    if summary:
        targets = [(sessions, combined_dir(sessions))] if combined else [([s], s) for s in sessions if per[s]]
        for ss, out in targets:
            out.mkdir(parents=True, exist_ok=True)
            log_dir = out / ".coach"
            # the summary's add-dirs cover every session it reads plus its own folder
            p = _launch("summary", summary_prompt(ss, out), sorted({out, *ss}, key=str), log_dir, model, SUMMARY_TOOLS)
            p.wait()
            _finish(p)
            res["summaries"].append(str(out / "coaching.md"))
            log(f"  summary -> {out / 'coaching.md'}")
    res["total_s"] = round(time.time() - t0)
    for s in sessions:
        if per[s]:
            with open(s / ".coach" / "times.txt", "a", encoding="utf-8") as f:
                f.write(f"games {res['games_s']}s  total {res['total_s']}s\n")
    try:
        from .site import build
        res["site"] = str(build())
        log(f"  page -> {res['site']}")
    except Exception as e:            # the page is a convenience; the reports are already on disk
        log(f"  page not rebuilt: {e}")
    return res
