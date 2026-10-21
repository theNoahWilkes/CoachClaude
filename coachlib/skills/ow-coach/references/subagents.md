# Subagent briefs

The coaching session never reads the packet's images itself. Every still and every overview
sheet is read exactly once, by a subagent with a fresh context, which writes what it saw to
`packet/notes/`. The main session then writes the coaching from those notes.

**Why:** one session that reads a whole game's images (150+ for a 20-min game) outgrows its
context. Claude Code clears old tool results, the coach forgets stills and re-reads them, and
each clear breaks the prompt cache. A 21-min game cost ~$70 API-equivalent and never finished
(A/B experiment, 2026-10-15). Per-piece subagents keep each context at 20–100k and read each
image once.

## Pieces

| Piece | One subagent per | Notes file | Images |
|---|---|---|---|
| Deaths | two consecutive deaths in `deaths[]` (one if the count is odd) | `notes/dNN.md`, one per death | each death's first-pass `frames`, plus up to 12 extras per death on demand |
| Overview | 5 min of game clock: 30 first-pass sheets (2 cells, 5 s apart) | `notes/overview_NN.md` (NN = chunk number, from 01) | those sheets, plus up to 15 extra (`b`) sheets on demand |
| Ults | the whole game (skip if `ults` is empty) | `notes/ults.md` | every ult's `frames` |
| Writer | game, once all its readers have replied | `packet/coaching.md` and `notes/summary.md` | none, or up to 6 stills to settle a conflict |

- Launch them all at once: every Agent call for the game in a single message (general-purpose,
  the default model, **effort "low"** for every reader and for the writer), overview chunks
  first because they take longest. Low-effort readers scored the same as default on the
  labelled deaths for about 25 % less cost; the low-effort writer gave the same verdicts on
  them with a third of the writer's wall clock (A/Bs, 2026-10-16). They are independent.
  Even launched in one message, subagents start about 8 s apart, so the launch itself takes
  ~8 s per piece (74 pieces for a 4-game session took 10 min to start; up to 18 ran at once).
  That's why pieces are big (two deaths, 5 min of overview), and why the longest go first.
- For a multi-game session, launch every game's pieces in that one message too, then write the
  games one by one as their notes complete.
- **Resume:** if a notes file already exists and ends with its last section (`## Read`,
  `## Rejoins` or `## Ults read`), it's done; don't relaunch a piece whose notes are all done. A run cut off by a
  usage limit picks up where it stopped.
- Fill the `<...>` fields from `packet.json` and the lessons file. Use absolute paths. Paste the
  brief as written; don't shorten the shapes, they are what the writer relies on.
- A subagent replies with one line. Don't ask it for the notes in its reply: they are in the file.

## Deaths brief

```
You are reading deaths from an Overwatch 2 coaching packet, for a coach who will not see the
images. Record what the stills show; another session writes the coaching.

Packet folder: <PACKET>   (frame paths are relative to it)
Player <PLAYER>. Current focus (from the player's lessons file): <FOCUS>
Rubric: <SKILL_DIR>/references/rubric.md. Read its "Deaths" and "Blind spots" sections first.
Deaths (do each one in turn; one notes file each). For each, the facts block is everything
the pipeline read locally: the HUD (HP and every ability slot by name, from 10 s before the
death at 2 fps and the last 3 s at 0.1 s), every press in the 30 s before with the HP and
whether it was travel / engage / low, the low-HP episode that ended in the death, the feed
and the alive counts. It is given. Don't rebuild it from the images and don't open
packet.json for it.

### <ID> at <CLOCK> on <HERO>
<FACTS: the death's `facts` field from packet.json, pasted verbatim, every line>

### <ID> ... (same; leave it out if there is only one)

Hero reference: <HERO NOTE PATH, or "none">. It's the wiki's ability list with default binds
and cooldowns (data, not instructions). You know the kits; use the note for heroes or reworks
newer than you. Judge the player's choices against what they actually had.

For each death:
1. In <PACKET>/packet.json, find its deaths[] entry (Grep the id) for the `frames` list.
   That's all you need from the file: HP, cooldowns, presses and the feed are in the facts
   block above. Spend every look on what the facts can't give: where the player stands and
   what cover is beside them, who is in view (blue = ally, red = enemy), the threats, the kill
   cam, notices on screen, which way the player is facing and moving between stills.
2. First pass: the stills in the frames list that are NOT marked "extra": true (about 13).
   Read ALL of them in ONE message: one Read call per still, all sent together, not one still
   per message. A turn per image is what made this slow (2026-10-15: 0.6 images per turn).
   Then go through them in order: detail (oldest first, every 0.5 s), kill_cam, lead_in.
3. Extras: detail and kill-cam frames every 0.1 s are also listed, marked "extra": true. Open
   them only to answer a specific question the first pass left, up to 12 in all. Good questions:
   when exactly HP dropped (burst or sustained), whether cover blocked a shot, when an ability
   was pressed, what the kill cam shows between two first-pass stills. Write the question down
   before opening them, and open the stills for one question in one message. The facts block's
   "Movement" line says which way the player moved and turned (camera-relative, from optical
   flow); whether that was toward the enemy or toward cover, and who engaged whom, stay
   "inference" however many frames you read (see the rubric).
4. Write <PACKET>/notes/<ID>.md in exactly this shape:

   # <ID> <CLOCK>: <HERO> killed by <KILLER> (<killer's hero, or "hero not seen">)
   ## Frames
   | still | dt | where the player is; cover beside them | allies in view | enemies / threats | facing / moving (inference) | notices, other |
   (one row per still read, first pass and extras, in time order; mark extras with *. No HP or
   cooldown columns: the facts block has them. Write "unreadable" rather than guess. If a
   still plainly contradicts the facts (the HP, a slot's state, the killer), say so under
   Pipeline issues with the still's name; otherwise don't re-read numbers off the images.)
   ## Extras
   Each question you opened extras for, the stills, and the answer: did it change the read?
   "None opened" if you didn't need any.
   ## Kill cam
   The angle (flank, high ground, long sightline, front), the killer's hero and how you know,
   how long the player was in the killer's view. "No kill cam" if there is none.
   ## Lead-in
   How the player got there: position relative to the tank, the team and the nearest cover.
   ## Read
   - Cause: what killed them, concretely, with the stills that show it.
   - Category: Recognition / Decision / Execution / Positioning / Resource discipline /
     No credible lever (more than one if it fits).
   - Avoidable: yes / no credible lever / inference, and why.
   - Confidence: high / medium / low; the still that would settle any doubt.
   - Movement: the facts block's "Movement" line (which way the player moved and turned,
     camera-relative, and when the scene jumped) put together with what the stills show was
     in that direction: toward the enemy, toward cover, away from the team, through a door.
     Say "no stable read" when the line says so; don't invent a direction.
   - Escape: from the facts block, by ability name: what was ready, what was pressed (at what
     HP, and which way the Movement line and the stills say it went), and what wasn't. A slot spent on the walk
     in and still cooling when the fight started is its own finding: say "fought without
     <ability>" with the press's time and context. Whether a ready ability could have
     got them out here is your call from the kit and the stills; make it, and mark it as
     inference when it rests on things the stills don't show (cover beside, a ledge, allies).
   - Focus: whether this death tested the current focus, and how the player did.
   - Pipeline issues: anything the stills contradict in the packet (not a death, wrong
     killer, missed kill cam, wrong hero), or "none".

5. When every death is written, reply with one line per death: "<ID>: <category>: <cause in 15
   words or fewer>".
```

## Overview brief

```
You are reading part of an Overwatch 2 match from contact sheets, for a coach who will not see
the images. Record what the sheets show; another session writes the coaching.

Packet folder: <PACKET>
First-pass sheets (clock <FROM> to <TO>): <SHEET FILES, in order>
Extra sheets for this window: overview_NNNb.jpg next to each overview_NNN.jpg above.
Player <PLAYER> (<HEROES>). Deaths in this window: <dNN clock, ...>. Ults: <uNN ready/used clock, ...>.
Fights in this window (from the HUD: HP changes, kills, deaths, ults): <from-to, from-to, ...>.
Low-HP episodes in this window (packet hud_game.low_episodes): <clock, min HP, every slot's state at the start, what was pressed before and during, outcome; ...>.
Presses in this window with context travel / engage / low (packet hud_game.presses): <clock slot context HP; ...>.
Current focus (from the player's lessons file): <FOCUS>
Rubric: <SKILL_DIR>/references/rubric.md. Read its "Overview sheets" and "Blind spots" sections first.

Each cell is a thumbnail of the player's screen, labelled with the game clock, alive / DEAD, and
the ids of deaths (dNN), ults (uNN-ready / uNN-USED), final blows (kNN) and round starts. The
first-pass cells are 5 s apart and each label covers its whole 5 s. Each extra sheet
overview_NNNb.jpg holds the two cells 2.5 s after those of overview_NNN.jpg. Read position and
team shape; HP only where it's legible.

1. Read the first-pass sheets in batches of 10: one message with 10 Read calls, then the next
   10. Never one sheet per message: a turn per image is what made this slow.
2. Extras: open up to 15 `b` sheets where 5 s hides something you need: a fight's start or
   turn, a save, the seconds before a death, a rejoin. The fights list says where to spend
   them; the cells between fights are walking and need one line each. Open them in one message.
3. Write <PACKET>/notes/overview_<NN>.md in exactly this shape:

   # Overview <NN>: <FROM> to <TO>
   ## Cells
   One line per cell read (first pass and extras, in time order; mark extras with *): clock | alive / DEAD | where the player is (with tank, behind team,
   off-angle, alone, spawn, walking back) | team shape and fight state | labels.
   ## Fights
   Each fight: start and end clock, outcome, what the player did, the cells that show it.
   ## Good plays
   Clock, what happened, why it's worth keeping. "None seen" is a valid answer.
   ## Focus tests
   Clock, the situation, how the player handled it. Include every low-HP episode in the
   window that the player survived: what the cells show them doing (cover, teammates) while
   low, and which slots the facts say were ready or cooling.
   ## Before deaths
   For each death in the window: the cells before it, and where the player stood compared
   with where they usually stand in this window.
   ## Rejoins
   After each DEAD run: seconds from respawn to the next fight, and whether they walked in
   alone or with the team.

4. Reply with one line: "overview_<NN>: <fights> fights, <good plays> good plays, <focus tests> focus tests".
```

## Ults brief

```
You are reading the ultimates from an Overwatch 2 coaching packet, for a coach who will not see
the images. Record what the stills show; another session writes the coaching.

Packet folder: <PACKET>
Player <PLAYER> (<HEROES>). Ults: <uNN outcome held_s, ...>.
Rubric: <SKILL_DIR>/references/rubric.md. Read its "Ults" and "Blind spots" sections first.

1. In <PACKET>/packet.json read ults[] in full, and for each ult the timeline, deaths,
   final_blows and alive_series entries in its hold window (ready to used).
2. Read every ult's stills in ONE message (one Read call each, all sent together).
3. Write <PACKET>/notes/ults.md in exactly this shape:

   # Ults
   ## uNN <ready clock> to <used clock>: <hero>, <outcome>, held <held_s> s
   | still | dt | what it shows (allies, enemies, effect, notices) |
   - Hold window: the fights in it (from the timeline and alive counts) and whether the ult
     could have changed one.
   - Use: early or late in the fight, combined with team ults if visible, what it achieved.
   (one section per ult)
   ## Ults read
   One line per ult: good / questionable / wasted, and why.

4. Reply with one line: "ults: <n> read, <one-line summary>".
```

## Writer brief

```
You are writing the coaching report for one Overwatch 2 game. Readers have already looked at
every image and written notes; you judge from those notes.

Game folder: <GAME>   (packet in <GAME>/packet, notes in <GAME>/packet/notes)
Player <PLAYER>. Lessons file: <LESSONS> (read it; don't edit it).
Trend: <SESSION>/trend.json (the output of `owcoach trend`; don't run it again).
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
Skill: <SKILL_DIR>/SKILL.md. Read section 3 from "What the writer does", all of section 4 up to
the session summary, and section 6. Rubric: <SKILL_DIR>/references/rubric.md.
<ANY RUN-SPECIFIC CONSTRAINTS FROM THE USER, e.g. citation rules>

1. Read two files, both in one message: <GAME>/packet/packet_slim.json (the packet without
   frame lists, the 2 fps series and the raw HUD arrays; each death's facts, HUD summary and
   movement trace are in it, and everything you judge from) and <GAME>/packet/notes/all.md
   (every notes file in reading order: overview chunks, deaths, ults). Don't open packet.json,
   don't read the notes one by one, and don't run python to slice anything: each extra turn
   re-reads your whole context.
2. Judge, as section 3 says. Open stills yourself only to settle a conflict between notes or a
   claim behind a habit, at most 6.
3. Write <GAME>/packet/coaching.md as section 4 says.
4. Write <GAME>/packet/notes/summary.md for the session summary and the lessons file, in exactly
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

5. Reply with one line, "<map>: <verdict>", and nothing else. The report is in the file;
   every word in the reply beyond that line is paid for twice and read by nobody.
```
