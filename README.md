# hots-coach

Post-game coaching for Heroes of the Storm, from your own replay files.

Two layers:

- **`hotscoach.py`** - a CLI that parses `.StormReplay` files and flags avoidable deaths
  (solo exposure, far from your tank, first down, enemy-half dives, pre-objective deaths),
  shows where XP gaps came from, and logs every game to SQLite for trends.
- **A Claude Code skill** (`.claude/skills/hots-coach/`) that runs the CLI, digs into
  the timeline and positions, and writes coaching like a dispassionate third party. It
  keeps a per-player lessons file so it can tell you when an old habit repeats.

## Setup

```bash
git clone <this repo> && cd hots-coach
git clone https://github.com/Blizzard/heroprotocol ~/src/heroprotocol
pip install --user mpyq six

# in your shell rc
export HOTS_PLAYER=YourName                 # in-game name, no #1234
export HEROPROTOCOL_PATH=~/src/heroprotocol
export HOTS_REPLAY_DIR="/path/to/Replays/Multiplayer"
```

Replays live under `Documents/Heroes of the Storm/Accounts/<id>/<region>-Hero-1-<id>/Replays/Multiplayer`.
On Linux with Wine/Proton that is inside the prefix's `drive_c/users/<user>/`.

`heroprotocol` on PyPI is stale and breaks on Python 3.12; the script loads protocol
modules from the GitHub clone directly and falls back to the newest one for new builds.

## CLI

```bash
S=.claude/skills/hots-coach/scripts/hotscoach.py
python3 $S batch "$HOTS_REPLAY_DIR" --new-only     # analyze + log new games
python3 $S analyze game.StormReplay [--json]       # one game
python3 $S timeline game.StormReplay               # levels, XP by source, every death/objective/camp
python3 $S positions game.StormReplay --start 4:00 --end 4:30
python3 $S trend --last 20 [--hero Rehgar]
```

## With Claude Code

Run `claude` from the repo root; the project skill loads automatically. Then:

```
coach tonight's games
why did we lose the last Dragon Shire?
```

To use it from anywhere, symlink the skill into your personal skills:
`ln -s "$PWD/.claude/skills/hots-coach" ~/.claude/skills/hots-coach`

Your lessons file lives at `~/.local/share/hotscoach/lessons-$HOTS_PLAYER.md` and your
game log at `~/.local/share/hotscoach/games.db`, both outside the repo, so everyone's
history stays their own.

## Limits

Positions are sampled about every 15s and only for heroes in combat; ability casts are
not in the tracker data; Garden of Terror and Hanamura emit no objective events. The tank
and bruiser lists in the script need updating when new heroes ship. See
`.claude/skills/hots-coach/references/maps.md` for per-map status.

Replays contain other players' names, so don't commit them (the `.gitignore` blocks
`*.StormReplay`).
