---
status: accepted
---

# Up to three focus items, turned on and off on the page

Supersedes the "at most one focus" rule in [0003](0003-focus-loop.md) and its glossary entry.
The rest of 0003 (the check-in, the separate pattern finder and focus grader, decline timeouts,
retired focus) stands.

Picking a focus from the page (ADR 0013) first copied the CLI's menu: confirm one option, which
replaced the whole focus. The player found that clunky and at odds with how they work, which is
sometimes two habits at once. Noah, 2026-10-26: show the current focus items, let the player
change them, highlight when coaching has a new one, let them write their own, and cap them at
three with a nudge toward one or two.

- **Focus items with a toggle.** The page's Focus page lists every item: active ones (the
  lessons file's "Current focus") and set-aside ones ("Focus options"), each with an
  Active / Off toggle. Turning one off keeps it, with its grades, under "Focus options".
- **New from coaching.** Options in a pending focus proposal that the lessons file doesn't hold
  yet are shown with a "new from coaching" badge, and the page has a banner. The first change on
  the page files every proposal option under "Focus options" and retires the proposal file.
- **The player's own wording** is added as an active item straight away.
- **At most three active.** At three the page says one or two work better; a fourth is refused
  until one is turned off. `owcoach focus N` keeps the same cap.
- **CLI parity:** `owcoach focus --on/--off/--add "wording"` does what each button does.

The coach still grades every active item each match and never rewrites an item's wording.

## Considered Options

- **Keep one focus (0003).** Rejected by the player: two habits at once is how they practise.
- **No cap.** Rejected: more than a few habits can't be held in mind in a fight, and the coach
  grades each one every match, so the report grows with each item.
