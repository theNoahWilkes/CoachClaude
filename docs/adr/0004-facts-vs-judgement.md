# Facts come from free, deterministic extraction; judgement comes from the coach

Each game has two layers. The CLI turns recordings or replays into facts: clips, stills,
kill-feed and HUD reads, rule flags, per-match stats. The coach (a Claude Code skill) only
judges from those facts. The split keeps facts reproducible and costless, and keeps the
expensive, fallible model on the part only it can do.

- **The match log is extracted for free.** Results, maps, heroes, score, rank movement and any
  other stat come only from deterministic local extraction (video, replay files), never from
  model calls. It is the primary record and must be rigorous and queryable. For example, the
  Overwatch HUD is read by the pipeline, not by the model looking at stills.
- **Each record has one owner.** The CLI writes the match log and the coach never does. The
  coach writes the lessons file and reports, and the CLI never writes judgement into them.
- **A misread fact is reported, not patched over.** When the coach sees that a fact is wrong,
  it notes it under "Pipeline issues" in the report, and the fix goes into the extractor.

## Considered Options

- **Let the model read stats from stills or the scoreboard.** Rejected: it costs tokens on
  every match, it is not reproducible, and its errors would be silent and mixed into the record
  that trends are built on.
