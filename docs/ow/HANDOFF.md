# owcoach — passdown for Claude Code

Written 2026-10-14 at the end of the first working session (claude.ai cloud session, linked to
Noah's Windows PC). Read this before touching anything.

## Who / what

- **User:** Noah. Strong Python + CLI person, runs a homelab (Proxmox, TrueNAS, UniFi, Docker).
  Prefers terminal workflows and a peer tone. Plays Overwatch 2, mostly **support**.
- **Project:** `owcoach`, the Overwatch follow-on to his Heroes of the Storm coach
  (`theNoahWilkes/CoachClaude`: Python CLI that extracts data + a Claude Code skill that coaches).
  Same split here: deterministic local extraction, then Claude does the judgment.
- **End-state workflow he wants:** record a whole session with ShadowPlay, then split it into
  games and analyze them **in minutes, ideally seconds**. Coaching for support first, all roles later.

## Where things are (since 2026-10-18)

**The repo is CoachClaude** (`github.com/theNoahWilkes/CoachClaude`, local clone under
`~/source/repos/CoachClaude`): `owcoach/` (this package), `hotscoach.py` (the Heroes of the
Storm coach, one file), `coachlib/` (what they share: `config.py`, the one config file with a
section per game, `site.py`, the page renderer, `version.py` and `install.py`), the skills as
package data in `coachlib/skills/{ow-coach,hots-coach}/` (since 2026-10-20; they were
`.claude/skills/` before), `docs/ow/` (this file, the labels). `pip install -e ".[ow,hots]"`
puts `owcoach` and `hotscoach` on PATH; `owcoach install-skill` links both skills into
`~/.claude/skills` from a checkout and copies them from a release install, so a player on a
tagged version runs that tag's skill text. Developer mode (`owcoach config dev on`, the
top-level `dev` key of the config) is what lets the skills edit the pipeline and shows the
cost estimate; off by default, off on every released install.
owcoach came in squashed on 2026-10-18 (its 55-commit history stays in the old repo under
`Videos/NVIDIA/Overwatch 2/owcoach/src`, now an archive).

`owcoach/config.py` owns every OW path. `~/.config/coachclaude/config.json` names the capture
folder(s), the **library** (`~/Videos/owcoach` by default: `<session>/` folders, `.cache/<stem>/`
scan caches) and the **profile** (`~/.local/share/coachclaude/ow`: profile.json,
nameplate, portraits, hud_layouts, history.sqlite, lessons.md, focus_proposal*.md, heroes/).
`python -m owcoach config` prints them. The recordings stay in the ShadowPlay folder and are
read-only input. `owcoach new` / `run` / `coach` / `site` are the user-facing commands (README). The
driver is `owcoach/coach.py` (`scripts/coach_session.sh` is a wrapper now). `owcoach/site.py`
renders `<library>/coaching.html` over every session and game (`collect()` knows the owcoach
layout, `render()` is generic so the HotS coach can share it); `run` and `coach` rebuild it.

## Lessons from session 1 (don't repeat)

- **The previous session ran in a bad environment.** The only code execution next to the files
  was the Claude desktop app's sandboxed Linux VM: 2 cores, 3 GB RAM, no GPU, a 3-minute cap per
  command, files reached over a ~12 MB/s share. Cloud staging is capped at 400 MB per file, and
  the recordings are 27–37 GB. Everything slow about session 1 (chunked/resumable scans, the
  `--budget` flag, the PowerShell cut script) was a workaround for that. **Run on the metal.**
- **Deliver the asked-for thing first.** About half of session 1 went into extras (map OCR,
  hero names, scoreboard/summary/rank grabs, match clock) before any clip existed. Noah called
  that out. Get clips out, then add features, and flag environment limits as soon as you see them.

## Recording facts (measured from his files)

| Property | Value |
|---|---|
| Recorder | NVIDIA ShadowPlay, manual record, files in `~\Videos\NVIDIA\Overwatch 2\` |
| Naming | `Overwatch 2 YYYY.MM.DD - HH.MM.SS.NN.mp4` |
| Capture | **5120×1440** (32:9 monitor), game renders **21:9 = 3456×1440 at x=832**, black pillars either side |
| Codec | **HEVC Main10, HDR10** (PQ / BT.2020, full range), 60 fps nominal, VFR |
| Bitrate | ~61 Mbps (≈27.6 GB/h). Suggest lowering to ~15 Mbps and turning HDR capture off |
| GOP | **keyframe every 0.5 s**, so `-skip_frame nokey` gives a free 2 fps sample and `-c copy` cuts land within 0.5 s |
| Audio | AAC 192k |
| In-game | default HUD; OW performance overlay on (FPS/TMP/LATENCY/IND/clock, top-right); player name **SIXN** |

The 21:9 crop is auto-detected (`probe.detect_crop`). HDR is tonemapped with
`zscale → tonemap=hable → zscale` (`scan.TONEMAP`). If the recording changes (SDR, different
resolution or aspect), the HUD template and pixel ROIs below **must be recalibrated**: they are
in 1280-wide, tonemapped, cropped-thumbnail coordinates.

## Code layout (`owcoach/`, ~1,000 lines, Python 3.10+, deps: numpy, opencv-python, ffmpeg, tesseract)

```
owcoach scan    SESSION.mp4 [--jobs 2] [--chunk 600] [--budget S]
owcoach segment CACHE
owcoach split   CACHE [--cut here|script|none] [--pad 3]
owcoach sheet   CACHE [--every N] [--labels]          # contact sheets for eyeballing
```
Cache: `<library>/.cache/<video stem>/` (`config.cache_for`; `scan.json`, `index.json`,
`frames/<chunk>/*.jpg`, `features.npy`, `matches.json`, `states.json`, `events.json`, `hud.json`).
Every CACHE argument also accepts the recording path or its bare stem (`config.resolve_cache`).

- `probe.py`: ffprobe wrapper (HDR flag, VFR flag), keyframe listing, black-bar crop detection.
- `scan.py`: keyframe-only decode → crop → scale 1280 → tonemap → JPEG thumbnails, with timestamps
  from `showinfo` (uses `-copyts`, so they're absolute). Chunked + resumable + parallel. `grab_frame()`
  pulls one full-res (or ROI) frame straight from the source video for OCR/stills.
- `segment.py`: per-frame features + match logic (details below).
- `split.py`: per-match bundle folders; `--cut here` runs ffmpeg, `--cut script` writes `cut_matches.ps1`.
- `sheet.py`: contact sheets. `assets/hud_ref.png` is the HUD template (frame[420:534, 0:300] of a
  spawn-room thumbnail).

### Detection logic (segment.py)

Per thumbnail (cached in `features.npy` as `[t, hud, dx, tab]`):
- **HUD (hero-agnostic)**: three bottom-left anchors matched as Sobel-gradient templates: "+"/HP
  readout `(84,434,140,452)`, health pips `(84,450,176,472)`, nameplate bar `(84,474,204,500)`.
  Searched ±36 px horizontally because the HUD block shifts with the hero's portrait frame
  (about +13 px on his 2nd hero). Score = best `min(a,b)` over anchor pairs whose x-offsets agree
  within 3 px. Threshold 0.40. The portrait hexagon is **not** usable (cosmetic frames vary by hero).
  The ult ring didn't template-match well.
- **TAB scoreboard**: blue fraction in `(270,100,690,240)` and red fraction in `(270,300,690,440)`.
  min ≥ 0.45 means TAB. Very clean (~0.7 on TAB, ~0 otherwise).
- in-match = HUD or TAB. Runs merged across gaps < 75 s.

Per span, in priority order:
1. **Result**: (a) VICTORY/DEFEAT banner OCR in the centre (often hidden because **Noah holds TAB
   through the match end**); (b) **chat line `[ATHENA] Victory.` / `Defeat.`** (OCR bottom-centre),
   which also pins the true end, because **POTG replays show a HUD** and would otherwise extend the
   match; (c) the accolades-screen header (top-left "VICTORY · map · MATCH TIME"); (d) the comp rank-page title.
2. **Round-swap merge**: comp escort/hybrid has "ROUND 1 COMPLETE / switching sides" + ~80 s
   hero select. A span with no result and no post-match screen, followed by another span within
   200 s, gets merged. (This fixed Havana being split in two.)
3. **Post-match screen**: tab bar `SUMMARY/REWARDS` (QP) or `COMPETITIVE/SUMMARY/REWARDS` (comp),
   detected on thumbnails (bright-text mask, `g>170`), then read from a full-res grab.
   QP title = hero + minutes ("DOCTRINE 7 minutes"); comp title = result, page = rank + progress.
4. **Map / mode / clock / queue**: full-res grab of the TAB header (top-right):
   `ESCORT | ROUTE 66 TIME: 10:43` (QP) or `ESCORT THE PAYLOAD - COMPETITIVE | WATCHPOINT: GIBRALTAR`
   (comp). The map is matched against a known-map list (`MAPS`, Grímsvötn included), with the mode
   from `MAP_MODE`. The orange italic clock is read by colour mask + shear deskew + vote.
5. **Hero timeline** (`heroes.py`): every TAB press's side panel (`TAB_HERO_ROI`) is OCR'd at full
   res and snapped to `HEROES`. Those reads label the **HUD portrait** (face inside the border,
   thumbnail px `(36,438,66,486)`; the QP hexagon / comp wings are outside it). Frames within 15 s
   of a read become references (gradient + Lab a/b vector), purified so spectate/kill-cam faces
   drop out, and saved per session in the profile's `portraits.npz` (a library across sessions).
   Each HUD frame takes the best reference (top-5 mean, min 0.50). Runs shorter than 30 s must
   show the player's nameplate (full-res HSV text mask vs the profile's `nameplate.png`;
   own ≥ 0.85, others ≤ 0.35), else they're `views` (kill cam / spectating, kept for stage 4).
   Swaps sit between the last frame of one hero and the first of the next (always a death at
   0 HP then the respawn shimmer). Verified against frames for all 9 swaps in the two sessions.
   The hero-select screen OCR was dropped: its italic font defeats tesseract.
6. **Player profile** (`profile.py`, `owcoach init CACHE`): 48 full-res nameplate crops from HUD
   frames; each is cut to its glyphs; the one matching the most others is the player (92–94% of
   samples on Noah's sessions, so spectating doesn't confuse it). Tesseract proposes the name and
   the user confirms (`--name` / `--yes` when non-interactive). Stored in the profile dir
   (`OWCOACH_PROFILE` overrides): profile.json, nameplate.png, nameplate_preview.png, portraits.npz.
   A name change or a new resolution means re-running `init`.

7. **Events, stage 4** (`events.py`, `owcoach events CACHE`). First source is the kill feed.
   - `roiscan.py` decodes the keyframes again and writes full-res crops of named regions
     (`geometry.Region`, anchored and in height units), cropped *before* the tonemap. Files are
     named like the thumbnails. The feed region is `("tr", -0.40, 0.065, -0.02, 0.33)`.
     Cost: 38 s and 144 MB for a 76-minute session.
   - The player's name is found with the **profile nameplate template**: same font and size in the
     feed, coarse match then local adaptive rescore ≥ 0.55 plus a whole-word check. On the right
     edge the player is the victim (death); on the left, the killer (final blow).
   - Deaths: sightings < 10 s apart are one death. Kills: the victim name is OCR'd per sighting
     (name word cut out, greyscale, whitelist) and grouped by name within 12 s. A differently
     read kill within 6 s that never shares a frame with an earlier kill is a misread of it.
   - Deployables (turret, B.O.B., pylon): edge density left of the victim name is < 0.25
     (portraits ≥ 0.33, icons ≤ 0.18). Colour fails: Doctrine's portrait on a red box.
   - Validated: deaths equal the final scoreboard's D in all 9 matches. Final blows ≤ E
     everywhere; the deployables were checked by eye. Feed rows flicker in and out of
     detection (semi-transparent boxes), so identity never rests on continuity.
   - Output: `events.json` in the cache, then per match from `split`: deaths {t, t_clip,
     killed_by, hero}, final_blows {victim}, deployables_destroyed {owner}.
   - **Ult** (roiscan region `ult`, `("bc", -0.07, -0.205, 0.07, -0.07)`): the % ring is
     unreliable on orange/red backgrounds, so only the READY state is detected. Ready means a
     light rim (0.024–0.030 H) around the hero-specific icon, a blue ring (0.033–0.045 H), and a
     ring at least 50 points more saturated than the rim (rejects plain light-blue backgrounds).
     It's read only on **own-view frames** (`own_view.npy`, saved by the hero step), because the
     kill cam shows the killer's meter. Ready runs closer than 25 s are one ult, since no ult
     recharges that fast; so are runs within 40 s across a death (charge survives death).
     Outcomes are used / lost_on_swap / held_to_end, plus held_s and deaths_while_ready.
     Checked by eye: Doctrine held 170 s on Grímsvötn, Zenyatta about 145 s on NQS, and a
     Mizuki death with ult ready on Gibraltar.
   - **Players alive** (region `alive`, `("tr", -0.18, 0.022, -0.02, 0.066)`): the "VS" text is
     found by template (`assets/alive_vs.png`), then the two digits at fixed offsets are
     Otsu-binarized and matched to `assets/alive_digits.npz` (2–5 only; 0/1 read as None).
     About half the frames give a reading: the counter fades at 5v5 and is hidden under TAB and
     the kill cam. Each death or final blow gets `alive_before` {ally, enemy, age_s}.
   - **Objective** (`objective.py`, region `objective` `("tc", -0.32, 0.0, 0.32, 0.19)`): the
     objective HUD is mostly text in every mode, so there is one reader for all of them.
     - Per frame (own view only, 1 fps): top-hat on the max channel finds text brighter than its
       own box, whatever the box colour. Glyph-sized components locate tokens, and all tokens of
       a frame are OCR'd in **one** tesseract call: crops stacked in slots, words mapped back by
       y. Line grouping drops single characters, which made per-token fallback 13x slower.
     - Tokens are typed by regex (% / distance / mm:ss / score digit), put on ally or enemy side
       by x (allies left), or fuzzy-matched to PHRASES (PREPARE TO ATTACK/YOUR DEFENSES, ESCORT/
       STOP THE PAYLOAD, ATTACK/DEFEND OBJECTIVE A/B, CONTESTED!, POINT UNLOCKS, CAPTURING).
     - OVERTIME is italic, so it's template-matched (`assets/overtime.png`, NCC ≥ 0.48).
     - Series per match: side from phase labels, held for 4 reads (none for control); rounds
       from setup labels; overtime and contested stretches; scores only in +1 steps; per-mode
       fields (control %, push and comp escort/hybrid distance); control % monotonic per round.
     - Score steps (2026-10-15): the lone score digit misreads often, so "4 reads in a row" dated
       Havana's checkpoints 10–53 s late (Noah confirmed checkpoint 1 at ~11:08; it read 11:17). Now a
       step also counts with 4 reads of the next value within 15 s that are over half the reads
       there, and is back-dated to the first read of it, at most 15 s. Havana now reads 11:07 and 13:34.
       Checkpoint 3 still reads 16:03 (the round ended ~15:15), and Nepal's capture reads 12:49
       though % hit 100 at 11:30. TODO: date captures from % / distance / time bank instead.
     - Every death, final blow and ult gets `objective` context: side, overtime, contested, and
       ally/enemy % or distance.
     - Cost: 32 s and 41 s for the two sessions. Checked: sides and rounds on all escort/hybrid
       games, overtime frames by eye, and end states that fit each result. Distances still
       carry the odd misread (a stray small value between big ones); QP progress is only a bar
       (not read); Flashpoint/Clash phrases are untested (no footage).
   - Not yet: assists (icons in the killer cell), snapping names to the scoreboard roster
     (OCR reads 0 as O), ult charge %, digit templates for 0 and 1, QP payload bar.

**Stage 5: the per-game packet** (`packet.py`, `owcoach packet CACHE [--game N]`, after `split`).
This is the input to the generative coaching. Claude takes text and images, not video, so each
moment is a few stills plus JSON.
   - Written to `<game dir>/packet/`: `packet.json`, `frames/`, copies of scoreboard_final / summary
     / rank, and `moments.m3u`. The playlist is for Noah: VLC plays each death and ult straight
     from `../match.mp4` (12 s before, 6 s after), so no extra clip files.
   - In `packet.json`, times are `t` (s since match start), `clock` (m:ss) and `video_t`
     (match.mp4). It holds game facts, the hero timeline, objective (rounds, sides, overtime,
     scores, series), one merged `timeline`, deaths, ults, final blows, `alive_series` and `notes`
     (known limits, for the analyst).
   - Deaths are found in the kill feed, then **re-anchored on the "YOU WERE ELIMINATED BY" banner**
     (`assets/eliminated.png`, grey-scale NCC on thumbnails, searched centre-bottom because its
     height moves with stacked notices; banner 0.6–1.0, alive frames ≤ 0.58). Onset = a thumbnail
     ≥ 0.6 with another ≥ 0.55 in the next two, searched from 14 s before the feed (but not before
     the previous death + 8 s); death = onset − 0.25 s. 60 of 65 deaths get a banner anchor; the
     rest (menus, spectating) use feed − 0.5 s. It fixed every late feed: NQS d01 2.8 s, Gibraltar
     d06 3.3 s, Lijiang d05 6.2 s, Havana d08 6.2 s, Nepal d12/d14 1.7 s. Each death records
     `anchor` and `feed_lag_s`. An HP = 0 template on the HUD was tried first and dropped: the HUD
     block shifts per hero and "250|250" matched "0|".
   - Death stills (2026-10-14 rework): `lead_in` full screen at -10 / -6 s, then **`detail` stills
     every 0.5 s from -3 s to the death**. A detail still is the centre 1.089 × 0.611 game-area
     heights at native resolution with the bottom-left (HP) and bottom-right (abilities / ult)
     HUD corners under it, 1568 × 1140 at 1440p. Why: the full 3456-wide frame downscaled to
     1568 px left HP, names, team colours and ability icons illegible, and the first coaching pass
     misread several deaths (a teammate Juno as an attacker, the player's own Binding Chain as an
     enemy Ana, a Fade on cooldown missed). A 3-death A/B (dense 4 fps vs these) showed 2 fps over
     3 s loses nothing. The own-view mask is *not* an alive signal: the red low-HP overlay hides
     the HUD while still fighting, and the death camera keeps it.
   - **First pass and extras (2026-10-15):** detail and kill cam are now decoded every 0.1 s, but
     only the old set is the first pass: detail every 0.5 s, 4 kill-cam stills. The rest carry
     `"extra": true` in `frames` and are read on demand, up to 12 per death, for a specific
     question. Why: in the Havana A/B, reading all of them at 10 fps (+84% cost) fixed one
     misread (d10: the car was covering the player) but added a confident wrong one (d08: the
     direction of a dash). Decoding is free; reading is what costs. ~540 stills for Havana, 100 s.
   - Kill cam stills are found by the "KILL CAM" label (`assets/killcam.png`, NCC ≥ 0.65; kill cam
     0.72–1.0, everything else ≤ 0.54). Up to four per death, 2–14 s after the feed. 43 of 65 deaths
     have one; the rest were skipped. Each death records `kill_cam`, `alive_for_s`, `respawned`
     (first steady own view after it) and `ult_ready`/`ult_held_s`.
   - Used ults get stills at -3, +0.5 and +2.5 s around the press. Stills are the full game area at
     1568 px wide (Claude's native size), grabbed with NVDEC: 9 s for a game, 34 s and 59 s per
     session.
   - Size: 33–173 stills per game (Nepal, 15 deaths, is the largest). Detail stills are ~2.4k
     tokens each, full ones ~1.4k; a death costs about 2× what it did with the old six lead-ins.
     Rebuilding both sessions' packets takes 80 s + 140 s.

   - Rule flags per death (`first_down`, `team_ahead`/`team_behind`/`even_fight`, `short_life`,
     `died_with_ult`, `overtime`, `contested`, `repeat_killer`) and per ult (`held_long`,
     `ult_died_with_it`, `died_while_holding`) plus `counts.death_flags`. These are leads for the
     analyst, the way `hotscoach analyze` works in CoachClaude.
   - Respawn is approximate: the death camera and spectating a teammate both pass the own-view
     check, so it's searched from 8 s after the feed. It can still read 1–2 s early. Fix with a
     per-frame nameplate check.
   - `events.match_ult`: an ult whose icon vanishes within 2 s of a death is `died_with_it`, not
     `used`. Found by the first coaching run (Busan u02).

**Stage 6: the coach** is the Claude Code skill `.claude/skills/ow-coach/` (SKILL.md, references/rubric.md,
references/lessons-template.md), modelled on CoachClaude's hots-coach. It's linked into
`~/.claude/skills/ow-coach` with a junction (`owcoach install-skill`). It reads packet.json, then the scoreboard/summary, then
every death's stills. It writes `packet/coaching.md` and keeps `lessons.md` in the profile dir. It lists
data errors it finds under "Pipeline issues" instead of patching. First run: Busan. Its findings were
checked against the stills, and it caught the u02 bug above.
   - **Fan-out (2026-10-15):** the main session no longer reads images. It launches one subagent per
     death, one per overview chunk (≤5 min / ≤60 sheets) and one for the ults
     (`references/subagents.md` has the briefs). Each writes `packet/notes/<piece>.md`, and the main
     session writes the coaching from the notes, opening at most 6 stills itself. Finished notes are
     skipped, so a run cut off by a usage limit resumes.
   - **Why:** one session reading all of Havana's 151 images never finished. Old tool results were
     cleared, the coach re-read stills up to 6×, and each clear broke the cache (~$70 API-equivalent,
     no report). With the fan-out the same game took 7.7 min and $11.89, and every image was read
     exactly once.
   - **COST:** most of the spend is subagent output (~12k tokens each, notes plus reasoning) and
     cache reads at one turn per image. The briefs ask for parallel Reads, but the readers still
     read 0.6-0.8 images per turn (session 2 re-coach, 2026-10-15).
   - **Fire test, session 2 (4 games, 43 deaths), 2026-10-15:** 74 subagents, 17.7 min, $59.63
     API-equivalent (~$15 and ~4.5 min a game). Subagents start ~8 s apart even when launched in
     one message, so launching took 10 min; each piece ran 1-3 min; writing 4 reports, the
     session summary and lessons took 4 min. No errors or compactions.
   - **Fire test, session 1 (5 games, 22 deaths), 2026-10-15,** after the speed-up (two deaths per
     reader, 5-min overview chunks, overview first pass at 5 s with the 2.5 s cells as `b` extras):
     29 subagents, 12.5 min, $30.27 (~2.5 min and ~$6 a game). Per minute of game: 16.8 s and
     $0.68, against 16.6 s and $0.93 for session 2. Launching took ~4 min, readers 1-4 min,
     writing 5 reports + summary + lessons 4.6 min (now the largest serial part). Readers still
     read ~0.65 images per turn despite the batching instruction.
   - **Per-game processes (`scripts/coach_session.sh`, 2026-10-16):** one `claude -p` per game in
     parallel, then one for the summary and lessons (trend computed first by the script). Session
     2: games finished at 13.4 / 14.0 / 15.5 min, Havana at 23.5 only because its process kept
     scheduling wake-ups after its writer was done (prompt now forbids it); summary 2 min, $0.73.
     Cost $61.75, the same as the single-session runs ($53-60). **Wall clock didn't improve:** a
     game's chain (launch ~2 min, readers 4-5 min, writer 5-6 min) is the floor whatever the
     cross-game arrangement, so a session takes about as long as its slowest game, ~16 min.
     Kept because it's cleaner (a game is resumable on its own, no concurrency refusals) and
     the summary step is cheap. The next wall-clock lever is the chain itself: low-effort
     readers halved reader time on Havana (2.0 vs 4.4 min per death pair); the writer's 5-6 min
     is the other half.
   - **Low-effort readers A/B (2026-10-16, `coach_session.sh --effort low --no-summary`, 7 games
     with labelled deaths, both sessions in parallel, outputs in the scratchpad `ab_low/`):**
     every reader at effort low, writer at default, all Opus 5.5. Session 2 games: 12.2 / 14.0 /
     12.8 min and $12.48 / $14.83 / $11.20 (default run: 13.4 / 14.0 / 15.5 min, $17.34 / $18.49 /
     $15.54), so ~25 % cheaper and 0-3 min faster. Session 1 games 7-10.5 min, $5-8 each (the
     default single-session run was ~$6 a game). Readers finished at 3-6.5 min (Havana 6.0 vs
     7.4 default); the writer then took 4-7.5 min and opened stills itself in 4 of 7 games to
     settle what the notes left open, so the writer is now the floor. Scored against the 12
     labels in `labels/deaths.md`: low was better than the default run on 6 deaths, equal on 5,
     worse on 1 (Nepal d04, read the backwards Return as a leap into the Moira). Two of the
     six (Nepal d07, Gibraltar d07) are credited to the grading decisions Noah's labels added to
     lessons.md after the default run, not to the effort. Decision pending with Noah; the
     suggested next A/B is these low-effort Opus readers against Sonnet readers.
   - **Facts block A/B (2026-10-16, same 7 games, low-effort readers, outputs in the scratchpad
     `ab_facts/`):** the only change from the run above is the per-death facts block pasted
     into the reader brief (`facts.py`, commit e1da33d). Cost $59.35 vs $62.32, wall clock the
     same (games 8-13.7 min; readers done at 3.6-6.3 min, the writer 4-7.5 min after and still
     opening stills itself). Against the 12 labels: better than the low run on 4 (Grímsvötn
     d03 now has the pillar, the break for the Zarya and "leaving cover was the lever"; Nepal
     d04 and Lijiang d01 now say the Return was no way out and name the engagement as the
     mistake; Havana d08 reads the Grip as a save and puts the lever at the tank's death),
     equal on 6, worse on 2 (Havana d02 back to "no lever"; Paraíso d01 no longer says which
     way the Momentum went). The facts run's pipeline notes are real: Route 66 d04 has no 2 fps
     read from -10 to -3 s although the view was live, its 3:40-3:58 fight is missing from
     `hud_game.fights` so its presses read as travel, and its 3:50 low episode is missing;
     Grímsvötn d03's 2 fps HP at -6 s is ~1 s off the still; Mizuki's doll-out state reads as
     "blocked" where the RETURN prompt is up. Kept: the block costs nothing and the hardest
     deaths moved toward Noah's accounts.
   - **Pipeline fixes from the labels (2026-10-16, commit 7b3bdfa; `overlay.py`):** (1) the
     SELECT PERK prompt covers the nameplate the own-view check reads, so stretches with an
     unspent perk lost the 2 fps HUD, their fights and low episodes, and their presses read
     as travel; hudscan now keeps a non-own frame whose nameplate area is the orange box and
     whose HP reads (+31 s / +72 s of live HUD per session), and `match_heroes` accepts the
     box for future sessions. (2) With the Tab scoreboard open the health box shows 0; those
     frames and the 0.5 s fade-in are hidden now (series and death stills), and the facts
     block says so. (3) A kill, death or ult opens a fight window on its own (6 s before, 2
     after). (4) Slot state "active": a red/orange in-use icon without the diagonal slash
     (Katashiro's doll out with the RETURN prompt, a platform placed); "blocked" needs the
     slash. (5) Lead-in rows nearest each whole second. Validation run (Nepal, Grímsvötn,
     Route 66, low-effort readers, $24.82, 8-13.6 min): Nepal d07 now reads as Noah labelled
     it (rejoined a lost fight, the second Return would have sent them back in); Nepal d04,
     Grímsvötn d03 and Route 66 d04 unchanged or slightly better (Route 66 now has the dash
     into the rail car and the perk prompt; the writer still dates the death ~3:53 from a 0
     HP + skull still at -3.0 s where Noah says 3:57: open question for the clip). Slot
     names for Doctrine stay "slot N" (learned cooldowns 3 / 3 / - / 5 don't match the note's
     8 / 14; the note has no binds for Momentum and Drones).
   - **Egomotion (`motion.py`, 2026-10-16, commits bd00087 / ffac5bd):** dense flow (DIS, 480 px
     wide) between consecutive 0.1 s detail stills on the centre crop, weapon / hands / reticle
     masked. Far-field median flow = the camera's turn (degrees at the default 103° FOV);
     near-ground parallax against it = strafe and forward / back. Far-field inlier fraction
     < 0.30 = a cut: a "jump" when the pixel difference is wholesale (>= 45 / 255: teleports,
     freezes, the death cam, menus), else "no stable read" (close quarters, looking at the
     ground, a dash blur). The facts block carries the trace per 0.5 s, camera-relative; the
     rubric and deaths brief say movement comes from it and only its direction relative to the
     enemy or cover stays inference, and the notes shape has a Movement bullet. Against the
     labels: Havana d02 forward at the Tracer, d05 / d10 strafing back and forth, d08 moving in
     the road then unreadable from the Dash; Grímsvötn d03 forward, 23° left, forward (the break
     for the Zarya); Nepal d04 / d07 unreadable (looking at the ground, a Winston in the face)
     and say so. A dash can't be told from close-quarters chaos by flow, so it stays the HUD's
     press record's job. Coaching run on Havana + Grímsvötn ($14.67, 9-10 min): the writer used
     the trace for d05 ("left the pillar at -2.5 s and pushed up the open street") and d08's
     lever; readers cited it in 4 of 15 notes before the Movement bullet was added. Not done:
     the 2 fps lead-in (0.5 s apart; only the turn would be recoverable); a per-death static
     mask learned from the frames instead of the fixed weapon box.
   - **The writer (2026-10-16, commits 7931ca9 + this):** its transcript showed where 5 min went:
     ~40 turns (packet.json in full, 16 notes files one per turn, python to slice the packet)
     each re-reading ~110k cached tokens (2.6-3.7M per game), one 120-270 s default-effort
     thinking turn, a Write turn with ~18k reasoning tokens for a 3.7k-token file, and a 2k-token
     reply where one line was asked. Fixes: `packet_slim.json` (no frames, series, raw hud /
     motion arrays; 108 KB vs 507 KB for Havana), `owcoach notes <game>` -> `notes/all.md`, the
     brief says two Reads in one message and a one-line reply, and `--writer-effort`. A/B on the
     7 labelled games: slim + one file alone (default effort) cut the writer's turns to 16-19 and
     cache reads to ~1.1M, wall 220-370 s; slim + low effort cut the writer to 96-134 s (thinking
     31-51 s, 10-15k output), games 5.4-9.6 min (was 7.2-14.0) and $51.01 for the 7 (was $62.32).
     Verdicts on the 12 labels: equal on 11, one detail lost (Havana d08's Grip read as travel
     where it was a save). Low is now the writer's default. Open question for Noah from both
     writer arms: Nepal d07 reads as a second Return press that put them back at the doll in
     front of four enemies (the HUD shows Katashiro active twice); Noah's label says re-pressing
     would have been worse, which implies they didn't.
   - **Sonnet readers A/B (2026-10-16, `--reader-model sonnet`, writer Opus, all low effort,
     outputs in the scratchpad `ab_sonnet/`):** the first run hit the claude.ai session usage
     limit mid-way (every process ended with "You've hit your session limit"; readers partly
     done, no writers), so it was resumed from the notes already written (`resume.sh`; the
     skill skips complete pieces). Cost: $25.78 + $19.96 for the resume, so a clean run would be
     ~$35-40 against $51.02 with Opus readers: about -25 %, not the 5x the per-token price
     suggests, because Sonnet readers wrote more (10.5k vs 7-10k output tokens per piece), the
     main process and writer stay Opus, and both runs were throttled (8-22 rate-limit retries
     per game). Reader wall per piece 20-180 s vs 24-205 s on Opus: no real speed-up. Against
     the 12 labels (Opus writer on Sonnet notes): equal on 9, worse on 3 (Nepal d04 back to
     "the leap put you next to the Moira"; Route 66 d04 lost the Momentum through the
     corridor; Havana d08 lost the "leave when the tank died" lever). Decision: keep Opus
     readers. If cost matters later, fewer pieces (3 deaths per reader) is the lever, not a
     cheaper reader.
   - **First end-to-end run on new footage (2026-10-17, three one-game recordings from the
     evening of 2026-10-16: Dorado / Lifeweaver, New Junk City / Ana, Lijiang Tower / Mizuki):**
     pipeline scan -> segment -> events -> hud -> split -> packet took 1.5-3.5 min per recording
     (packet 1.3-2 min of it); split once hit a Windows file lock on the clip rename (now
     retried). A 3-min fragment that starts mid-match segmented as "m01_unknown" and was left
     alone. `owcoach hero Ana` fetched the first new hero note; its slots named themselves from
     it (Sleep Dart 14 s, Biotic Grenade 12 s). Coaching: one process per game in parallel
     (5.6 / 5.6 / 8.7 min, $6.10 / $4.41 / $7.98, 14-16 rate-limit retries each), then one
     summary process over the three sessions by hand (`owcoach trend --games 3`, output in
     `owcoach/2026.10.16 - evening/`; $0.82), which graded the player's own focus for the first
     time (wall: 9/21 held, Not improved in all three; respawn wait: 8/10), left the wording
     alone and wrote a 5-option proposal. Pipeline issues it raised: a Dorado death at ~4:22
     the packet missed; Lijiang's Katashiro reads as cooling while the doll is out (the active
     state missed it there).
   - **Library + config layout (2026-10-18):** Noah wants owcoach packaged for others and merged
     into CoachClaude with a shared core (config, lessons/focus, history, a report viewer), both
     coaches writing coaching.md files and one viewer over both. Step 1 of 3: `config.py`
     (config file, profile, library, captures, `session_dir`, `cache_for`, `resolve_cache`),
     `pipeline.run` (every local stage, skip-if-done), `coach.py` (the bash driver in Python:
     prompt on stdin to the npm `claude.exe`, parallel game processes, one summary per session
     or one combined over several, `--sessions-summary`; cost estimate from the logged
     `total_cost_usd`, asks before spending unless `--yes`), `migrate.py` (moves + rewrites the
     stored paths), `setup` / `config` / `new` / `run` / `install-skill` commands. Stored paths
     went relative (session.json dirs, hero_notes, history packet). Noah's data was migrated
     (two 2026-10-13 sessions, four 2026-10-16, the evening summary; caches; profile). The skill
     text now gets paths from `owcoach config` and tells the model how a player asks ("coach last
     night's games" -> `owcoach new`, cost, `owcoach coach --new --yes` in the background).
   - **The page (2026-10-18), step 2 of 3:** `owcoach site` writes `<library>/coaching.html`, one
     file, no copies: a sidebar of days -> sessions (and combined summaries) -> games; a game page
     has the stats table (game, per 10, other same role, enemy same role), the scoreboard, an SVG
     timeline (fights, deaths with time dead, ults ready->used, final blows, low-HP episodes),
     the clip as a `<video>` seekable from every moment (HEVC HDR: Edge/Chrome play it flat; the
     m3u link is there for VLC), the report, and each death/ult/final blow with its sampled
     stills, the facts line and the reader notes folded; a session page has the games table, the
     summary and the trend; Lessons and Focus proposal are pages; home is every game. Noah's
     long-term note: the dollar estimate in `coach` is for building only, not to ship (a default
     vs low-cost mode instead).
   - **The merge (2026-10-18), step 3 of 3:** owcoach joined CoachClaude as a light monorepo
     (Noah: "light monorepo", "separate pages", "always squash"). Shared code is only
     `coachlib.config` (one file, sections `ow` and `hots`) and `coachlib.site` (the renderer,
     now data-driven: a collector hands it days -> sessions -> games with cells, tables, a
     timeline, moments and folded details; `owcoach/site.py` is the OW collector). The HotS
     script stayed one file but moved to the repo root, writes
     `games/<session date>/<game>/{analysis.json, timeline.txt}` per game (session = evening,
     06:00 cutoff), has `site` and `install-skill`, and its skill now writes `coaching.md` per
     game and per session so its page fills in. Two pages, cross-linked in the sidebar.
   - **Fire test, session 2 again, 2026-10-15,** with per-game writer subagents: 44 subagents
     (40 readers, 4 writers), 17.9 min, $53.48. No faster than the first session-2 run (17.7 min).
     Why: about 20 subagents can run at once (4 launches were refused with a concurrency error and
     relaunched), two-death readers take ~4 min, and a game's writer (3-4.6 min) can only start
     after that game's last reader. Havana's last reader started at 7.6 min because of the
     refusals, so its writer ended at 16 min. Output is ~1M tokens per session and is the main
     cost and time driver; only ~25% of it is visible notes and text, so the rest is reasoning.
     Next lever: lower reasoning effort for readers (the Agent tool's `effort`).

   - **Focus ownership (`focus.py`, `owcoach focus`, 2026-10-16):** the focus in lessons.md is
     the player's. The coach grades it and never rewords it; at the end of every session it
     writes `focus_proposal.md` in the profile dir (option 1 = keep, verbatim with its grades; 2-4 more
     from the patterns, each with evidence and what would test it; shape in
     `references/focus-proposal.md`). `owcoach focus N [N]` (or `--set "..."`) rewrites the
     "Current focus" section from the chosen options and parks the rest under "Focus options",
     verbatim, then moves the proposal to `focus_proposal.last.md`. Interactive sessions ask
     with AskUserQuestion and run the command; `coach_session.sh`'s summary process only writes
     the proposal. Per-hero escape decisions moved to a "Grading decisions" section so they
     survive a focus change. Why: the coach had reworded the focus three times on its own.
     The first proposal (from session 2) is waiting; Noah hasn't picked.

**HUD reader** (`hud.py`, 2026-10-15, Fable): each death's `hud` block in packet.json holds HP
every 0.1 s (`hp`, with a confidence; `hp_max`; `hp_zero_dt` = the frame HP first read 0, which
precedes the banner anchor by up to ~1 s), each ability slot's state per frame (`abilities`:
ready / cooling with the countdown / blocked = red slash / hidden) and a one-paragraph `summary`
the readers quote. Why: HP and cooldowns were the most-cited facts in every death note and the
LLM readers got them wrong often enough to matter (210 read as 10; a dash on cooldown called
"pressed late"), and reading them off 13+ images per death was most of the reader cost.
   - Read from the detail stills, which carry the HUD strip at native resolution; no extra decode.
     ~2 s per game. All constants are at 1440p and scaled by the game-area height.
   - HP: adaptive threshold on the min channel (white text), connected components, the
     scoreboard digit templates. Current HP is the big font (~28 px), max HP the small grey one
     (~22 px) to its right, so the two separate by glyph height and the faint "|" isn't needed.
     98 % of 2,015 frames over 65 deaths read; max HP right in every death; 2 suspicious jumps
     left after per-death cleaning (spikes, dropped leading digits). A top-hat was tried first
     (93 %): a bright background behind the translucent box defeats it.
   - Ability squares: the three states look nothing alike (translucent white / dark grey filling
     with orange from the bottom / red outline only), so colour or flatness can't find them.
     Geometry does: two continuous vertical edges 85 px apart at a 105 px pitch on a fixed row,
     plus the row's top and bottom edges. Per-frame comb fits vote on the grid phase (candidate
     clusters; a fit aligned on a gutter gives a second cluster ~20 px off), each grid position is
     scored over the clear frames (75th percentile, best of +-2 px) and the longest contiguous
     run is the layout. The layout is a per-hero constant (Zenyatta 292/397 px in the right
     strip, Moira 227/332, Lifeweaver 123/228/333, Mizuki 198/303/407, Doctrine 6/111/216/317,
     Brigitte 89/194/299/404): learned from all of a hero's deaths in a game and cached in
     `<profile>/hud_layouts.json`, in heights from the right edge. A longer learned layout that
     agrees with the cached one replaces it.
   - States per slot: a countdown that reads (own italic templates, `assets/cooldown_digits.npz`,
     bootstrapped from 1,400 harvested glyphs clustered and labelled by eye, 99.9 % self-match)
     means cooling; else white fill >= 30 % ready; else red >= 6 % blocked. Smoothed per slot by
     a 5-frame majority, and the countdown must step down one per second (validation: Moira's
     Fade 5->2 and Orb 8->5 over 3 s, Lifeweaver's dash 4->1).
   - Not read yet: which key each slot is (the LSHIFT / E / SPACE labels under the squares;
     slot order left-to-right is reported instead), the ult charge %, the perk prompt, and the
     weapon / ammo panel. A slot can be missed when its square is an outline for every clear
     frame of a hero in a game (then the cache from an earlier game fills it in).

**Whole-game HUD series** (`hudscan.py`, `owcoach hud`, 2026-10-15, Fable): the HP and ability
reader run on every own-view keyframe (2 fps) of the session, from two new roiscan regions
(`hud_hp`, `hud_abil`: the same strips a detail still carries, cropped at native resolution, free
because that pass decodes every keyframe anyway; +92 s per session to re-crop). `hud.json` holds
one row per frame; `owcoach hud` takes ~170 s for a 1.3 h session (5,858 frames, 98.8 % with HP).
Slot layouts are learned per hero from 160 sampled frames of its own-view time, which found all
four of Doctrine's and Brigitte's slots where single deaths had found two.
   - `packet.json` -> `hud_game` per match (`hud.game_hud`): `series` [[t, HP, [slot states]]],
     `low_episodes` (every stretch under half HP: min HP, the escape slot's state when it
     started, when the escape was pressed, recovered / died), `presses` (escape slot steady
     ready -> steady not-ready, with the HP at the press), `fights` (HP changes >= 10 between
     keyframes, kills, deaths and ult presses, merged within 8 s, >= 4 s), `stats` and
     `stats.by_hero` (time under half %, episodes by outcome and by escape state, presses under
     half, median HP at press). Havana: 22 low episodes, 8 of them deaths; 9 started with the
     escape cooling, 1 with it ready and unused.
   - Why: the focus ("under half HP: escape or cover; escape down: stay in cover") is now graded
     from these counts instead of readers' impressions, so two runs give the same grade, and the
     overview readers get the fights list so they spend their extras there.
   - Cleaning: max HP = the mode per hero (one misread like 2507 would make everything "low");
     the same despike / dropped-digit pass as around deaths; episodes shorter than 0.75 s that
     didn't end in a death are misreads; a press needs two steady frames on each side.
   - **No "escape slot" (2026-10-16).** "Escape" is contextual (Noah: Dash is lateral only,
     Petal vertical only, a teleport needs a teammate alive), so the pipeline records facts for
     every slot and the coach judges with a per-hero kit note. `presses` cover every slot with a
     context (travel = outside a fight, engage = in a fight at or above half, low = in a fight
     under half) and the countdown the press started from; `low_episodes` carry every slot's
     state at the start and, for each slot not ready, the last press before it (how long before,
     at what HP, in what context): "fought without Fade, spent 11 s earlier walking in at full
     HP" is a fact the writer can state. `stats.by_hero.slots` learns each slot's cooldown
     length from the presses (Moira 6 / 8 = Fade / Orb; Lifeweaver 12 / 18 / 5 = Petal / Grip /
     Dash), so the kit is identified without keybinds. Whether a ready ability was a way out
     is the coach's judgment from its own knowledge of the kit (kept as inference when it rests
     on the scene); a per-hero kit *rulebook* was tried for a few hours and dropped, because it
     re-teaches the model Overwatch one hero at a time and boxes the coaching in (Noah,
     2026-10-16). The focus is graded from three factual rates (fights started with the escape
     cooling from a travel press; low episodes with it ready and pressed; low episodes with it
     cooling that ended in death); which slot is the escape is decided once per hero by the
     coach and recorded in the lessons file. `owcoach packet --refresh` rewrites packet.json
     from the stills on disk (seconds a game) for changes like this.
   - **Hero notes** (`herowiki.py`, `owcoach hero <Name>`): the Overwatch wiki's page
     (overwatch.fandom.com, MediaWiki API, wikitext) parsed into `<profile>/heroes/<Hero>.md`:
     each ability with its default bind (the wiki's "ability 1" = LSHIFT, "ability 2" = E,
     "ability 3" = SPACE), cooldown, charges, official description and a few details ("Dash is
     horizontal only", "the platform blocks line of sight"), plus perks. Optional reference
     data for heroes or reworks newer than the model; `packet.json` -> `hero_notes` lists the
     ones that exist and the briefs pass the path. The coach must work without them, and never
     fetches them: Noah runs `owcoach hero` rarely (a new hero, a rework), not as part of
     coaching.
   - Not done: ult charge % from the existing `ult` crop (same digit reader); the enemy/ally
     HP of targets; a cheaper 10 s overview first pass that reads the 5 s cells only in fights.

**Stats and trends** (`stats.py`, `history.py`, `owcoach trend`). Noah asked for a stats summary
(deaths, time dead, healing, damage per 10 min of active time) and to be told when they move
meaningfully.
   - **Scoreboard:** `scoreboard_final.jpg` cells at fixed spots (height units from centre), rows
     tank/DPS/DPS/support/support. The player's row is the lighter one. Digits are read by
     template (`assets/score_digits.npz`): Otsu on the min channel, blobs, and touching digits
     split where both halves match. Tesseract missed lone digits and garbled touching ones.
     Checked 120/120 cells on 2 boards plus Havana by eye; 1 cell unread over 9 boards (mouse
     cursor).
   - **Clock:** the TIME clock **pauses** in setup, between rounds and at match end, so it can't be
     inferred from session time. It's read at the final TAB with templates
     (`assets/clock_digits.npz`, from hand-read clocks; tesseract confuses italic 1/4, 3/5, 6/9).
     Over all 150 TAB presses the offset never decreases. segment's `final_clock` is the old
     tesseract read and is often wrong (Busan 7:43 vs 7:13); stats doesn't use it.
   - **packet.json `stats`:** totals, `player_per10`, `teammate_same_role_per10`,
     `enemy_same_role_per10`, `time_dead_pct`. Scoreboard D matched the kill-feed deaths in all 9
     games.
   - **History:** `history.sqlite` in the profile dir, one row per game, upserted by `packet`. Main hero is
     the hero with the most total time.
   - **`trend`:** latest session (or `--games N`) vs all earlier games, filterable by role or hero.
     Rates are time-weighted. A change is `better`/`worse` at ≥10% and ≥2 standard errors with ≥5
     baseline games. On 2026-10-13, session 2 vs session 1: deaths +50% and time dead +47% (worse),
     healing normal, damage −23% (hero mix).

**First full coaching pass (all 9 games, 2026-10-13).** Reports are in each `packet/coaching.md`, and
session summaries in `<session>/coaching.md`; lessons are in the profile's `lessons.md`. The reviews
turned up these pipeline issues, in priority order:
   1. **Killer names split across OCR variants** (ANGEL2CHAKS / 4ANGEL2GHAKS, ENIGMAL / ENIGMAL_),
      which undercounts repeat killers. Fix: snap to the scoreboard roster.
   2. ~~Feed read late~~ (3–9 s) on about 6 deaths. **Fixed 2026-10-14:** deaths are anchored on
      the elimination banner (above).
   2b. **Stills too small to read** (found by Noah, 2026-10-14). **Fixed:** detail stills (above).
      The first coaching pass misread Nepal d02, Nepal d14 and Havana d03; those are corrected in
      their coaching.md files.
   3. **Menus over gameplay** (TAB, Friends) in lead-in stills: Gibraltar d07, Route 66 d04,
      Nepal d08. Worth flagging per still so the coach doesn't have to spot them.
   4. About a third of deaths have no kill cam (the game or the player skipped it). That's expected.

**Overview at 2.5 s (2026-10-15):** `OVERVIEW_STEP` 2.5 s, 1×2 cells per sheet at the thumbnails'
full 1280 px (252 sheets for Havana). In the A/B it found real moments between deaths and three
pipeline timing errors that the 5 s / 780 px cells missed, for +39% cost. The numbers below are
the old 5 s setup.

**Overview sheets and coaching framework (2026-10-14, after comparing with a friend's tool,
devonbutler/overwatch-replay-coach, which has the model sample the whole match from contact
sheets):** each packet now has `overview/`: one scan thumbnail every 5 s, 2×4 cells of 780 px per
sheet, each labelled with the game clock, alive/DEAD (death to respawn) and event ids in that
window. They're built from the existing thumbnails, so no extra decode (12–32 sheets per game).
COST: about 1.8k tokens per sheet; 10 s spacing would halve it. The skill reads them before the
deaths. Each game report now grades the lessons file's current focus (Improved / Mixed / Not
improved / Not tested) and tags each death with a category (Recognition, Decision, Execution,
Positioning, Resource discipline, No credible lever). Policy for now (Noah): keep information over
saving tokens, and mark overspend with `COST:` comments instead of trimming.

**Full re-coach (2026-10-14):** all 9 games were re-coached with overview sheets, detail stills,
focus grading and categories (first versions kept as `coaching_v1.md`). Avoidable deaths: session 1
12 of 22, session 2 19 of 43. The top habit changed from "break line of sight at half HP" to "use the
escape (Katashiro Return, Fade) before 50 HP; play cover while it's on cooldown", which the old
stills couldn't show. Cost: roughly 330 overview sheets + 200 detail stills read for the pass.
Pipeline issues seen: stale `alive_before` making first_down wrong (Paraíso d01, Route 66 d02/d05),
killer-name splits, menus over gameplay, respawn read early (Lijiang d01).

**Re-coach with detail stills (2026-10-14):** Busan was re-coached on the new packets. Three of its
six deaths had been misread at the old resolution (an allied Zarya taken for the enemy one, the
killer's hero, a RIP-Tire kill), and the sharper HUD showed a new pattern: Fade on cooldown in all
four Moira deaths. The other 8 games still have their first-pass reports, apart from three
corrected deaths (Nepal d02/d14, Havana d03).

**Portability (planned, waiting on a 16:9 recording):** every ROI is still in 21:9 terms, either
1280-wide thumbnail px or game-area fractions. The plan is to anchor each to a corner or edge of the
game area in units of its *height*, since OW scales the HUD with height and ultrawide spreads it to
the edges, and to scale thumbnails to a fixed height. A centre crop of 21:9 footage is not a valid
16:9 test. New ROIs (stage 4) should already be written as corner offsets in height units.

Tesseract on Ubuntu 22.04 (4.x) read the `|` separator differently from the container's tesseract,
which is why the map is now looked up by list rather than split on `|`.

## Results already computed (session.json / match.json in each folder)

Session 1: `Overwatch 2 2026.10.13 - 20.18.33.01.mp4` (59.6 min)

| # | Span | Result | Queue | Map | Hero (final TAB) |
|---|---|---|---|---|---|
| 1 | 0:00:00–0:07:37 | defeat | QP | Grímsvötn (escort) | Doctrine. Recording starts mid-match |
| 2 | 0:09:51–0:17:39 | defeat | QP | Paraíso (hybrid) | Doctrine |
| 3 | 0:20:23–0:31:56 | victory | QP | Route 66 (escort) | Doctrine 3 min, then a switch (OCR "Mizuki") |
| 4 | 0:35:25–0:43:47 | victory | comp | New Queen Street (push) | OCR "Zenvattr", likely Zenyatta |
| 5 | 0:46:57–0:56:32 | victory | comp | Lijiang Tower (control) | OCR "Mizuki" |

Session 2: `Overwatch 2 2026.10.13 - 21.19.42.02.mp4` (76.3 min)

| # | Span | Result | Queue | Map | Hero |
|---|---|---|---|---|---|
| 1 | 0:02:42–0:20:16 | defeat | comp | Watchpoint: Gibraltar (escort) | Moira |
| 2 | 0:23:26–0:40:14 | defeat | comp | Nepal (control) | Moira |
| 3 | 0:44:08–0:52:29 | defeat | comp | Busan (control) | Moira. Rank after: Support Gold 4, 79% |
| 4 | 0:55:09–1:16:05 | defeat | comp | Havana (escort) | Lifeweaver. Recording ends 1:16:18 |

Doctrine and Mizuki are heroes newer than the model's training data. Read hero names off the screen,
and don't trust visual recognition.

## Output layout

```
<library>\<session>\                       e.g. ~\Videos\owcoach\2026.10.16 - 22.23.04.03\
    session.json            all matches; "video" = the recording's absolute path, matches[].dir = the folder name
    trend.json, coaching.md, .coach\*.jsonl    written by `owcoach coach`
<library>\coaching.html                   the page over everything (`owcoach site`)
    m01_victory_escort_dorado\
        match.mp4           stream copy of the game (+3 s pad)
        match.json          boundaries, result, map, mode, queue, clock, TAB timestamps (+ clip-relative)
        events.json, scoreboard_final.jpg, summary.jpg | rank.jpg, sheet.jpg
        packet\             packet.json, packet_slim.json, facts\dNN.md, frames\, overview\, moments.m3u,
                            notes\ (readers), coaching.md (writer)
<library>\<date> - <HH.MM> to <HH.MM>\      a combined summary over several one-game sessions
<library>\.cache\<recording stem>\         the scan cache
```
Paths inside the data are relative (session.json dirs, packet.json hero_notes to the profile,
history.sqlite packet to the library), so the library can move; `owcoach migrate --rewrite-only`
fixes older files. `Overwatch 2\_owcoach\` and `Overwatch 2\.claude\` are leftovers from
session 1, Noah's to delete.

## Performance (measured in the VM; the baseline to beat)

- Scan: ~80–90 s per 10 min of video per ffmpeg process (CPU HEVC 10-bit 5K decode, keyframes only,
  roughly single-threaded); 2 in parallel ≈ 13× realtime. ~10.5 min total for 2 h 17 m of footage.
- Features: ~20 s per 9k thumbnails. Segment + split: 45–56 s per session (tesseract + full-res grabs).
- Bridge write: 12 MB/s (irrelevant on metal).

## Next steps, in order

1. **Cut the clips** (top of this file). Confirm with Noah.
2. **Run natively on Windows** (his gaming PC has an NVIDIA GPU):
   - Install deps: Python 3.10+, `pip install numpy opencv-python`, ffmpeg (Gyan full build; confirm
     `ffmpeg -filters | findstr zscale`, since tonemapping needs zimg), Tesseract (`winget install
     UB-Mannheim.TesseractOCR`; it is **not** on PATH by default, so add it or make the binary path configurable).
   - Add GPU decode: `-hwaccel cuda` (or the `hevc_cuvid` decoder) and check whether `-skip_frame nokey`
     still applies with hw decode. If not, try `-hwaccel cuda` with a `select`/`fps` filter and compare.
     Tonemapping on GPU (`tonemap_cuda` / `libplacebo`) is optional; the thumbnails are small.
   - The VM workarounds can go or stay as no-ops: `--budget`, 600 s chunks. Keep `--jobs` and benchmark.
   - Re-run `scan → segment → split --cut here` on both sessions and compare with the tables above
     (regression check). Report wall time per stage.
3. **Fix rough edges**: snap hero OCR to a hero list (add new heroes), and handle multi-hero matches
   (the hero panel only shows the final hero). Unit-test the OCR readers on the saved
   `scoreboard_final.jpg` / `summary.jpg` / `rank.jpg` files.
4. **Toward "seconds"**: a live sampler (e.g. `dxcam`, 1 fps, downscaled) running during play can do
   boundary detection in real time, so the video is only touched for the cut and a few stills.
   Alternatively, watch the ShadowPlay folder and process incrementally.
5. **Coaching layer** (the actual product): per-match extraction of deaths (kill feed, "RESPAWN IN",
   kill cam), ult timing, ally-in-view as a positioning proxy, and the scoreboard/summary stats, fed
   to a Claude skill the way CoachClaude does it. Support role first.

Ask Noah before: deleting anything in his Videos folder, re-encoding (stream copy only unless asked),
or changing his ShadowPlay settings.
