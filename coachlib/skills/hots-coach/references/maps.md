# Map notes

Objective detection depends on `OBJECTIVE_RE` in the script. Verified against real
replays on build 98304 unless marked otherwise.

| Map | Lanes | Objective event(s) | Notes |
|---|---|---|---|
| Dragon Shire | 3 | `DragonKnightActivated` | Two shrines; team holding both gets the Knight. |
| Towers of Doom | 3 | `Altar Captured` | Only towers damage the core; every altar is a body-count fight. |
| Warhead Junction | 3 | `NukesSpawned`; `WarheadJunctionNukeDropped` = died carrying | Fire nukes quickly; Abathur mines warhead spawns. |
| Infernal Shrines | 3 | `Infernal Shrine Captured` | Guardian race; fight if losing the race. |
| Tomb of the Spider Queen | 3 | `SoulEatersSpawned` | Gems drop on death; turn in often. |
| Volskaya Foundry | 3 | `VolskayaCapturePointComplete` | Capture point; healer generally stays out of the mech. |
| Braxis Holdout | 2 | `BraxisHoldoutMapEventComplete` | Two-lane: healer goes with the four, never solo. |
| Garden of Terror | 3 | none emitted | Objective not detectable; skip pre-objective checks. |
| Hanamura Temple | 2 | none emitted | Payload not detectable; 1-4 split, healer in the four. |
| Haunted Mines | 2 + mines | `HauntedMinesGolemsSpawned` (fixedData TeamID 4096=team 0, 8192=team 1; SkullCount/4096 = skulls) | Fires when mines close, so "before objective" = died in the mines fight. Mine-open isn't emitted. |
| Sky Temple | 3 | `SkyTempleActivated` | `SkyTempleCaptured`/`ShotsFired` fire every second a temple is held; don't match them. |
| Cursed Hollow, Battlefield of Eternity, Blackheart's Bay, Alterac Pass | - | unverified patterns in `OBJECTIVE_RE` | Check `timeline` output on first replay and update this table. |

When a new map shows up, run `timeline`, look for map-specific `SStatGameEvent` names
(dump them with a few lines of Python if needed), add any objective event to
`OBJECTIVE_RE`, and record it here.
