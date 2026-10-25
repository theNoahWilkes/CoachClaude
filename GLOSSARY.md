# CoachClaude

Post-game coaching that looks back at a session of play, says what the player did well and
poorly and what to try next, and keeps a record of it. One section of shared terms, then one
per game.

Game sections may add terms but never redefine a shared one. If a game needs a different
meaning, it needs a different word.

## Shared

**Game**:
A title the coach supports: Overwatch 2, Heroes of the Storm.
_Avoid_: title, coach (for the game itself)

**Match**:
One unit of competition within a game, from start to result. Each match is coached on its own
merits, without regard to which session it was in.
_Avoid_: game (for a single match), round

**Session**:
The matches of one game played in one sitting, roughly a day or an evening. The session
summary looks across them; match coaching does not.
_Avoid_: recording, combined session, evening

**Habit**:
A trigger and the action to take on it: "when X happens, do Y."
_Avoid_: tip, goal

**Focus**:
The one habit the player is working on right now. There is at most one focus; there may be none.
_Avoid_: focus item, current habits, goal

**Retired focus**:
A focus the player has moved past. It is no longer graded, but it is remembered so that a
regression can be recognized.

**Pattern**:
A problem that recurs across the matches of a session. The pattern finder looks for patterns
without knowing the focus. A pattern is a no-op if it matches the focus, a regression if it
matches a retired focus, and otherwise a candidate focus proposal.
_Avoid_: trend (that is a statistic), theme

**Focus grade**:
The focus grader's judgement of improvement or regression on the current focus over a session.

**General feedback**:
What the coach says about a match regardless of the focus.

**Focus feedback**:
What the coach says about a match in light of the focus. There is none when there is no focus.

**Focus proposal**:
The single habit the coach thinks would be worth more than the current focus. There is at most
one, and only when the coach sees a real reason for it. It is offered at the next focus check-in.
_Avoid_: focus options, focus menu

**Focus check-in**:
The start of coaching, where the coach names the focus it will grade and, if there is a focus
proposal, offers that one alternative. Keeping the current focus is the default.

**Moment**:
A point in a match worth the player's attention: a teachable moment, a bad death, a particularly
bad decision, or a standout good play. The session summary picks about five per session, each
with its clip; the rest of what happened is not coached.
_Avoid_: highlight, event (for a coached moment)

**Focus test**:
A window in a match where the current focus could be tested, such as a low-HP episode for a
focus about walls. The pipeline lists them from facts; the coach judges each one.

**Stoplight**:
The one-word focus grade a match report gives each focus: green, amber, red, or not tested.
The reasons are in the session summary.

**Match log**:
The objective record of every match: result, map, hero, score, rank movement and any other stat
that can be extracted for free from the recording or replay. It is the primary record and must
be rigorous and queryable. No judgement goes in it.
_Avoid_: game log, history, stats file

**Lessons file**:
The coach's subjective record: the focus, retired focuses, declined proposals and a note per
session. Kept for continuity; it does not need to be queryable.
_Avoid_: notes, coaching log

**Backlog**:
Every match available but not yet coached, possibly spanning several sessions. Asking for
coaching coaches the whole backlog.

## Overwatch

**Packet**:
What the pipeline extracts for one match, in `<match>/packet/`: `packet.json` (facts, timeline,
deaths, ults, HUD reads), the stills, the overview sheets and the per-death facts blocks. The
coach's only input.

**Piece**:
One unit of coaching work on a match with its own process and context: two deaths, five minutes
of overview sheets, the ults, or the writer.

**Brief**:
The prompt a piece's process gets: a template from the skill's `briefs/` folder filled in by the
driver from the packet and the lessons file.

**Reader**:
The process for a deaths, overview or ults piece. It reads its images once and writes reader
notes; it records, it does not coach.

**Reader notes**:
A reader's output, `<match>/packet/notes/<piece>.md`, in the shape its brief fixes. The writer's
only view of the images.

**Writer**:
The process that judges one match from its reader notes and the packet and writes the match's
report and `notes/summary.md`.

**Driver**:
`owcoach coach`: the code that cuts matches into pieces, fills the briefs, runs the processes
and the session summary, and rebuilds the page.
