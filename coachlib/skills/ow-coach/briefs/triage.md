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
- A death that breaks the current focus or a recurring pattern is a strong pick even when the
  pattern is already in the lessons file: the repeat is what the player most needs to see. An
  escape that was ready, or a prompt that was on screen, and not used is the clearest kind.
  Take the clearest instance per match, not every one.
- Most of the shortlist is bad deaths and bad decisions; at most two good plays and one ult.
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
