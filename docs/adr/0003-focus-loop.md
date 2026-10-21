---
status: accepted (not yet implemented; Overwatch uses a proposal menu, HotS edits its own focus)
---

# The focus loop: one focus, a light check-in, an independent pattern finder

The player works on at most one focus at a time. The coach gives general feedback on every
match, and focus feedback when there is a focus. The two coaches had diverged: the Overwatch
coach once reworded the player's focus three times and was then forbidden to touch it, which
made switching clunky (leave the chat, run `owcoach focus N`). The HotS coach kept rewriting its
own one-or-two habits. Both now follow this single loop, built to stay light and to avoid
stagnating on one focus.

- **No focus:** the coach picks one from the session's patterns, records it straight away, and
  says it can be changed. It does not wait for approval.
- **Focus check-in:** coaching opens by naming the focus to be graded. If there is a focus
  proposal, the coach offers that single alternative, with keeping the current focus as the
  default. With no proposal it is one line, not a question. One answer covers the whole backlog.
  The player switches by saying so; the `focus` command is plumbing the skill calls.
- **Two separate jobs in the session summary:**
  - The **pattern finder** looks for patterns across the session's matches and is not told the
    focus.
  - The **focus grader** judges improvement or regression on the current focus.

  The pattern finder's section is written before the focus is introduced.
- **Patterns become proposals.** A pattern that matches the focus is a no-op. One that matches
  a retired focus is offered as a regression ("you had fixed this; it is slipping"). Any other
  pattern can become the focus proposal, and there is at most one proposal at a time.
- **Evidence.** A standout problem can earn a proposal from a single session. Improvement on the
  focus is called out after one session, but earns a switch proposal only after two.
- **Declines are a timeout, not a ban.** After two declines in a row, a proposal is not offered
  for the next two sessions. After that it can come back if the evidence still holds.
- **Retired focus.** A focus the player moved past is kept in the lessons file. It is not
  graded, and it returns only as a regression proposal.

## Considered Options

- **The player owns the focus, and the coach only proposes from a menu (Overwatch today).**
  Rejected: it adds friction, and choosing from a menu is a buffet where the coach should be
  making one judgement.
- **The coach owns and rewrites the focus (HotS today).** Rejected: the focus drifts and loses
  meaning for the player.
- **Proposals at the end of the summary.** Rejected in favour of the check-in: a proposal is
  easy to miss at the end of a report, and the start of coaching is when the player is thinking
  about what to work on.
