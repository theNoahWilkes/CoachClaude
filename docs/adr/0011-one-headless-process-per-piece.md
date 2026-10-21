# One headless process per piece; the driver fills the briefs

Supersedes the per-match part of [0006](0006-one-headless-process-per-match.md) and amends
[0007](0007-reader-writer-subagents.md).

`owcoach coach` cuts each match into pieces (two deaths, 5 minutes of overview sheets, the
ults, the writer), fills a brief per piece from `packet.json` and the lessons file, and runs one
`claude -p` process per piece through a pool (`owcoach/coach.py`, `owcoach/briefs.py`). A match's
writer starts when its readers are done; one more process then does the session summary, the
lessons file and the focus proposal, as 0006 says. The brief wording stays skill text, as
templates in `coachlib/skills/ow-coach/briefs/` with `{{FIELD}}` markers; filling them is code.
No Claude context orchestrates a match, and an interactive session never launches readers or
writers itself.

Why: in the reader-model A/B (issue #20) the per-match main process was 23-30 % of every arm,
about $1.5-1.8 a match, spent on 17-22 turns re-reading a 100-135k context and on pasting facts
blocks into briefs at Opus output price. Every brief is a template filled from facts the CLI
already has ([0004](0004-facts-vs-judgement.md)). The plan's five-hour window tracks token
volume, not model price, so removing those tokens is a saving a subscriber feels, where a
cheaper reader model was not (#20).

## Consequences

- 0006's reasons still hold one level down: every piece is resumable on its own, and the
  concurrency limit is the pool, not Claude Code's subagent cap. Logs move to
  `<session>/.coach/<match>/<piece>.jsonl`; the dev-mode estimate sums them per match.
- 0007's split stands: readers read every image once, the writer judges from the notes. "The
  main context reads no images" becomes "there is no main context".
- The skill no longer describes a fan-out. Section 3 of `SKILL.md` describes the pieces; the
  piece table and the measured reasons are in `references/subagents.md`.
- A piece pays the Claude Code system prompt (~13k tokens) as a subagent did. Readers get Read,
  Glob, Grep and Write only; no piece has the Agent tool.
- Each process must write 5-minute prompt cache (`CLAUDE_CODE_PROMPT_CACHE_TTL=5m`, set by the
  driver). Left unset, Claude Code writes 1-hour cache for a top-level session on a
  subscription, at 2x the input price instead of 1.25x; a piece lives minutes and nothing
  reads its cache afterwards. Subagents always wrote 5-minute cache, which hid this before.
- Measured on the five labelled matches of #20 (issue #21, 2026-10-21): cache writes -21 %,
  cache reads -27 %, output -33 %, wall clock -13 % (403 s against 462 s), blind quality 48/90
  against 46/90. List price only -4 % because that run wrote 1-hour cache; at the 5-minute rate
  the same token counts price at -29 %.
