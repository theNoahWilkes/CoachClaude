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
git clone https://github.com/theNoahWilkes/CoachClaude && cd CoachClaude
python3 -m pip install -r requirements.txt     # Windows: py -m pip install -r requirements.txt
python3 .claude/skills/hots-coach/scripts/hotscoach.py setup
```

`setup` finds your replay folder (Windows, macOS, Wine/Lutris/Proton/Bottles, WSL),
detects your in-game name from your recent replays, and writes
`~/.config/hotscoach/config.json`. Nothing else to configure.

**Even easier with [uv](https://docs.astral.sh/uv/):** skip the pip step entirely.
The script declares its own dependencies, so this installs them on first run:

```bash
uv run .claude/skills/hots-coach/scripts/hotscoach.py setup
```

If pip complains about an "externally managed environment" (Homebrew Python, some
Linux distros), use uv, or a venv: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

## CLI

```bash
S=.claude/skills/hots-coach/scripts/hotscoach.py
python3 $S batch --new-only                        # analyze + log new games
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

To use it from anywhere, link the skill into your personal skills:

```bash
ln -s "$PWD/.claude/skills/hots-coach" ~/.claude/skills/hots-coach                 # macOS/Linux
cmd /c mklink /J "%USERPROFILE%\.claude\skills\hots-coach" ".claude\skills\hots-coach"   # Windows
```

Your lessons file lives at `~/.local/share/hotscoach/lessons-<you>.md` and your
game log at `~/.local/share/hotscoach/games.db`, both outside the repo, so everyone's
history stays their own.

## Limits

Positions are sampled about every 15s and only for heroes in combat; ability casts are
not in the tracker data; Garden of Terror and Hanamura emit no objective events. The tank
and bruiser lists in the script need updating when new heroes ship. See
`.claude/skills/hots-coach/references/maps.md` for per-map status.

Replays contain other players' names, so don't commit them (the `.gitignore` blocks
`*.StormReplay`).
