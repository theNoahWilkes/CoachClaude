# Rubric: support first

What to check, in order, and how to judge it. Rule flags in `packet.json` are leads; the stills
decide.

## Deaths

**Classify each death first.** Use `alive_before` / flags plus the stills:

| Flag | Means | Usual question |
|---|---|---|
| `first_down` | 5v5 just before: nobody else had died yet | The most actionable death for a support. What exposed the player first: a sightline, overextending to heal, a flanker? |
| `team_behind` | the team was already down players | Was the fight lost before this? Then the mistake is staying, not the death itself. When should they have disengaged or saved a cooldown? |
| `team_ahead` | the team was up players | Losing a won fight. Overchasing, or healing in the open? |
| `even_fight` | equal counts, below 5v5 | Trade or fight in progress. Usually depends on the stills. |
| `short_life` | died within 20 s of respawning | Walking back alone, or into a fight the team had already lost (staggering). |
| `repeat_killer` | 3+ deaths to the same player | A pattern: the same flanker, sniper or dive. Name the counter-habit. |
| `died_with_ult` | ult was ready at death | Should it have been used to survive or to win that fight? |
| `died_after_ult` | died within a second or two of using ult | Used it as a last resort, or ulted from an exposed spot? |
| `overtime` / `contested` | died on the objective at a critical time | Costly. Was it necessary to touch, or could they have stalled from cover? |

**In the death stills (`lead_in` at -10 / -6 s, `detail` every 0.5 s from -3 s to the death, with 0.1 s extras on demand), look for:**
- **Cover:** is there a wall or corner within a step or two? Was the player standing in the open?
- **Teammates in view:** blue outlines or name tags, especially the tank. Isolation is the most
  common support death. If no teammate is visible in the last few seconds, say so.
- **Distance:** is the player ahead of the tank, or far behind and alone?
- **Health:** `hud.hp` in the packet (read locally every 0.1 s; `hud.summary` has it every
  0.5 s). Did it drop over several frames (sustained pressure they could have left) or in one
  step (burst, one-shot, or a combo)? `hp_zero_dt` is when they actually died.
- **Who is who:** blue outlines / names are teammates, red are enemies. Check before saying who
  was on the player; a teammate healing them is not an attacker.
- **Notices:** the centre-bottom notices name what happened ("CHAINED ANRAN (MIKLAXGB)" is the
  player's own ability landing, "SAVED BY …", "YOU WERE ELIMINATED BY …"). Read them; they settle
  kit questions better than effects do.
- **Unspent perk:** an orange "SELECT PERK" prompt on the HP bar means a perk was available and
  not taken. Worth a line if it's there during a fight.
- **Facing:** what were they looking at? The kill cam shows where the killer was. If the killer
  was behind or above the player's view, that's an awareness point.
- **Ability state:** `hud.abilities` in the packet: each slot (left to right as on the HUD)
  is ready, cooling with its countdown, or blocked (red slash: can't be used, e.g. a platform
  already placed). An escape on cooldown through the whole window and one pressed in the
  window are different lessons; the countdown tells you which. Don't guess kits from icons.
- **Was there a way out?** The pipeline gives the facts (which slots were ready, what each
  was last used for, the countdowns); you know the kits. Judge whether what was ready could
  have got them out here, and mark it as inference when it rests on the scene (cover beside
  for a horizontal dash, a ledge for a platform, a teammate for a teleport). A slot spent on
  the walk in and still cooling when the fight started is "fought without it", and the press
  that spent it is the mistake, not the death.
- **High ground:** whether the player or the killer had it.
- **Movement and initiative are mostly inference.** The facts block's "Movement" line gives the
  camera's turn and the body's motion (forward / back / strafe, jumps for a dash or teleport)
  from optical flow between the 0.1 s stills, camera-relative, with "no stable read" where it
  couldn't tell. Use it for which way the player moved; which way that was relative to the
  enemy or to cover is still yours from the stills. Stills are snapshots, so they don't show which way
  a dash or a step went, or who walked up to whom. Don't write "dashed into the enemy", "chose to
  stay and duel" or "walked into" from stills alone. Say what the frames show (positions, ranges,
  HP) and mark the movement or the initiative as inference. Only claim it when the same fixed
  landmark (a wall, a car, the payload) is visible in consecutive frames and the player's position
  against it clearly changes. A duel the enemy started (a dive, a flanker running past the tank)
  is a different lesson from one the player chose. Found on Havana d08: every reader called it a
  chosen duel, but the enemy Moira had run past the tank to the player, who then dashed *away*.

**Kill cam (killer's view):**
- **The angle:** flank, high ground, long sightline, or in front with the team?
- **The killer's hero:** from the player card at right, or their weapon.
- **Whether the player was visible for a long time before dying:** a sightline they should
  have broken.

**Avoidable versus no credible lever.** Count it as no credible lever when 3+ teammates were
already down and the player was at a sensible position, or when it was burst (an ult, a combo)
with nothing in the player's kit to answer it. Count it as avoidable when the player was first
down, isolated, or in a sightline with cover nearby. Say "inference" when the stills don't show
enough.

**Categories.** Give each death (and each notable ult) one or more of these (adapted from a
friend's replay coach, devonbutler/overwatch-replay-coach):

| Category | Means | Example |
|---|---|---|
| Recognition | didn't see the threat or the opportunity | the Genji on the roof never in view before the dive |
| Decision | saw it, chose a low-value response | took a 1v1 with a diving Anran instead of backing to the team |
| Execution | the plan was fine, the mechanics or timing failed | missed the Binding Chain on a target in the open |
| Positioning | exposed before mechanics mattered | peeking the same lane at half HP |
| Resource discipline | a cooldown, ult or escape used at the wrong time or for the wrong purpose | Fade spent, then stayed in the fight; ult held through the deciding fight |
| No credible lever | nothing realistic would have changed it | 2v5, or a RIP-Tire after the player killed the Junkrat |

Don't turn every death into an individual error, and don't claim execution from a blurry frame.
"This play failed" is not the same as "this decision was wrong".

## Focus grade

Each match report gives each focus a **stoplight**: green, amber, red or not tested. Grade it
from the list of situations that tested it, not from an overall feel.
Two runs on the same game gave different grades (Havana, 2026-10-15), so use this test:

1. List every test. That's each situation where the focus's trigger happened, in the deaths and in
   the overview. Mark each one **held** or **broke**, with its clock or death id. For a focus about
   HP or an escape, the tests are `hud_game.low_episodes` in the packet (every stretch under half
   HP, with the escape's state when it started, whether it was pressed, and the outcome), read
   locally; use them as the list, and the readers' notes for what the stills add (cover, who was
   there). A focus about leaving when the team is down two is graded from the facts alone: each
   down-two window (`focus_tests`, kind `down_two`) the player lived through is held, each that
   ended in their death is broken. "Down two" is a diagnosis on a death; whether a player who
   lived left a few seconds late is out of scope (the player, 2026-10-29).
2. Grade by the count:
   - ⚪ **Not tested:** no tests.
   - 🟢 **Green:** held in at least 3 of 4 tests, and no avoidable death was caused by breaking it.
   - 🔴 **Red:** held in fewer than half the tests, or breaking it caused 3 or more avoidable deaths.
   - 🟡 **Amber:** anything in between.
3. Write the count with the stoplight, e.g. "🟡 held 6 of 11".

A focus can have parts (e.g. "use the escape" and "with the escape down, stay in cover"). Then
count each part on its own, and give the focus the lower of the two stoplights.

The stoplight is the match report's whole say on the focus. What the tests showed, in plain
words, is the session summary's (SKILL.md section 4).

## Overview sheets

The cells are thumbnails every 5 s (2.5 s with the extra sheets); read team shape and position, and HP only where it's legible. Look for:
- **Where the player stands while alive:** with the tank, on an off-angle, or alone. Compare it
  with where they stood just before their deaths.
- **Fights won without a death**, and what the player did in them. These are the behaviours to
  keep; a standout one is a moment worth nominating.
- **Situations that test the current focus** whether or not they ended in a death.
- **Time between respawn and rejoining** (DEAD runs, then the first alive cells): walking in
  alone, or waiting for the team.

## Ults

- **Held long** (`held_long`, 45 s or more): find fights in the hold window. Deaths, final blows,
  score/progress changes and `alive_series` dips are fights. A support ult held through a lost
  fight is the main thing to call out.
- **`died_with_it`:** usually the biggest ult mistake.
- **Uses:** check the alive counts and the stills around the press. Was it used at the start of
  the fight (good for most support ults), or late in a fight that was already lost? Was it combined
  with the team's ults? You can only see that if it shows in the stills.
- **`ult_lost_on_swap` / `ult_held_to_end`:** wasted charge. Note it once, briefly.

## Heroes and swaps

- Swapping after repeated deaths to one player is a good reaction. Name it if it worked (fewer
  deaths after it).
- If the same problem continues after the swap, the hero wasn't the issue.

## Objective and time

- Deaths in overtime or while contested cost the most. Check whether the player could have
  stayed alive and contested from cover.
- Staggering: deaths shortly after a team wipe on the timeline mean the player went back in
  before the team regrouped.

## Stats (packet `stats` and `owcoach trend`)

- **Per 10 min of match clock:** deaths, time dead (% of match), healing and damage. Compare them
  with the other support (same team, same game) and the enemy supports. This is the fairest
  comparison because the game and the fights were shared.
- **Hero matters:** Lifeweaver and Mizuki heal more and damage less than Moira or Zenyatta. The
  trend's `by_hero` gives the player's own norms per hero.
- **Trend verdicts:** `better`/`worse` means at least a 10% change and two standard errors from
  the baseline. Report those; otherwise say it's normal variation. Below 5 baseline games, say
  there isn't enough history.
- Numbers frame the coaching; don't build points on them alone. A high death rate is explained by
  the deaths themselves.

## Blind spots

Say these out loud rather than guess.

- **No teammate positions** beyond what's in the player's view.
- **Overview cells are 5 s apart in the first pass** (2.5 s with the extras): a quick pick can
  fall between two cells.
- **No assists, no ult charge %.**
- **No healing over time:** only end-of-game totals. The player's own HP over the whole game
  is in `hud_game.series` (2 fps), and every 0.1 s around deaths in each death's `hud`.
- **Names are OCR'd:** O/0 and I/l mix-ups are possible. `killed_by` groups are already merged.
- **New heroes:** Doctrine, Mizuki and others released after your training data. Don't assume
  their kits: use the hero note if the packet lists one (`hero_notes`, from the wiki; paths relative to the profile dir), the
  key labels in the stills and the cooldown lengths the HUD reader learned, and otherwise
  describe what the stills show.
- **Death times:** `anchor` "banner" means the time comes from the elimination banner (within
  ~0.25 s); "feed" means it's the kill-feed sighting minus 0.5 s and can be seconds late (no banner:
  menu open, spectating). With a feed anchor, check the detail stills actually show the death.
- **Kill cams:** about a third of deaths have none, because the game or the player skipped it.
