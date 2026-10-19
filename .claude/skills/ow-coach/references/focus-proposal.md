# The focus proposal

The focus in the lessons file is the player's. You grade it every game, and you never change its
wording, not even to sharpen it. When you think it should change, or at the end of every session
either way, you write a proposal and the player picks. `owcoach focus` applies the pick.

**Why:** between 2026-10-14 and 2026-10-16 the coach rewrote the focus three times on its own
(added the escape clause, added "above half, walk", then "a wall, not a pillar beside you"), so
the player was graded against wording they had never agreed to. The player: "let the user and
the agent agree on what the next session's theme will be." Patterns not chosen are not lost:
they stay in the lessons file under "Focus options" with their evidence.

## When

After the session summary (SKILL.md section 4) and the lessons update (section 5), every
session. In an interactive session, then ask (below). In a headless process (`coach_session.sh`),
write it and say in chat and at the end of `<session>/coaching.md` that it's waiting.

## Where and shape

`focus_proposal.md` in the profile dir (`python -m owcoach config profile`). Exactly this
shape, since `owcoach focus` parses it:

```
# Focus proposal, <YYYY-MM-DD>

After <session date and record>. Pick with `owcoach focus N` (two numbers for two habits), or
`owcoach focus --set "..."` for your own wording. What you don't pick stays listed as an option.

## 1. Keep: <short title>
**<the current focus wording, verbatim>**
- Grades so far: <one line per session: held/tests per part>
- This session: <what the tests showed, with death ids and clocks>
- Would test it next: <the situation>

## 2. <short title>
**<trigger, then the action, at most two sentences; wording the player will be graded against>**
- Evidence: <this session's count and ids; earlier sessions' count from the lessons file>
- Would have changed: <the deaths or fights it would plausibly have saved, with ids (inference)>
- Would test it next: <the situation; how it will be counted>

## 3. ...
```

Rules:
- Option 1 is always "keep", with the current wording verbatim (both bullets if the focus has two)
  and everything the lessons file holds under it (grades so far, per game), so that picking it
  loses nothing: `owcoach focus` replaces the whole section with the chosen options.
- Two to four more options, from the recurring patterns, the session's habits, and the "Focus
  options" already in the lessons file. Each is one habit with a trigger the player can notice in
  the moment and an action; not "position better".
- The first line under each heading is the bold wording and nothing else. That's what the
  lessons file will carry.
- Evidence is counts and ids, this session and before. Say what counts as a test next session so
  the grade (rubric, "Focus grade") is a count and not a feel.
- A hero-specific habit is fine when the pattern is (e.g. Mizuki's Return prompt), but say which
  heroes it applies to.
- Don't rank them or recommend one in the file. The player ranks. In chat you may say which you
  would pick and why, in one line.

## Asking (interactive sessions)

Use AskUserQuestion with one option per proposal entry (label = the title, description = the
wording and the one-line evidence), multi-select, with the current focus first. "Other" is their
own wording. Then run `python -m owcoach focus N [N]` (or `--set "..."`) from the repo root and
show the resulting "Current focus" section. Don't edit the lessons file's focus by hand.

## Reading a pending proposal (start of a session)

If `focus_proposal.md` exists in the profile dir, the player hasn't picked since the last session.
Interactive: ask now, before coaching, so the games are graded against the focus they chose.
Headless: coach against the current focus and say the proposal is still waiting.
