---
status: accepted (not yet implemented; today only the skill text enforces it)
---

# Developer mode is enforced by the harness, not by the skill text

With developer mode off (the `dev` config key or `COACHCLAUDE_DEV`), the codebase must not be
changed during coaching. Today that rests on the skill's instructions alone: the headless
coaching runs started by `owcoach coach` are given Write/Edit with `acceptEdits` and run from
the repo directory, whatever the mode. A shippable tool cannot depend on the model choosing to
behave, so the coaching runs enforce it. With dev off, they run outside the repo, and their
write access covers only the data directories (reports, notes, lessons file).

## Consequences

- Any new way of launching the coach (a new driver, a new game) has to apply the same
  restriction. Wording in a skill is not enough.
