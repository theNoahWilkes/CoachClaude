# No fixed escape slot and no per-hero kit rulebook

The pipeline does not decide which ability is a player's "escape". It records facts for every
ability slot (each press with its fight context and the countdown it started from; each
low-HP episode with every slot's state and the last press before it), and learns each slot's
cooldown from the presses so the kit is identified without keybinds. Whether a ready ability
was a way out is the coach's judgement from its own knowledge of the kit, kept as inference
when it rests on the scene. Which slot counts as the escape for grading is decided once per
hero by the coach and recorded in the lessons file.

"Escape" is contextual: Dash is lateral only, Petal vertical only, a teleport needs a teammate
alive. A fixed escape slot in the pipeline got that wrong.

## Considered Options

- **A per-hero kit rulebook** spelling out what each ability can and can't escape from. Tried
  for a few hours on 2026-10-16 and dropped: it re-teaches the model Overwatch one hero at a
  time and boxes the coaching in.
- **Hero notes** (`owcoach hero <Name>`, parsed from the Overwatch wiki) were kept, but only as
  optional reference data for heroes or reworks newer than the model. The coach must work
  without them and never fetches them.
