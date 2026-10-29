# Labelled focus tests and good plays: ground truth from Noah

Focus-test grades and good plays the coach got wrong, in the player's words, with what the
pipeline now does about each. `tests/test_moments.py` holds each case's packet slice, so a
change to `owcoach/moments.py` that would grade it wrong again fails there.

Clocks are the game clock the reports use. The match video runs a few seconds ahead of it
(`video_t - t`, 3 s on this match), so a clock read off the player's video is that much later.

### 2026.10.27 - 22.31.54.02 / m02 Runasapi f01 1:04-1:14, down two (Moira)
- Coach (2026-10-27): 🔴 broke. "Team down two. 1:05 by the payload ... 1:10 in the street ...
  1:15 beside the bus at full HP. She stayed in the fight." The reader saw the 5 s cells only.
- Facts: 3v5 from 1:04; Fade pressed at 1:12 at 217 HP (then labelled "engage"); 5v5 again at
  1:14. The 1:12 extra cell shows the Fade down the street, the 1:18 cell shows the player
  indoors next to the Sombra at 5v5.
- Noah: I did leave the fight at 1:17 (video) using my Fade. Fair to say I didn't immediately
  exit, but I wasn't in danger and I did disengage. "Down two" is a diagnosis on a death:
  getting myself killed and staggered is the learning opportunity. If I lived, what's left is
  whether I left too late, and that nuance is out of scope.
- Now: a down-two window is graded from the facts, held when the player lived through it and
  broken when it ended in their death; no image is read for it. The press context is "fight",
  not "engage".

### 2026.10.27 - 22.31.54.02 / m02 Runasapi 1:30-1:44, good play (Moira)
- Coach (2026-10-27): not mentioned. The triage gave the match's one good-play pick to 8:28.
- Facts: 4v5 going in; k01 1:38 and k02 1:40, both the player's final blows; 5v3 at 1:40; the
  player lived.
- Noah: the next engagement I poked safely and killed two of their team, turning the 5v5 into a
  5v3 in our favour.
- Now: the digest lists it under "Swings" as a good-play lead for the triage.
