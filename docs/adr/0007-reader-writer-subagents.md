# Reader and writer subagents; the main context reads no images

The coaching session never reads a packet's images itself. It launches reader subagents (two
deaths per reader, one per 5 minutes of overview sheets, one for the ults), each with a fresh
context, which read every still once and write `packet/notes/<piece>.md`. One writer subagent
per match then judges from the notes and writes `packet/coaching.md`, opening at most 6 stills
itself, only when two notes conflict or a claim backs a habit it will recommend
(`coachlib/skills/ow-coach/SKILL.md`, `references/subagents.md`).

Why: one session reading all 151 of Havana's images never finished. Claude Code cleared old
tool results, the coach re-read stills up to 6 times, and each clear broke the prompt cache
(~$70 API-equivalent, no report). With the fan-out the same match took 7.7 min and $11.89 and
every image was read once.

## Consequences

- The cost moves to subagent output: ~12k tokens per piece, mostly reasoning, plus cache reads
  at one turn per image (readers manage only 0.6-0.8 images per turn despite being asked for
  parallel Reads). Pieces are big because subagents start ~8 s apart even when launched in one
  message.
- Finished notes files are skipped, so a run cut off by a usage limit resumes where it stopped.
- ~~The standing policy on cost: keep information over saving tokens, and mark overspend with a
  `COST:` comment instead of trimming it.~~ Superseded by
  [0012](0012-coach-a-few-moments.md): each input earns its place by measured value, and
  readers read only the shortlisted moments and focus tests.
