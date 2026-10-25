---
status: accepted (not yet implemented)
---

# Coach a few moments, not every second; each input earns its place

Supersedes the cost policy in [0007](0007-reader-writer-subagents.md) ("keep information over
saving tokens") and its rule that readers read every image. Changes the match report that
[0001](0001-experience-contract.md) asks to be the same in every game.

The Overwatch coach reads every death, skims the whole match through overview sheets and writes
a report that tries to coach everything in it. That costs about $6 and 6-9 minutes a match, and
the insight the player wants is buried in dense paragraphs. A session should be affordable on a
$20/month plan, and the plan's five-hour window tracks token volume, so the saving has to come
from reading and writing less, not from a cheaper model (#20). The coach now does what a coach
reviewing tape does: it picks a handful of moments for the whole session and says plainly what
they show.

- **Each input earns its place.** Information is added only when a measurement shows what it
  adds to the reports, and an existing input is kept only while one does. 0007's `COST:`
  comments become a measurement or a removal.
- **About five moments per session.** Teachable moments, bad deaths and particularly bad
  decisions go into the session summary, each with its clip. Mundane deaths and fights are not
  coached.
- **The pick happens before the images are read.** A text-only triage reads what the pipeline
  already has for every match (each death's facts block and flags, the HUD fights, low-HP
  episodes, the alive counts, the ults) and shortlists about eight moments for the session.
  Readers read the stills of the shortlisted moments only, and the session summary keeps the best
  five. Rule flags alone are not enough to pick: they miss a bad decision that trips no rule.
- **No whole-match skim.** The preprocessor lists the **focus tests** from text: the windows
  where the current focus could be tested (low-HP episodes, stretches down two, the 20 s after a
  respawn, depending on the focus). Readers read the overview cells of those windows only, to
  see where the player stood. "Saved" banners become a text notice, like the eliminated banner,
  so good plays are still found without the skim. The whole-match skim stays as a dev-mode QA
  pass for pipeline errors.
- **The match report is facts, a verdict and a stoplight.** Everything the pipeline extracts for
  free stays: final scoreboard, stats table, clips, death times linked to the video. Then the
  3-sentence verdict on how the match went, one stoplight per focus (green, amber, red or not
  tested) linked to its focus tests' clips, and "Pipeline issues". No per-death write-ups and no
  per-match habits; anything worth saying goes up to the session summary.
- **The focus is graded in the session summary, in plain words.** The focus grader
  ([0003](0003-focus-loop.md)) reads the focus-test verdicts across the session and says what
  they show the way a coach would talk: "Both good and bad: at 5:18 you broke line of sight,
  healed yourself and got the kill, but at 5:50 you died in the open with no cooldowns and cover
  a step to your left." A clean test is "no problems observed". Numbers go in only when they make
  the point.
- **A full read is the yardstick.** In dev mode, a labelled session can be coached both ways:
  triage, and today's full read of every death and the whole-match skim. The measure is how many
  of the full read's key moments and focus grades the triage run also found. Every miss becomes a
  fix to the facts block, the preprocessor or the triage brief. The player's labels
  (`docs/ow/labels/`) referee both, since the full read scored only about half against them
  (#20). It is a paid run, so it is run on purpose, never on every session.

## Evidence

An audit of the reports of 10 matches (2026-10-16 and 2026-10-20) traced each timestamped line
to the window it came from. 13 % of the lines came from moments only the overview sheets saw:
respawn walk-outs, pipeline errors (a wrong hero track, missed Nano uses) and saves. The session
summary used none of them. What the sheets did that mattered was grade the focus between deaths,
in windows the text already finds. Those windows are 25 % of match time, so reading only them
should cut overview reading, 31 % of a match's cost, by about three quarters. That figure is an
estimate from window coverage, not a measured run.

## Considered Options

- **Read everything, then pick the five.** The reports get shorter but the cost and wall clock
  barely move: reading is what costs. Kept as the dev-mode yardstick.
- **Let the pipeline's rule flags pick the moments.** Free, but the flags are crude and miss the
  decisions the player most wants to hear about.
- **A coarser skim (10-15 s cells) on every match.** It still pays for the 75 % of the match where
  nothing tests the focus.
- **A cheaper reader model.** Rejected in #20: Sonnet tied Opus on quality but used as much of the
  plan window, and Haiku lost on quality.

## Consequences

- Pieces change ([0011](0011-one-headless-process-per-piece.md)): a triage piece per session
  runs before any reader, death pieces exist only for shortlisted deaths, and the 5-minute overview
  pieces become focus-test pieces. Readers write a short verdict per focus test ("held, behind the
  arch wall") instead of prose.
- The match writer does less (verdict, stoplights), and the session summary does more (moments,
  focus grade). Most of the judgement moves to the session level, which is also where 0003 puts
  the pattern finder and the focus grader.
- 0001 asks for match reports with the same sections and job in both games, so the HotS match
  report moves to the same shape: facts, verdict, stoplight.
- The packet keeps everything it extracts today. Only what Claude reads changes.
