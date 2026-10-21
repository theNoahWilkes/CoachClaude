---
status: accepted (code partly behind; see the checklist in CLAUDE.md)
---

# The player's experience is the shared contract, not the coaching content

CoachClaude ships an experience: an honest outside read of your matches, and a focus you work
on from one session to the next. That experience must feel the same in every game. What good
play looks like differs between games, so the coaching content (rubrics, death categories,
pipelines, what counts as a mistake) is free to specialize. Throughout, prefer the lighter
option: remove friction wherever it can be removed.

**Invariants** (changing one needs a new ADR):

- **The coach's voice.** The coach is an honest outside reporter: what went well, what went
  poorly, no padding. Flags from the CLI are leads, not verdicts. Inferences are labelled. This
  is the core deliverable.
- **The focus loop**, as defined in [0003](0003-focus-loop.md).
- **The landing page** is a time-ordered list of sessions and matches with their results.
- **Commands.** Every user-facing verb exists in each game's CLI and means the same thing. A
  verb that makes sense for only one game is a design problem to solve, not an exception.
  Developer diagnostics (pipeline probes and scans) are not user-facing and are exempt.

**Guiding principles** (departing from one needs a reason, not an ADR):

- The match report, session summary and lessons file have the same sections and the same job
  in every game.
- Match pages are recognizably similar across games, without a fixed format.

## Considered Options

- **Share everything, including the rubrics.** Rejected: good HotS coaching needs different
  thinking from good Overwatch coaching, so forcing one shape would make both worse.
- **Share nothing beyond the code.** Rejected: the two coaches had already drifted apart, for
  example in who owns the focus and in what a session is.
