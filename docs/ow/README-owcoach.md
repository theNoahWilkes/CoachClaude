# owcoach

Overwatch 2 session recordings → per-game clips, packets and coaching reports.

Two layers:

- **`owcoach`**, a local, deterministic pipeline: finds the matches in a ShadowPlay recording,
  cuts one clip per game (stream copy), reads the kill feed, HP and ability states off the HUD,
  and writes a coaching packet per game (stills, facts, stats, `moments.m3u`).
- **The `ow-coach` Claude Code skill** (`.claude/skills/ow-coach/`), which coaches from the
  packets: reader subagents per death, a writer per game, a session summary, a lessons file the
  player owns the focus of.

## Setup, once

```
pip install numpy opencv-python markdown-it-py
winget install Gyan.FFmpeg UB-Mannheim.TesseractOCR     # ffmpeg (full build, needs zscale), tesseract
npm install -g @anthropic-ai/claude-code                # the coach
python -m owcoach setup --from "<a recording with gameplay>.mp4"   # tools check, config, your nameplate
python -m owcoach install-skill                          # links the skill into ~/.claude/skills
```

`setup` writes `~/.config/coachclaude/config.json`: the capture folder(s) (ShadowPlay's, found
automatically), the **library** where everything owcoach writes goes (default `~/Videos/owcoach`),
and the **profile** (default `~/.local/share/coachclaude/ow`: your name, nameplate, lessons,
history). Recordings are never written next to. `owcoach config` prints the resolved paths.

## Use

In Claude Code, from anywhere: *"coach last night's games"*. The skill lists the new recordings,
says what it will cost, runs the pipeline and the per-game coaching, and reads the summary back.

Or in a terminal:

```
python -m owcoach new                 # recordings not in the library yet
python -m owcoach coach --new         # process + coach them (asks before spending; -y skips)
python -m owcoach coach "2026.10.16 - 22.23.04.03" --games "m01"   # re-coach one game
python -m owcoach focus               # the coach's focus proposal; `focus 2 4` picks
python -m owcoach run "<stem>"        # only the local stages, no coaching
python -m owcoach site --open         # the page over everything (also rebuilt by run and coach)
python -m owcoach trend --role support
```

Reports: `<library>/<session>/mNN_.../packet/coaching.md` per game, `<library>/<session>/coaching.md`
per session, lessons in the profile. `moments.m3u` in each packet opens the deaths and ults in VLC.

**`<library>/coaching.html`** is all of it in one page: every day, session and game in a sidebar;
per game the stats, scoreboard, a timeline of deaths/ults/final blows, the clip (seek to any
moment), the report, and each moment's stills, facts and reader notes; the session summaries,
the lessons and the focus proposal. Rebuilt by `run` and `coach`; `python -m owcoach site --open`
rebuilds and opens it. Nothing is copied: it links to the files beside it.

Single stages (CACHE = the cache dir, the recording, or its bare stem): `scan`, `segment`,
`events`, `hud`, `split`, `packet`, `init`, `hero`, `notes`. `HANDOFF.md` documents each.

Calibrated for a 21:9 game area (auto-cropped from a 32:9 ShadowPlay capture), HDR10 tonemapped.
Reports and packets contain other players' names; they live in the library, not in the repo.
