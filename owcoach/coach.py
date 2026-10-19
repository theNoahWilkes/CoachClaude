"""`owcoach coach`: the headless coaching driver (one `claude -p` process per game, in parallel,
then one for the session summary, the lessons file and the focus proposal).

Why processes: one session fanning out readers for every game hits Claude Code's limit on
concurrent subagents, and a game's writer can't start until its slowest reader is back, so a
4-game session took 18 min however the pieces were cut. A process per game gets its own budget.
Each game process writes packet/coaching.md and packet/notes/summary.md and leaves lessons.md
alone; the summary process reads the summaries and does the session work.

Logs: <session>/.coach/<game>.jsonl (stream-json, for cost and timing), summary.jsonl, times.txt.
This replaced scripts/coach_session.sh on 2026-10-18 (same prompts, same flags).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .config import library, profile_dir, repo_dir, skill_dir, tesseract_dir

ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Skill", "Agent", "Bash(python:*)", "Bash(ls:*)"]
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_COST = 6.0          # $/game when no history is on disk (7 games, 2026-10-16: $4.4-8.0)


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


def cost_history() -> list[float]:
    """total_cost_usd of the most recent game processes logged in the library (the last
    RECENT_LOGS by file time: older runs predate the slim packet and cost twice as much)."""
    costs = []
    logs = sorted(library().glob("*/.coach/m[0-9]*.jsonl"), key=lambda f: f.stat().st_mtime)[-RECENT_LOGS:]
    for f in logs:
        try:
            for line in reversed(f.read_text(encoding="utf-8", errors="replace").splitlines()):
                if '"type":"result"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "result" and ev.get("total_cost_usd"):     # the process's own result, last line
                    costs.append(float(ev["total_cost_usd"]))
                    break
        except OSError:
            pass
    return costs


def estimate(n_games: int) -> tuple[float, float, int]:
    """(total, per game, logged games the rate comes from)."""
    h = cost_history()
    per = sum(h) / len(h) if h else DEFAULT_COST
    return per * n_games, per, len(h)


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if tesseract_dir():
        env["PATH"] = os.pathsep.join([env.get("PATH", ""), str(tesseract_dir())])
    return env


def _launch(name: str, prompt: str, dirs: list[Path], log_dir: Path, model: str) -> subprocess.Popen:
    cmd = [claude_exe(), "-p", "--model", model, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS]
    for d in [*dirs, profile_dir(), skill_dir()]:
        cmd += ["--add-dir", str(d)]
    out = open(log_dir / f"{name}.jsonl", "wb")
    err = open(log_dir / f"{name}.err", "wb")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=str(repo_dir()), env=_env())
    p.stdin.write(prompt.encode("utf-8"))        # the prompt goes in on stdin: no quoting, any length
    p.stdin.close()
    p._owcoach = (name, time.time(), out, err)   # type: ignore[attr-defined]
    return p


def _finish(p: subprocess.Popen, log_dir: Path) -> None:
    name, t0, out, err = p._owcoach        # type: ignore[attr-defined]
    p.wait()
    out.close(); err.close()
    with open(log_dir / "times.txt", "a", encoding="utf-8") as f:
        f.write(f"{name} exit {p.returncode} wall {time.time() - t0:.0f}s\n")


def effort_lines(effort: str, writer_effort: str, reader_model: str | None) -> str:
    lines = []
    if effort != "default":
        lines.append(f'6. Launch every reader subagent (deaths, overview, ults) with the Agent tool\'s effort set to "{effort}".')
    if writer_effort != "default":
        lines.append(f'7. Launch the writer subagent with the Agent tool\'s effort set to "{writer_effort}".')
    if reader_model:
        lines.append(f'8. Launch every reader subagent (deaths, overview, ults) with the Agent tool\'s model set to "{reader_model}". '
                     "The writer keeps the default model.")
    return ("\n" + "\n".join(lines)) if lines else ""


def game_prompt(g: Path, session: Path, extra: str) -> str:
    return f"""Use the ow-coach skill to coach this one game: {g}

This game is one of several in session {session} being coached in parallel processes, one per game. Constraints:
1. The trend is already saved at {session}/trend.json. Read it; don't run owcoach trend.
2. One game only: no session summary.
3. Read the lessons file as usual, but do NOT edit it (another process does that after every game is done). Put everything you would change in it (this game's focus grades with their counts, new or bumped patterns with death ids, a candidate focus if one stands out) under a '## Lessons' heading at the end of packet/notes/summary.md.
4. Shell commands other than python will be denied; use Read, Glob and Grep for files.
5. Don't schedule wake-ups or check-ins: subagent results arrive on their own. When the writer has replied, stop.{extra}"""


def summary_prompt(sessions: list[Path], out: Path) -> str:
    where = (f"session {sessions[0]}" if len(sessions) == 1
             else "these sessions, played the same evening and summarised together: " + ", ".join(str(s) for s in sessions))
    return f"""Use the ow-coach skill. Every game of {where} has already been coached by a separate process: each game folder has packet/coaching.md and packet/notes/summary.md (the summary ends with a '## Lessons' section of what that game's writer would change in the lessons file). Do the session part only:
1. Read each game's packet/notes/summary.md and {out}/trend.json. Don't re-read the game reports, notes or stills, and don't relaunch readers or writers.
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


def coach(sessions: list[Path], games: list[str] | None = None, model: str = DEFAULT_MODEL, effort: str = "low",
          writer_effort: str = "low", reader_model: str | None = None, summary: bool = True,
          combined: bool = False, role: str | None = None, log=print) -> dict:
    """Coach every game of each session (in parallel across all of them), then the summary:
    one per session, or one over all of them when `combined`."""
    extra = effort_lines(effort, writer_effort, reader_model)
    per = {s: game_dirs(s, games) for s in sessions}
    t0 = time.time()
    procs = []
    for s, gs in per.items():
        log_dir = s / ".coach"
        log_dir.mkdir(exist_ok=True)
        if not combined:
            write_trend(s, None, role)
        for g in gs:
            procs.append((_launch(g.name, game_prompt(g, s, extra), [s], log_dir, model), log_dir))
            log(f"  launched {s.name} / {g.name}")
    if combined:
        out = combined_dir(sessions)
        out.mkdir(parents=True, exist_ok=True)
        (out / ".coach").mkdir(exist_ok=True)
        write_trend(out, sum(len(gs) for gs in per.values()), role)
    for p, log_dir in procs:
        _finish(p, log_dir)
    t1 = time.time()
    res = {"games": sum(len(gs) for gs in per.values()), "games_s": round(t1 - t0), "summaries": []}
    if summary:
        targets = [(sessions, combined_dir(sessions))] if combined else [([s], s) for s in sessions if per[s]]
        for ss, out in targets:
            out.mkdir(parents=True, exist_ok=True)
            log_dir = out / ".coach"
            log_dir.mkdir(exist_ok=True)
            # the summary's add-dirs cover every session it reads plus its own folder
            p = _launch("summary", summary_prompt(ss, out), sorted({out, *ss}, key=str), log_dir, model)
            _finish(p, log_dir)
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
