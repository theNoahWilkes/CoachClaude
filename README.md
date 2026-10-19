# CoachClaude

Post-game coaching for **Overwatch 2** (from ShadowPlay recordings) and **Heroes of the Storm**
(from replay files), driven by Claude Code skills. Each coach has two layers:

- a local, deterministic CLI that turns your recordings or replays into facts: per-game
  clips, stills, kill-feed and HUD reads, rule flags, per-game stats, a game log for trends;
- a Claude Code skill that coaches from those facts like a dispassionate third party, writes a
  report per game and per session, and keeps a lessons file with the habit you're working on.

Everything the coaches write goes to one page per game you can open and browse:
`coaching.html`, with every session, game, report, still and clip linked.

## Install

```
git clone https://github.com/theNoahWilkes/CoachClaude && cd CoachClaude
pip install -e ".[ow,hots]"            # or just [ow] or [hots]
npm install -g @anthropic-ai/claude-code
```

That puts `owcoach` and `hotscoach` on your PATH. Then, once:

```
owcoach install-skill                  # links both skills into ~/.claude/skills (hotscoach install-skill does the same)
owcoach setup --from "<a recording with gameplay>.mp4"   # Overwatch: tools check, config, your nameplate
hotscoach setup                        # HotS: finds your replays, detects your name
```

Both read one config file, `~/.config/coachclaude/config.json`, with a section per game, and
keep their data under `~/.local/share/coachclaude/{ow,hots}/` (and, for Overwatch, a video
library, default `~/Videos/owcoach`). Nothing is written next to your recordings or replays.

Without pip, the HotS script runs on its own: `uv run hotscoach.py setup` (uv installs its
dependencies from the script header).

## Overwatch 2

Needs ffmpeg (full build) and Tesseract: `winget install Gyan.FFmpeg UB-Mannheim.TesseractOCR`.

In Claude Code, from anywhere: *"coach last night's games"*. The skill lists the new
recordings, runs the pipeline and the per-game coaching, and reads the summary back. Or:

```
owcoach new                 # recordings not in the library yet
owcoach coach --new         # process + coach them (one claude process per game; -y skips the prompt)
owcoach coach "2026.10.16 - 22.23.04.03" --games "m01"   # re-coach one game
owcoach focus               # the coach's focus proposal; `focus 2 4` picks
owcoach run "<stem>"        # only the local stages, no coaching
owcoach site --open         # <library>/coaching.html
owcoach trend --role support
```

`<library>/<session>/mNN_result_mode_map/` holds the clip, `match.json` and `packet/`
(`packet.json`, facts and stills per death, `moments.m3u` for VLC, the coach's `coaching.md`).
`docs/ow/HANDOFF.md` documents every stage and its known limits. Calibrated for a 21:9 game
area (auto-cropped from a 32:9 capture), HDR10 tonemapped.

## Heroes of the Storm

```
hotscoach batch --new-only                        # analyze + log new games, write their folders
hotscoach analyze game.StormReplay [--json]       # one game
hotscoach timeline game.StormReplay               # levels, XP by source, every death/objective/camp
hotscoach positions game.StormReplay --start 4:00 --end 4:30
hotscoach trend --last 20 [--hero Rehgar]
hotscoach site --open                             # <data>/coaching.html
```

In Claude Code: *"coach tonight's games"*, *"why did we lose the last Dragon Shire?"*. Each
game gets `games/<session>/<game>/{analysis.json, timeline.txt}` under the data folder and the
skill writes `coaching.md` beside them (and one per session).

Limits: positions are sampled about every 15 s and only for heroes in combat; ability casts
are not in the tracker data; Garden of Terror and Hanamura emit no objective events. The tank
and bruiser lists in the script need updating when new heroes ship. See
`.claude/skills/hots-coach/references/maps.md` for per-map status.

## Privacy

Replays, recordings, reports and stills contain other players' names. They live in your data
folders and library, never in the repo (`.gitignore` blocks replays, databases and lessons).
