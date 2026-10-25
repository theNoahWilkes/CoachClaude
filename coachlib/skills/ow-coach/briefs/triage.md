You are picking the moments worth coaching in one Overwatch 2 session, from text only, before
anyone looks at an image. Readers will then read the stills of the moments you pick and nothing
else, so a moment you leave out is not coached.

Digest: {{DIGEST}} (every match of the session: each death's facts block, the death chains,
ults, fights, final blows and the focus tests; facts read locally, given). Read it in one go.
Lessons file: {{LESSONS}} (read "Current focus" and "Recurring patterns"; don't edit it).
Player {{PLAYER}}. Current focus: {{FOCUS}}
Rubric: {{SKILL_DIR}}/references/rubric.md. Read its "Deaths" and "Blind spots" sections.

What a moment is: a bad death, a particularly bad decision, a teachable moment, or a standout
good play to keep. The player wants about five per session in the summary; you shortlist about
{{N}} so the readers can confirm or drop some. Choose the moments that would teach the most,
not the most dramatic. Spread them across the matches when the session allows, but don't pad a
quiet match.

- The flags are leads, not verdicts: a death with no flag can be the best moment of the session
  (a decision that trips no rule), and a flagged one can be nothing (team already lost the
  fight). Read the facts block: what was ready, what was pressed and when, the HP, the alive
  counts, what the feed shows.
- A death chain (listed per match) is one moment, told from its first death: list its deaths
  together, e.g. "m03 d03+d04". The first death is usually the decision; the rest is what it cost.
- A good play has no death to anchor it: cite its clock (a fight won at 2v5 with the player
  alive, an ult that turned a fight, a low-HP episode survived with the escape held).
- Repeat patterns from the lessons file are worth one example, the clearest one, not every
  instance.
- Mundane deaths stay out: a death in a fight the team had already lost, burst with nothing to
  answer it, the last seconds of a decided round.

Write {{OUT}} in exactly this shape, and nothing else:

# Triage: {{SESSION_NAME}}
## Candidates
One line per moment you considered seriously, picked or not: <match> <id or clock>, one line on
why or why not. Keep it short; it's how the pick is checked against a full read.
## Shortlist
- <match> <death id, ids joined by + for a chain, ult id, or clock> | <kind: bad death / bad decision / teachable / good play> | <why it's worth the player's time, one line> | <what the reader should look for in the stills>
(about {{N}} lines, best first. Ids exactly as the digest writes them: m03 d04, m03 d03+d04, m06 u02, m01 3:35.)

Then reply with one line: "triage: <n> shortlisted".
