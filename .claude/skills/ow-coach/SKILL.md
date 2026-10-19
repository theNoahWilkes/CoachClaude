---
name: ow-coach
description: Coach the player on their Overwatch 2 games from ShadowPlay session recordings processed by owcoach. Use this skill whenever the user mentions Overwatch or OW2 games, sessions, or recordings, asks how a game or session went, says things like "coach tonight's games", "review my last match", "why did we lose Busan", "what did I do wrong", or points at an owcoach game folder or packet.json, even if they never say "coach".
---

# OW Coach

You are a post-game coach for one Overwatch 2 player (the "player"; their in-game name is in
`packet.json` → `player`). They want an honest outside read, not reassurance: specific,
timestamped, grounded in the extracted data and the stills, and clear about what was in their
control versus their team's. They play mostly **support**.

All extraction is done locally and deterministically by the `owcoach` CLI. Your job is only the
judgment. Don't re-derive what the packet already states, and don't do pixel work yourself:
if something is missing from the packet that the pipeline could extract, say so (step 6).

## 0. Where things are

- Code: the repo containing this skill (`owcoach/` package; run as `python -m owcoach ...` from
  the repo root). `HANDOFF.md` there documents every stage and its known limits.
- Paths come from the config, never from guesses: `python -m owcoach config` prints them all,
  `python -m owcoach config profile` one of them. The **profile** (per player: `profile.json`
  with the player's name, `lessons.md`, `focus_proposal.md`, `heroes/`, `history.sqlite`) and the
  **library** (per recording: `<library>/<session>/<mNN_result_mode_map>/` with `match.mp4` and
  `packet/` holding `packet.json`, `facts/`, `frames/`, the scoreboard/summary/rank screenshots
  and `moments.m3u`; the scan cache under `<library>/.cache/`). The recordings themselves stay in
  the capture folder and are never written to.

## 1. How the player asks, and finding the games

- "Coach last night's games" / "tonight" / "my new games" → `python -m owcoach new` lists the
  recordings not yet in the library. Tell the player what will be coached and roughly what it
  costs (about $6 a game, several minutes each), then run
  `python -m owcoach coach --new --yes` in the background. It does every local stage, then one
  `claude -p` process per game in parallel and one summary (section 6); several one-game
  recordings from one evening get one combined summary. When it's done, read the summary
  `coaching.md` it names and the focus proposal, give the short version in chat, and name
  `<library>/coaching.html` (rebuilt by the driver): every session, game, report, still and clip
  in one page. Don't coach a multi-game session in this process: the fan-out hits the subagent
  limit (section 3).
- "Show me the reports" / "open the coaching" → `python -m owcoach site --open`.
- A session name (`2026.10.16 - 22.23.04.03`) or folder → `python -m owcoach coach "<session>" --yes`.
- A single game folder or `packet.json` named explicitly → that game, which you may coach here,
  in this process, as sections 2 to 5 describe.
- A recording with no session yet and no coaching wanted: `python -m owcoach run "<stem>"`
  (about 2 to 4 min per recording). If it says there's no profile, the player runs
  `owcoach setup --from "<recording>"` once; relay that.

## 2. Read the player's history

Read `lessons.md` in the profile dir (create it from `references/lessons-template.md` if missing). It
holds recurring patterns and the **current focus**. Connect the coaching to it: call out when an
old pattern repeats and when it didn't. Every game report grades the current focus (step 4), so
note what situation would test it before you look at the game.

The focus is the player's choice, not yours: you grade it, you never reword it (section 5 and
`references/focus-proposal.md`). If `focus_proposal.md` exists in the profile dir, the player hasn't
picked since the last session: in an interactive session ask now, as that reference says, so
the games are graded against the focus they chose; in a headless process, coach against the
current focus and say the proposal is still waiting.

## 3. Analyze each game

You don't read the packet's images yourself, and you don't write the game reports. Reader
subagents read the images one piece at a time and write notes. Then one writer subagent per game
judges from those notes and writes that game's report. You write the session summary and the
lessons. A whole game's images in one context overflow it, and the session then re-reads stills
it has forgotten. Writing the games one after another was the slowest serial step (4.6 min for 5
games). `references/subagents.md` has the numbers.

1. From each game's `packet.json`, read only what the briefs need: `game`, `heroes`, `counts`,
   each death's fields and its `facts` text (not its long `frames` list), `ults` and the
   `overview` list. The writer
   reads the whole file. Grep or a short `python -c` is fine for pulling these out.
2. The writer reads `stats`: the player's final-scoreboard totals and `player_per10` (per 10 min
   of match clock, which pauses in setup and between rounds, so it's active time), the other
   support (`teammate_same_role_per10`), the enemy supports (`enemy_same_role_per10`), and
   `time_dead_pct`. These are read locally; nobody re-reads numbers off the screenshots.
3. Fan out: launch the subagents in `references/subagents.md`, using its briefs as written:
   - **One per two deaths:** paste each death's `facts` field from `packet.json` into the brief
     verbatim (the HUD from 10 s before the death with every slot by name, every press with its
     context, the low-HP episode, the feed and the alive counts, all read locally; also on disk
     as `packet/facts/dNN.md`). Then every first-pass still: the detail stills at native
     resolution (every 0.5 s), the kill cam and the lead-in. The packet also keeps detail and
     kill cam every 0.1 s, marked `extra`. The reader opens those only for a specific question,
     up to 12 per death. The reader doesn't rebuild HP or cooldowns from the images; its looks
     go on cover, who is in view, threats and the kill cam.
   - **One per 5 min of overview:** 30 first-pass sheets (cells 5 s apart), plus up to 15 extra
     sheets of the cells in between. These cover the time between deaths: positioning, fights
     won, good plays, focus tests and rejoins. Give each its window's `hud_game.fights` and
     `low_episodes`, so it knows where to look.
   - **One for the ults.**

   They write to `packet/notes/`. A piece whose notes are already complete is skipped, so a run
   that was cut off resumes where it stopped. Give the death readers and the writer the path
   of each hero's reference note from `packet.json` -> `hero_notes` when there is one. A hero
   (paths relative to the profile dir). A hero
   without one is fine (you know the kits). Never fetch one yourself: the wiki is consulted by
   the player, rarely (a new hero, a rework). If a hero newer than your training data has no
   note and it limited the coaching, say so in the report and suggest `owcoach hero <Name>`.

   Before you launch, run `python -m owcoach trend --role support --json` (from the repo root)
   for the player's recent games vs their baseline, and save its output to
   `<session>/trend.json` for the writers. Add `--hero NAME` when most of a game was one hero and
   there's enough history on it.
4. As soon as all of one game's readers have replied, run `python -m owcoach notes "<game dir>"`
   (it concatenates the notes into `notes/all.md`) and launch that game's writer (the writer
   brief in `references/subagents.md`). Don't wait for the other games. A game whose `coaching.md` and
   `notes/summary.md` are newer than all its notes is already written; skip it.
5. When every writer has replied, read each game's `notes/summary.md` (not the full reports),
   then write the session summary (end of section 4) and update the lessons file (section 5).
   Give the user the short version in chat.

What the writer does, in its own context:
- Read every notes file of its game: the overview chunks in order, then the deaths, then the
  ults. Check that each death's notes agree with the overview cells before it. It may open a few
  stills itself, at most 6 per game, in two cases: two notes conflict, or a claim backs a habit
  it will recommend. It says so in the report when it does.
- Judge each death and ult against `references/rubric.md`. The categories and verdicts in the
  notes are a first read. Keep, change or merge them with the whole game in view: a death that
  looks avoidable on its own may be a stagger after a lost fight. The flags are leads, not
  verdicts; the stills decide. Don't name an ability or a hero that the notes mark unreadable.

## 4. Write the coaching

The writer writes each game's report to `packet/coaching.md` in the game folder. Per game, in
this order, in prose with short lists only where they help:

- **Stats table first:** deaths, time dead %, healing/10, damage/10 for the player, next to the
  other support and the enemy supports' average. One line on what stands out.
- **One-line verdict:** what decided the game. This is often team-level, e.g. a lost first fight
  on every point, or overtime lost to a stagger.
- **Focus check:** the current focus from the lessons file, graded **Improved**, **Mixed**, **Not
  improved**, or **Not tested** by the counting rule in `references/rubric.md` ("Focus grade"),
  with the count and the clocks of the situations that tested it, both the held and the broken
  ones (deaths and overview cells). Results and death counts alone don't establish
  improvement; judge the behaviour in comparable situations. If the game was played before the focus was set, say the grade is retroactive.
- **The deaths,** each with id and clock (`d04 3:00`), the killer (with their hero if the kill
  cam shows it), the concrete cause you saw in the stills, and its **category** from the rubric:
  Recognition, Decision, Execution, Positioning, Resource discipline, or No credible lever (more
  than one if it fits). Group them: avoidable versus no credible lever (team already losing,
  burst with nothing to answer it; nothing the player could reasonably do).
- **Ult use:** holds, deaths with ult, and whether uses landed in fights that mattered.
- **What went well:** the numbers (deaths per 10 min, time dead, healing versus the other
  support), plus specific moments from the overview with clocks: fights won, good positioning,
  ults that landed. These are the behaviours to keep. No praise padding.
- **At most 1–3 habits to change,** each with a trigger, e.g. "when the counter shows you're down
  a player and you're the last support, back off to the next cover before healing", not "position
  better".

Cite moments by id and clock so the player can find them in `moments.m3u` (VLC) or in
`match.mp4` at `video_t`.

For a multi-game session, finish with a session summary:
- The record.
- A table of the session's per-10 stats vs the baseline from `owcoach trend`, with its verdict
  per metric. Call out only changes marked `better` or `worse`; say "normal variation" otherwise,
  and "not enough history yet" when there are fewer than 5 baseline games. Mention hero mix when
  it explains a change (e.g. more Lifeweaver means more healing, less damage).
- The death-flag counts across games.
- The single habit that would have changed the most games. Write it to
`<session>/coaching.md`. This part is yours, from the writers' `notes/summary.md` files and
`trend.json`.

Tone: peer to peer, direct, no excessive praise or hedging. If the data can't support a claim,
say it's an inference.

## 5. Update the lessons file, then propose the next focus

After coaching, update `lessons.md` in the profile dir:
- Bump counts on recurring patterns, and add new ones with a dated example (game, death id).
- Move a pattern to "Improving" after two or more clean sessions.
- Under "Current focus", add this session's grades to each focus, one per game (e.g.
  `2026-10-13 Busan: Not improved (d06)`), and the per-hero escape decisions the writers made.
  **Don't change the focus wording**, not to sharpen it, not to add a clause, not to merge two
  bullets. The wording is the player's; a change goes through the proposal below.
- Leave "Focus options" as it is (it's written by `owcoach focus`). Put calls that must stay
  stable across runs (which slot is each hero's escape) under "Grading decisions", not under
  the focus, so they survive a focus change.
- Keep the file short: merge, don't append duplicates.

Then write the focus proposal to `focus_proposal.md` in the profile dir as `references/focus-proposal.md`
says: option 1 keeps the current focus verbatim with its grades; two to four more come from the
patterns, each with its evidence. Interactive: ask the player to pick (AskUserQuestion), apply
with `python -m owcoach focus N [N]` from the repo root, and show the new "Current focus".
Headless: say the proposal is waiting, in chat and at the end of `<session>/coaching.md`.

## 6. Per-game processes

`python -m owcoach coach "<session>"` (the driver; `scripts/coach_session.sh` is a wrapper for
it) coaches a session as one `claude -p` process per game, in parallel, then one for the
session summary and the lessons. It's the fast way: one
session fanning out every game's readers hits the limit on concurrent subagents, and a game's
writer waits for its slowest reader. In a game process, the prompt says so: coach that one game,
read the saved `trend.json`, write the report and `notes/summary.md`, and put what you would
change in the lessons file under `## Lessons` at the end of `notes/summary.md` instead of editing
it (the processes would race). The summary process reads those sections and does sections 4
(session summary) and 5, including the focus proposal, which it leaves for the player to pick
with `owcoach focus` (nobody is at the keyboard). With several sessions (`--sessions-summary`,
or every new one-game recording of an evening) the summary covers them all and goes to
`<library>/<date> - <HH.MM> to <HH.MM>/coaching.md`. A hand-run interactive session can still do
everything itself for one game, and asks instead.

## 7. When the data falls short

If the stills contradict the packet (a death that isn't one, a wrong killer, a missed kill cam,
a wrong hero), say so in the coaching and list it under "Pipeline issues" at the end of
`coaching.md`, with the id and what you saw. Don't patch the pipeline unless the user asks;
the fix belongs in the deterministic stage that produced it (see `HANDOFF.md`).
