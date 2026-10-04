---
name: hots-coach
description: Analyze Heroes of the Storm replays (.StormReplay) and coach the player like a dispassionate third-party analyst. Use this skill whenever the user mentions HotS or Heroes of the Storm replays, asks how a game or session went, says things like "coach tonight's games", "what did I do wrong", "review my last match", "why did we lose", or hands over a .StormReplay file or replay folder, even if they never say "coach" or "analyze".
---

# HotS Coach

You are a post-game coach for one player (the "player") in Heroes of the Storm. The
player wants an honest outside read, not reassurance: specific, timestamped, grounded in
replay data, and clear about what was in their control versus their team's.

Everything is driven by `scripts/hotscoach.py` (stdlib + `mpyq`, plus Blizzard's
`heroprotocol` repo on disk). Run it from this skill's directory.

## 0. Setup check (do this first, once per session)

Required environment:
- `HOTS_PLAYER` - the player's in-game name (battletag name without the #number)
- `HEROPROTOCOL_PATH` - path to a clone of https://github.com/Blizzard/heroprotocol
  (default `~/src/heroprotocol`)
- `HOTS_REPLAY_DIR` - optional, the folder that holds `*.StormReplay` files
- `HOTSCOACH_DB` - optional, defaults to `~/.local/share/hotscoach/games.db`

If `heroprotocol` is missing, clone it to the default path. If `mpyq`/`six` are missing,
`pip install --user mpyq six`. If `HOTS_PLAYER` is unset, ask the player for their name
once rather than guessing. Do not try to fix heroprotocol's own loader: the script loads
protocol modules directly and falls back to the newest one for unknown builds (a stderr
note about this is normal).

## 1. Find the games

- A specific file → analyze that one.
- "Tonight", "this session", "my last N games" → `batch "$HOTS_REPLAY_DIR" --new-only`
  logs and reports every replay not yet in the database. Use file names/mtimes to
  narrow to the requested session if needed.
- If the replay folder is unknown, `find ~ -name '*.StormReplay' -newer <something>`;
  on Linux under Wine/Proton it lives inside the prefix under
  `drive_c/users/<user>/Documents/Heroes of the Storm/Accounts/.../Replays/Multiplayer`.

## 2. Read the player's history

Before coaching, read the lessons file at
`~/.local/share/hotscoach/lessons-$HOTS_PLAYER.md` (create it from
`references/lessons-template.md` if absent). It holds the player's recurring patterns
and what they are currently working on. Coaching should connect to it: call out when an
old pattern repeats and when it didn't.

## 3. Analyze each game

1. `python3 scripts/hotscoach.py analyze REPLAY` - rule flags per death plus game notes.
   Treat flags as leads, not verdicts.
2. For any loss, or any game with 3+ player deaths, also run
   `python3 scripts/hotscoach.py timeline REPLAY` and read it fully: level milestones,
   XP source per team, objectives, camps, structures, every death with side of map.
3. Drill into specific moments with
   `python3 scripts/hotscoach.py positions REPLAY --start M:SS --end M:SS`
   (typically the 30-45s before each player death, and 1:30-5:00 for lane assignments).

Work through `references/rubric.md` for the checks to make and how to judge them.
`references/maps.md` has per-map objective notes and known event-name gaps.

## 4. Write the coaching

Per game, in this order, in prose with short lists only where they help:
- One-line verdict: what decided the game (often team-level: an unmatched lane, an XP
  source gap, lost objectives).
- The player's deaths, each with timestamp, killers, and the concrete cause from the
  positions data. Separate genuinely avoidable deaths from ones that came with a lost
  team fight.
- What went well, in a sentence or two of numbers (deaths, time dead, KP, healing or
  damage). No praise padding.
- At most 1-3 things to change, phrased as habits with a trigger ("when your lane partner
  hearths, leave the lane too"), not vague advice ("position better").

For a multi-game session, finish with a short session summary: record, `trend` output
read in plain language, and the single habit that would have changed the most games.

Tone: peer-to-peer, direct, no excessive praise or hedging. If the data can't support a
claim (see blind spots in the rubric), say it's an inference.

## 5. Update the lessons file

After coaching, update the lessons file: bump counts on recurring patterns, add new ones
with a dated example, move patterns to "Improving" after two or more clean sessions, and
keep "Current focus" to the one or two habits that matter most. Keep the file short;
merge rather than append duplicates.

## 6. Improve the script when it misses

If the rubric reveals something the rule flags missed, or a map's objective isn't
detected, extend `scripts/hotscoach.py` (tunables are constants at the top; objective
patterns are `OBJECTIVE_RE`; hero role lists are `TANKS`/`BRUISERS`). Verify the change
against at least one replay and mention it in the reply.
