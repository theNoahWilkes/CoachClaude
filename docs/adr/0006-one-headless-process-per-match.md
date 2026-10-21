# One headless process per match

`owcoach coach` runs one `claude -p` process per match, in parallel, then one more process for
the session summary, the lessons file and the focus proposal (`owcoach/coach.py`). A single
session that fanned out readers for every match hit Claude Code's limit on concurrent subagents
(launches were refused and had to be relaunched), and a match's writer can't start until its
slowest reader is back.

Match processes read the lessons file but never edit it, because parallel processes would race
on it. Each one puts what it would change (focus grades with counts, new or bumped patterns, a
candidate focus) under a `## Lessons` heading at the end of its `packet/notes/summary.md`; the
summary process applies those sections, replacing any entries the session already has so
nothing is counted twice. Every process runs with a fixed tool allowlist (`ALLOWED_TOOLS`:
Read, Write, Edit, Glob, Grep, Skill, Agent, `python` and `ls` only) under `acceptEdits`.

## Consequences

- It did not make a session faster. A match's chain (launch ~2 min, readers 4-5 min, writer
  5-6 min) is the floor however the matches are arranged, so a session takes about as long as
  its slowest match (~16 min for session 2, at the same cost as the single-session runs). It
  was kept because each match is resumable on its own, there are no concurrency refusals, and
  the summary step is cheap (~2 min, under $1).
- The remaining wall-clock levers are inside the chain: reader and writer effort, and the
  writer's turn count (see `docs/ow/pipeline.md`).
- The allowlist includes Write and Edit, so it does not keep a process out of the repo; that
  is [0005](0005-dev-mode-enforced-in-code.md).
