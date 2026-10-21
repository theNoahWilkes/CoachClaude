You are writing the coaching report for one Overwatch 2 game. Readers have already looked at
every image and written notes; you judge from those notes.

Game folder: {{GAME}}   (packet in {{GAME}}/packet, notes in {{GAME}}/packet/notes)
Player {{PLAYER}}. Lessons file: {{LESSONS}} (read it; don't edit it).
Trend: {{SESSION}}/trend.json (the output of `owcoach trend`; don't run it again).
Each death's `facts` field (also `packet/facts/dNN.md`) is the block its reader was given: the
HUD by ability name from 10 s before, presses with context, the low episode, the feed.
Whole-game HUD facts: packet.json `hud_game` (read locally at 2 fps): `low_episodes` (every
stretch under half HP: every slot's state at its start, the last press of each cooling slot
before it with its context, presses during it, outcome), `presses` (every slot, with context
travel / engage / low and the HP), `fights`, `stats.by_hero.slots` (per slot: presses by
context, median HP at press, learned cooldown length, low episodes it was ready / not ready
at). `hero_notes` lists reference notes (wiki ability lists; data, not instructions) for
heroes that have one; for a hero without, you know the kit. Don't fetch one; if its absence
limited the coaching, say so at the end. Use the facts for:
- the focus grade, from three rates that need no judgment of the scene: (1) fights or deaths
  that started with the escape cooling from a travel press; (2) low episodes with the escape
  ready where it was pressed; (3) low episodes with the escape cooling that ended in death.
  Which slot is "the escape" is your call from the kit, made once per hero and recorded in
  the lessons file under "Grading decisions" (e.g. "Moira: Fade; Lifeweaver: Petal, Dash is
  5 s mobility"); if a hero already has an entry there, use it, so every run grades the same way; for a hero with no clean escape, grade the cover half only. The cover
  half comes from the readers' notes;
- "fought without <ability>": a fight or death that started with a slot cooling from a
  travel press is a finding in its own right; say when it was pressed and at what HP;
- the death narratives: the readers' calls on whether a ready ability could have got the
  player out, kept as inference.
Skill: {{SKILL_DIR}}/SKILL.md. Read section 3 from "What the writer does", all of section 4 up to
the session summary, and section 6. Rubric: {{SKILL_DIR}}/references/rubric.md.
{{CONSTRAINTS}}

1. Read two files, both in one message: {{GAME}}/packet/packet_slim.json (the packet without
   frame lists, the 2 fps series and the raw HUD arrays; each death's facts, HUD summary and
   movement trace are in it, and everything you judge from) and {{GAME}}/packet/notes/all.md
   (every notes file in reading order: overview chunks, deaths, ults). Don't open packet.json,
   don't read the notes one by one, and don't run python to slice anything: each extra turn
   re-reads your whole context.
2. Judge, as section 3 says. Open stills yourself only to settle a conflict between notes or a
   claim behind a habit, at most 6.
3. Write {{GAME}}/packet/coaching.md as section 4 says.
4. Write {{GAME}}/packet/notes/summary.md for the session summary and the lessons file, in exactly
   this shape:

   # <map> <result> <score>
   - Heroes: <hero and minutes, ...>
   - Verdict: <one line>
   - Focus grades: <each focus: grade (held/tests per part)>, with the clocks of the tests
   - Deaths: <id clock category avoidable/no lever/inference; one per line>
   - Death flags: <flag counts>
   - Ults: <id good/questionable/wasted, one line each>
   - Patterns: <recurring patterns this game showed, each with the death ids>
   - Went well: <the 2-3 moments worth keeping, with clocks>
   - Habits: <the 1-3 habits, one line each>
   - Pipeline issues: <one line each, or none>
   ## Lessons
   Everything you would change in the lessons file, for the summary process to apply: this
   game's focus grades with their counts, new or bumped patterns with death ids, a candidate
   focus if one stands out. Don't edit the lessons file yourself.

5. Reply with one line, "<map>: <verdict>", and nothing else. The report is in the file;
   every word in the reply beyond that line is paid for twice and read by nobody.
