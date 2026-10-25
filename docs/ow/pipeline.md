# Overwatch pipeline

The Overwatch coach (`owcoach/`) turns ShadowPlay recordings of a session into per-match
packets, then has Claude Code coach from them. This is the technical reference: what each stage
does, how it was validated, and its known limits. Decisions and their reasons are in
`docs/adr/`.

Deterministic local extraction produces the facts; Claude only judges from them
([ADR 0004](../adr/0004-facts-vs-judgement.md)).

## Where things are

`owcoach/config.py` owns every Overwatch path. `~/.config/coachclaude/config.json` (section `ow`)
names the capture folder(s), the **library** (`~/Videos/owcoach` by default: `<session>/`
folders, `.cache/<stem>/` scan caches) and the **profile** (`~/.local/share/coachclaude/ow`:
profile.json, nameplate, portraits, hud_layouts, history.sqlite, lessons.md,
focus_proposal*.md, heroes/). `python -m owcoach config` prints them. The recordings stay in
the ShadowPlay folder and are read-only input
([ADR 0010](../adr/0010-packaged-skills-and-data-locations.md)).

`owcoach new` / `run` / `coach` / `site` are the user-facing commands (README). `run`
(`pipeline.run`) runs every local stage, skipping what is done. The coaching driver is
`owcoach/coach.py`. `owcoach/site.py` collects every session and match for the shared renderer
(`coachlib/site.py`), which writes `<library>/coaching.html`; `run` and `coach` rebuild it, and
`coach` opens it when done (`--no-open` skips that). Every rebuild also refreshes the desktop
link (`coachlib/launcher.py`).

## Recording facts (measured from Noah's files)

| Property | Value |
|---|---|
| Recorder | NVIDIA ShadowPlay, manual record, files in `~\Videos\NVIDIA\Overwatch 2\` |
| Naming | `Overwatch 2 YYYY.MM.DD - HH.MM.SS.NN.mp4` |
| Capture | **5120×1440** (32:9 monitor), game renders **21:9 = 3456×1440 at x=832**, black pillars either side |
| Codec | **HEVC Main10, HDR10** (PQ / BT.2020, full range), 60 fps nominal, VFR |
| Bitrate | ~61 Mbps (≈27.6 GB/h). Suggest lowering to ~15 Mbps and turning HDR capture off |
| GOP | **keyframe every 0.5 s**, so `-skip_frame nokey` gives a free 2 fps sample and `-c copy` cuts land within 0.5 s |
| Audio | AAC 192k |
| In-game | default HUD; OW performance overlay on (FPS/TMP/LATENCY/IND/clock, top-right) |

The 21:9 crop is auto-detected (`probe.detect_crop`). HDR is tonemapped with
`zscale → tonemap=hable → zscale` (`scan.TONEMAP`). If the recording changes (SDR, different
resolution or aspect), the HUD template and pixel ROIs below **must be recalibrated**: they are
in 1280-wide, tonemapped, cropped-thumbnail coordinates.

Ask the player before deleting anything in their Videos folder, re-encoding (stream copy only
unless asked), or changing their ShadowPlay settings.

## Code layout (`owcoach/`, Python 3.10+, deps: numpy, opencv-python, ffmpeg, tesseract)

```
owcoach scan    SESSION.mp4 [--jobs 2] [--chunk 600] [--budget S] [--hwaccel auto|cuda|none]
owcoach segment CACHE
owcoach split   CACHE [--cut here|script|none] [--pad 3]
owcoach sheet   CACHE [--every N] [--labels]          # contact sheets for eyeballing
```
Cache: `<library>/.cache/<video stem>/` (`config.cache_for`; `scan.json`, `index.json`,
`frames/<chunk>/*.jpg`, `features.npy`, `matches.json`, `states.json`, `events.json`, `hud.json`).
Every CACHE argument also accepts the recording path or its bare stem (`config.resolve_cache`).

- `probe.py`: ffprobe wrapper (HDR flag, VFR flag), keyframe listing, black-bar crop detection.
- `scan.py`: keyframe-only decode → crop → scale 1280 → tonemap → JPEG thumbnails, with timestamps
  from `showinfo` (uses `-copyts`, so they're absolute). Chunked + resumable + parallel; CUDA
  decode when it works (`--hwaccel auto`). `grab_frame()` pulls one full-res (or ROI) frame
  straight from the source video for OCR/stills.
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
       matches, overtime frames by eye, and end states that fit each result. Distances still
       carry the odd misread (a stray small value between big ones); QP progress is only a bar
       (not read); Flashpoint/Clash phrases are untested (no footage).
   - Not yet: assists (icons in the killer cell), snapping names to the scoreboard roster
     (OCR reads 0 as O), ult charge %, digit templates for 0 and 1, QP payload bar.

## Stage 5: the per-match packet

`packet.py`, `owcoach packet CACHE [--game N]`, after `split`. This is the input to the
generative coaching. Claude takes text and images, not video, so each moment is a few stills
plus JSON.
   - Written to `<match dir>/packet/`: `packet.json`, `frames/`, copies of scoreboard_final / summary
     / rank, and `moments.m3u`. The playlist is for Noah: VLC plays each death and ult straight
     from `../match.mp4` (12 s before, 6 s after), so no extra clip files.
   - In `packet.json`, times are `t` (s since match start), `clock` (m:ss) and `video_t`
     (match.mp4). It holds match facts, the hero timeline, objective (rounds, sides, overtime,
     scores, series), one merged `timeline`, deaths, ults, final blows, `alive_series` and `notes`
     (known limits, for the analyst). `packet_slim.json` is the same without frames, series and
     raw hud / motion arrays (108 KB vs 507 KB for Havana), for the writer.
     `owcoach packet --refresh` rewrites packet.json from the stills on disk (seconds a match).
   - Deaths are found in the kill feed, then **re-anchored on the "YOU WERE ELIMINATED BY" banner**
     (`assets/eliminated.png`, grey-scale NCC on thumbnails, searched centre-bottom because its
     height moves with stacked notices; banner 0.6–1.0, alive frames ≤ 0.58). Onset = a thumbnail
     ≥ 0.6 with another ≥ 0.55 in the next two, searched from 14 s before the feed (but not before
     the previous death + 8 s); death = onset − 0.25 s. 60 of 65 deaths get a banner anchor; the
     rest (menus, spectating) use feed − 0.5 s. It fixed every late feed: NQS d01 2.8 s, Gibraltar
     d06 3.3 s, Lijiang d05 6.2 s, Havana d08 6.2 s, Nepal d12/d14 1.7 s. Each death records
     `anchor` and `feed_lag_s`. An HP = 0 template on the HUD was tried first and dropped: the HUD
     block shifts per hero and "250|250" matched "0|".
   - Death stills: `lead_in` full screen at -10 / -6 s, then **`detail` stills every 0.5 s from
     -3 s to the death**. A detail still is the centre 1.089 × 0.611 game-area heights at native
     resolution with the bottom-left (HP) and bottom-right (abilities / ult) HUD corners under
     it, 1568 × 1140 at 1440p. Why: the full 3456-wide frame downscaled to 1568 px left HP,
     names, team colours and ability icons illegible, and the first coaching pass misread
     several deaths (a teammate Juno as an attacker, the player's own Binding Chain as an enemy
     Ana, a Fade on cooldown missed). A 3-death A/B (dense 4 fps vs these) showed 2 fps over 3 s
     loses nothing. The own-view mask is *not* an alive signal: the red low-HP overlay hides the
     HUD while still fighting, and the death camera keeps it.
   - **First pass and extras:** detail and kill cam are decoded every 0.1 s, but only the first
     pass is read by default: detail every 0.5 s, 4 kill-cam stills. The rest carry
     `"extra": true` in `frames` and are read on demand, up to 12 per death, for a specific
     question. Why: in the Havana A/B, reading all of them at 10 fps (+84% cost) fixed one
     misread (d10: the car was covering the player) but added a confident wrong one (d08: the
     direction of a dash). Decoding is free; reading is what costs. ~540 stills for Havana, 100 s.
   - Kill cam stills are found by the "KILL CAM" label (`assets/killcam.png`, NCC ≥ 0.65; kill cam
     0.72–1.0, everything else ≤ 0.54). Up to four per death, 2–14 s after the feed. 43 of 65 deaths
     have one; the rest were skipped. Each death records `kill_cam`, `alive_for_s`, `respawned`
     (first steady own view after it) and `ult_ready`/`ult_held_s`.
   - Used ults get stills at -3, +0.5 and +2.5 s around the press. Stills are the full game area at
     1568 px wide (Claude's native size), grabbed with NVDEC: 9 s for a match, 34 s and 59 s per
     session.
   - Size: 33–173 stills per match (Nepal, 15 deaths, is the largest). Detail stills are ~2.4k
     tokens each, full ones ~1.4k; a death costs about 2× what it did with the old six lead-ins.
     Rebuilding both sessions' packets takes 80 s + 140 s.
   - Rule flags per death (`first_down`, `team_ahead`/`team_behind`/`even_fight`, `short_life`,
     `died_with_ult`, `overtime`, `contested`, `repeat_killer`) and per ult (`held_long`,
     `ult_died_with_it`, `died_while_holding`) plus `counts.death_flags`. These are leads for the
     analyst, the way `hotscoach analyze` works.
   - Respawn is approximate: the death camera and spectating a teammate both pass the own-view
     check, so it's searched from 8 s after the feed. It can still read 1–2 s early. Fix with a
     per-frame nameplate check.
   - `events.match_ult`: an ult whose icon vanishes within 2 s of a death is `died_with_it`, not
     `used`. Found by the first coaching run (Busan u02).
   - **Facts block** (`facts.py`, `packet/facts/dNN.md`): a per-death text block pasted into the
     reader brief (HP from -10 s, slots by name, every press, the low episode, the feed). In the A/B on 7 labelled matches it cost
     nothing extra and moved the hardest deaths toward Noah's accounts.

### Overview sheets

Each packet has `overview/`: contact sheets of the whole match built from the existing scan
thumbnails, so no extra decode. Cells are `OVERVIEW_STEP` = 2.5 s apart, two per sheet at the
thumbnails' full 1280 px, each labelled with the game clock, alive/DEAD (death to respawn) and
the event ids in that window. The first pass is every other cell (5 s); the in-between cells are
`b` sheets marked `extra`, read around fights. In the A/B the 2.5 s cells found real moments
between deaths and three pipeline timing errors that 5 s / 780 px cells missed, for +39% cost.
COST: ~6 first-pass sheets a minute (~1.8k tokens per sheet at the old 780 px size).

### HUD reader (`hud.py`)

Why the HUD is read by the pipeline: [ADR 0004](../adr/0004-facts-vs-judgement.md). Each
death's `hud` block in packet.json holds HP every 0.1 s (`hp`, with a confidence; `hp_max`;
`hp_zero_dt` = the frame HP first read 0, which precedes the banner anchor by up to ~1 s), each
ability slot's state per frame (`abilities`: ready / cooling with the countdown / blocked = red
slash / active / hidden) and a one-paragraph `summary` the readers quote.
   - Read from the detail stills, which carry the HUD strip at native resolution; no extra decode.
     ~2 s per match. All constants are at 1440p and scaled by the game-area height.
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
     Brigitte 89/194/299/404): learned from all of a hero's deaths in a match and cached in
     `<profile>/hud_layouts.json`, in heights from the right edge. A longer learned layout that
     agrees with the cached one replaces it.
   - States per slot: a countdown that reads (own italic templates, `assets/cooldown_digits.npz`,
     bootstrapped from 1,400 harvested glyphs clustered and labelled by eye, 99.9 % self-match)
     means cooling; else white fill >= 30 % ready; else red >= 6 % blocked. Smoothed per slot by
     a 5-frame majority, and the countdown must step down one per second (validation: Moira's
     Fade 5->2 and Orb 8->5 over 3 s, Lifeweaver's dash 4->1).
   - Fixes from the labels (`overlay.py`, commit 7b3bdfa): (1) the SELECT PERK prompt covers the
     nameplate the own-view check reads, so stretches with an unspent perk lost the 2 fps HUD,
     their fights and low episodes, and their presses read as travel; hudscan now keeps a
     non-own frame whose nameplate area is the orange box and whose HP reads (+31 s / +72 s of
     live HUD per session), and `match_heroes` accepts the box. (2) With the Tab scoreboard
     open the health box shows 0; those frames and the 0.5 s fade-in are hidden (series and
     death stills), and the facts block says so. (3) A kill, death or ult opens a fight window
     on its own (6 s before, 2 after). (4) Slot state "active": a red/orange in-use icon without
     the diagonal slash (Katashiro's doll out with the RETURN prompt, a platform placed);
     "blocked" needs the slash. (5) Lead-in rows nearest each whole second.
   - Not read yet: which key each slot is (the LSHIFT / E / SPACE labels under the squares;
     slot order left-to-right is reported instead), the ult charge %, and the weapon / ammo
     panel. A slot can be missed when its square is an outline for every clear frame of a hero
     in a match (then the cache from an earlier match fills it in). Slot names for Doctrine stay
     "slot N" (learned cooldowns 3 / 3 / - / 5 don't match the note's 8 / 14).

### Whole-match HUD series (`hudscan.py`, `owcoach hud`)

The HP and ability reader run on every own-view keyframe (2 fps) of the session, from two
roiscan regions (`hud_hp`, `hud_abil`: the same strips a detail still carries, cropped at native
resolution, free because that pass decodes every keyframe anyway; +92 s per session to re-crop).
`hud.json` holds one row per frame; `owcoach hud` takes ~170 s for a 1.3 h session (5,858
frames, 98.8 % with HP). Slot layouts are learned per hero from 160 sampled frames of its
own-view time, which found all four of Doctrine's and Brigitte's slots where single deaths had
found two.
   - `packet.json` -> `hud_game` per match (`hud.game_hud`): `series` [[t, HP, [slot states]]],
     `low_episodes` (every stretch under half HP), `presses`, `fights` (HP changes >= 10 between
     keyframes, kills, deaths and ult presses, merged within 8 s, >= 4 s), `stats` and
     `stats.by_hero` (time under half %, episodes by outcome, presses under half, median HP at
     press). Havana: 22 low episodes, 8 of them deaths.
   - The focus is graded from these counts instead of readers' impressions, so two runs give
     the same grade, and the overview readers get the fights list so they spend their extras there.
   - Cleaning: max HP = the mode per hero (one misread like 2507 would make everything "low");
     the same despike / dropped-digit pass as around deaths; episodes shorter than 0.75 s that
     didn't end in a death are misreads; a press needs two steady frames on each side.
   - Every slot, no fixed escape slot ([ADR 0008](../adr/0008-no-per-hero-kit-rulebook.md)).
     `presses` cover every slot with a context (travel = outside a fight, engage = in a fight at
     or above half, low = in a fight under half) and the countdown the press started from;
     `low_episodes` carry every slot's state at the start and, for each slot not ready, the
     last press before it (how long before, at what HP, in what context): "fought without
     Fade, spent 11 s earlier walking in at full HP" is a fact the writer can state.
     `stats.by_hero.slots` learns each slot's cooldown length from the presses (Moira 6 / 8 =
     Fade / Orb; Lifeweaver 12 / 18 / 5 = Petal / Grip / Dash), so the kit is identified
     without keybinds. The focus is graded from three factual rates (fights started with the
     escape cooling from a travel press; low episodes with it ready and pressed; low episodes
     with it cooling that ended in death).
   - **Hero notes** (`herowiki.py`, `owcoach hero <Name>`): the Overwatch wiki's page
     (overwatch.fandom.com, MediaWiki API, wikitext) parsed into `<profile>/heroes/<Hero>.md`:
     each ability with its default bind (the wiki's "ability 1" = LSHIFT, "ability 2" = E,
     "ability 3" = SPACE), cooldown, charges, official description and a few details ("Dash is
     horizontal only", "the platform blocks line of sight"), plus perks. `packet.json` ->
     `hero_notes` lists the ones that exist and the briefs pass the path. Noah runs
     `owcoach hero` rarely (a new hero, a rework), not as part of coaching.
   - Not done: ult charge % from the existing `ult` crop (same digit reader); the enemy/ally
     HP of targets; a cheaper 10 s overview first pass that reads the 5 s cells only in fights.

### Egomotion (`motion.py`)

Dense flow (DIS, 480 px wide) between consecutive 0.1 s detail stills on the centre crop,
weapon / hands / reticle masked. Far-field median flow = the camera's turn (degrees at the
default 103° FOV); near-ground parallax against it = strafe and forward / back. Far-field
inlier fraction < 0.30 = a cut: a "jump" when the pixel difference is wholesale (>= 45 / 255:
teleports, freezes, the death cam, menus), else "no stable read" (close quarters, looking at the
ground, a dash blur). The facts block carries the trace per 0.5 s, camera-relative; movement
comes from it and only its direction relative to the enemy or cover stays inference. Against
the labels it read Havana d02 forward at the Tracer, d05 / d10 strafing, Grímsvötn d03 forward,
23° left, forward; Nepal d04 / d07 unreadable and said so. A dash can't be told from
close-quarters chaos by flow, so it stays the HUD press record's job. Not done: the 2 fps
lead-in (0.5 s apart; only the turn would be recoverable); a per-death static mask learned from
the frames instead of the fixed weapon box.

## Stats and trends (`stats.py`, `history.py`, `owcoach trend`)

Deaths, time dead, healing and damage per 10 min of active time, and a flag when they move
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
     matches.
   - **History:** `history.sqlite` in the profile dir, one row per match, upserted by `packet`.
     Main hero is the hero with the most total time.
   - **`trend`:** latest session (or `--games N`) vs all earlier matches, filterable by role or
     hero. Rates are time-weighted. A change is `better`/`worse` at ≥10% and ≥2 standard errors
     with ≥5 baseline matches.

## Stage 6: the coach

The Claude Code skill `coachlib/skills/ow-coach/` (SKILL.md, references/rubric.md,
references/subagents.md, references/focus-proposal.md, references/lessons-template.md). It
writes `packet/coaching.md` per match and keeps `lessons.md` in the profile dir. Data errors it
finds go under "Pipeline issues" instead of being patched. Focus ownership and the proposal
flow (`focus.py`, `owcoach focus`): [ADR 0003](../adr/0003-focus-loop.md).

- **Readers and writer:** the main context reads no images; reader subagents write
  `packet/notes/`, one writer per match writes the report
  ([ADR 0007](../adr/0007-reader-writer-subagents.md)). `owcoach notes <match dir>` concatenates
  a match's notes into `notes/all.md` so the writer reads one file.
- **Processes:** `owcoach coach` runs one `claude -p` per match, then one for the session
  summary and lessons ([ADR 0006](../adr/0006-one-headless-process-per-match.md)). Logs go to
  `<session>/.coach/*.jsonl`; the cost estimate comes from the logged `total_cost_usd`.
- **Defaults and why:** readers and writer at effort low (`--effort`, `--writer-effort`), all
  Opus (`--reader-model` to change the readers).
  - Low-effort readers (A/B on 7 matches with labelled deaths, scored against
    `labels/deaths.md`): ~25 % cheaper and 0-3 min faster than default; better on 6 of the 12
    labels, equal on 5, worse on 1.
  - The writer: its transcript showed ~40 turns re-reading ~110k cached tokens each. With
    `packet_slim.json`, `notes/all.md`, two Reads in one message and a one-line reply, plus low
    effort, the writer took 96-134 s, matches 5.4-9.6 min (was 7.2-14.0), $51.01 for the 7
    (was $62.32); equal on 11 of 12 labels.
  - Reader model: Opus is kept. Decided 2026-10-21 from a three-arm A/B (Opus, Sonnet 5.5,
    Haiku 5.5 readers; 5 labelled matches, 9 deaths scored blind), recorded in full on
    [issue #20](https://github.com/theNoahWilkes/CoachClaude/issues/20). Sonnet tied Opus
    on quality (44/90 each) for 25 % less at list price but 15 % slower, and used as much
    of the plan's five-hour window as Opus did: the window tracks token volume, not price,
    so a cheaper reader model saves a subscriber nothing. Haiku scored 36/90, lost two lever
    labels and read movement wrong in 6 of 9 deaths. The first A/B (2026-10-16, Sonnet
    readers, resumed after a usage-limit cut) had found about -25 % and 3 of 12 labels lost.
  - Where the cost goes (11 runs, 2026-10-16 to 2026-10-20; split per agent from the
    stream-json logs): overview readers 31 %, main process 26 %, death readers 25 %, writer
    12 %, ults 5 %; by token type cache writes 58 %, output 30 %, cache reads 12 %. Images
    are ~300k tokens a match. Every arm of the A/B scored about half against the labels,
    wrong on movement in 4-6 of 9 deaths and right on the lever once in 27: the quality
    ceiling is the movement line and the writer's lever judgement, not the reader model.
    Next cost levers are token volume (briefs built by `owcoach` with one `claude -p` per
    piece, a smaller detail-still crop now the HUD is read locally, fewer first-pass stills).
- **Timing:** subagents start ~8 s apart even when launched in one message, and about 20 can
  run at once. On new footage (three one-match recordings, 2026-10-17) the local stages took
  1.5-3.5 min per recording and coaching 5.6-8.7 min and $4.41-7.98 per match.

## Known limits

From the coaching passes and the labels, still open:
   1. **Killer names split across OCR variants** (ANGEL2CHAKS / 4ANGEL2GHAKS, ENIGMAL / ENIGMAL_),
      which undercounts repeat killers. Fix: snap to the scoreboard roster.
   2. **Menus over gameplay** (TAB, Friends) in lead-in stills: Gibraltar d07, Route 66 d04,
      Nepal d08. Worth flagging per still so the coach doesn't have to spot them.
   3. About a third of deaths have no kill cam (the game or the player skipped it). That's expected.
   4. Stale `alive_before` making `first_down` wrong (Paraíso d01, Route 66 d02/d05); respawn
      read early (Lijiang d01).
   5. Route 66 d04's 3:40-3:58 fight is missing from `hud_game.fights`; Grímsvötn d03's 2 fps HP
      at -6 s is ~1 s off the still.
   6. From the 2026-10-17 run: a Dorado death at ~4:22 the packet missed; Lijiang's Katashiro
      reads as cooling while the doll is out (the active state missed it there). A 3-min
      fragment that starts mid-match segments as `m01_unknown`.
   7. Late feed reads and stills too small to read were fixed (banner anchor, detail stills,
      above).

**Portability (planned, waiting on a 16:9 recording):** every ROI is still in 21:9 terms, either
1280-wide thumbnail px or game-area fractions. The plan is to anchor each to a corner or edge of the
game area in units of its *height*, since OW scales the HUD with height and ultrawide spreads it to
the edges, and to scale thumbnails to a fixed height. A centre crop of 21:9 footage is not a valid
16:9 test. New ROIs (stage 4) should already be written as corner offsets in height units.

Tesseract on Ubuntu 22.04 (4.x) read the `|` separator differently from the container's tesseract,
which is why the map is now looked up by list rather than split on `|`. On Windows it is not on
PATH by default; the config's `tesseract` key names it.

## Reference sessions (session.json / match.json in each folder)

The regression set; `labels/deaths.md` labels deaths from these.

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
        match.mp4           stream copy of the match (+3 s pad)
        match.json          boundaries, result, map, mode, queue, clock, TAB timestamps (+ clip-relative)
        events.json, scoreboard_final.jpg, summary.jpg | rank.jpg, sheet.jpg
        packet\             packet.json, packet_slim.json, facts\dNN.md, frames\, overview\, moments.m3u,
                            notes\ (readers), coaching.md (writer)
<library>\<date> - <HH.MM> to <HH.MM>\      a combined summary over several one-match sessions
<library>\.cache\<recording stem>\         the scan cache
```
Paths inside the data are relative (session.json dirs, packet.json hero_notes to the profile,
history.sqlite packet to the library), so the library can move; `owcoach migrate --rewrite-only`
fixes older files.

## Performance (measured in the session-1 VM: 2 cores, no GPU)

- Scan: ~80–90 s per 10 min of video per ffmpeg process (CPU HEVC 10-bit 5K decode, keyframes only,
  roughly single-threaded); 2 in parallel ≈ 13× realtime. ~10.5 min total for 2 h 17 m of footage.
- Features: ~20 s per 9k thumbnails. Segment + split: 45–56 s per session (tesseract + full-res grabs).

Not done: a live sampler (e.g. `dxcam`, 1 fps, downscaled) running during play could do boundary
detection in real time, so the video is only touched for the cut and a few stills; or watch the
ShadowPlay folder and process incrementally.
