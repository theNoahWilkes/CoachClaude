# CoachClaude

Post-game coaching for **Overwatch 2** (from ShadowPlay recordings) and **Heroes of the Storm**
(from replay files), driven by Claude Code skills. Each coach has two layers:

- a local, deterministic CLI that turns your recordings or replays into facts: per-game
  clips, stills, kill-feed and HUD reads, rule flags, per-game stats, a game log for trends;
- a Claude Code skill that coaches from those facts like a dispassionate third party, writes a
  report per game and per session, and keeps a lessons file with the habit you're working on.

Everything the coaches write goes to one page per game you can open and browse:
`coaching.html`, with every session, game, report, still and clip linked. It opens in your
browser when coaching finishes, and `setup` puts a **CoachClaude** shortcut on your desktop
that opens it any time (delete it if you don't want it; it won't come back).

The page has buttons. On **Focus**, turn your focus items on and off (up to three; one or two is
best), see the coach's new ideas, and add your own. On each day, **Compress this day** shrinks
that day's match clips to about a third for keeping (re-encoded on the GPU, in the background). The desktop shortcut starts
a small server on your own PC (`owcoach serve`, reachable from nowhere else) so the buttons
work, and it stops by itself once the page has been closed for a while. Opened as a plain file,
each button copies its command for a terminal instead.

## Install

Install a release (a tag such as `v0.2.0`; the latest is on the releases page):

```
pip install "coachclaude[ow,hots] @ git+https://github.com/theNoahWilkes/CoachClaude@v0.2.0"   # or just [ow] or [hots]
npm install -g @anthropic-ai/claude-code
```

That puts `owcoach` and `hotscoach` on your PATH. Then, once:

```
owcoach install-skill                  # copies both skills into ~/.claude/skills (hotscoach install-skill does the same)
owcoach setup --from "<a recording with gameplay>.mp4"   # Overwatch: tools check, config, your nameplate
hotscoach setup                        # HotS: finds your replays, detects your name
```

`owcoach --version` (or `hotscoach --version`) says what you're running; the page footer,
`packet.json` and `analysis.json` carry the same number, so a report can be tied to a build.
To upgrade, run the pip line with the new tag and `install-skill` again.

To work on the code instead, clone it and install editable:

```
git clone https://github.com/theNoahWilkes/CoachClaude && cd CoachClaude
pip install -e ".[ow,hots]"
owcoach install-skill                  # from a checkout this links the skills, so editing the repo edits the live skill
owcoach config dev on                  # developer mode, see below
```

Both read one config file, `~/.config/coachclaude/config.json`, with a section per game, and
keep their data under `~/.local/share/coachclaude/{ow,hots}/` (and, for Overwatch, a video
library, default `~/Videos/owcoach`). Nothing is written next to your recordings or replays.

Without pip, the HotS script runs on its own: `uv run hotscoach.py setup` (uv installs its
dependencies from the script header).

### Developer mode

By default the coaches behave like a released product: the skills coach with the pipeline as
it is and, when a rule misfires, write the miss under "Pipeline issues" in the game's
`coaching.md` instead of editing code, and nothing mentions what a review costs. With
`"dev": true` at the top of the config (`owcoach config dev on`, or `COACHCLAUDE_DEV=1` for one
command) the skills may fix the pipeline when it misses and `owcoach coach` prints its dollar
estimate before it starts. Keep it off when you're testing what another player will get.

## Overwatch 2

Needs ffmpeg (full build) and Tesseract: `winget install Gyan.FFmpeg UB-Mannheim.TesseractOCR`.

In Claude Code, from anywhere: *"coach last night's games"*. The skill lists the new
recordings, runs the pipeline and the per-game coaching, and reads the summary back. Or:

```
owcoach new                 # recordings not in the library yet
owcoach coach --new         # process + coach them (one claude process per game; -y skips the prompt)
owcoach coach "2026.10.16 - 22.23.04.03" --games "m01"   # re-coach one game
owcoach focus               # the coach's focus proposal; `focus 2 4` picks, `--on/--off/--add "..."` toggles
owcoach serve               # the page with working buttons (what the desktop shortcut runs)
owcoach compress 2026-10-25        # shrink a day's match clips for storage (GPU)
owcoach run "<stem>"        # only the local stages, no coaching
owcoach site --open         # <library>/coaching.html (default ~/Videos/owcoach)
owcoach trend --role support
```

`<library>/<session>/mNN_result_mode_map/` holds the clip, `match.json` and `packet/`
(`packet.json`, facts and stills per death, `moments.m3u` for VLC, the coach's `coaching.md`).
`docs/ow/pipeline.md` documents every stage and its known limits. Calibrated for a 21:9 game
area (auto-cropped from a 32:9 capture), HDR10 tonemapped.

## Heroes of the Storm

```
hotscoach batch --new-only                        # analyze + log new games, write their folders
hotscoach analyze game.StormReplay [--json]       # one game
hotscoach timeline game.StormReplay               # levels, XP by source, every death/objective/camp
hotscoach positions game.StormReplay --start 4:00 --end 4:30
hotscoach trend --last 20 [--hero Rehgar]
hotscoach site --open                             # <data>/coaching.html (~/.local/share/coachclaude/hots)
```

In Claude Code: *"coach tonight's games"*, *"why did we lose the last Dragon Shire?"*. Each
game gets `games/<session>/<game>/{analysis.json, timeline.txt}` under the data folder and the
skill writes `coaching.md` beside them (and one per session). The match page also shows a death
map (`map.svg`, drawn from the replay, no game art): your deaths numbered as in the moments list,
every other hero death, and the buildings, hollow once destroyed. Matches analyzed before it existed
get one when `hotscoach batch` runs again over the replay folder.

Limits: positions are sampled about every 15 s and only for heroes in combat; ability casts
are not in the tracker data; Garden of Terror and Hanamura emit no objective events. The tank
and bruiser lists in the script need updating when new heroes ship. See
`coachlib/skills/hots-coach/references/maps.md` for per-map status.

## Releases

The version lives in `pyproject.toml`. A release is a tag `vX.Y.Z` on `main` with the same
number; a checkout reports `X.Y.Z+dev.<commit>` (`.dirty` with uncommitted changes) so the two
never look alike. The skills ship inside the package (`coachlib/skills/`), so a release
install gets the skill text of that tag and nothing newer.

## Working on CoachClaude

Read [CLAUDE.md](CLAUDE.md) first: the vocabulary, the decisions on record and the known gaps.

## Privacy

Replays, recordings, reports and stills contain other players' names. They live in your data
folders and library, never in the repo (`.gitignore` blocks replays, databases and lessons).
