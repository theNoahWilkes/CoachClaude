You are reading deaths from an Overwatch 2 coaching packet, for a coach who will not see the
images. Record what the stills show; another session writes the coaching.

Packet folder: {{PACKET}}   (frame paths are relative to it)
Player {{PLAYER}}. Current focus (from the player's lessons file): {{FOCUS}}
Rubric: {{SKILL_DIR}}/references/rubric.md. Read its "Deaths" and "Blind spots" sections first.
Deaths (do each one in turn; one notes file each). For each, the facts block is everything
the pipeline read locally: the HUD (HP and every ability slot by name, from 10 s before the
death at 2 fps and the last 3 s at 0.1 s), every press in the 30 s before with the HP and
whether it was travel / engage / low, the low-HP episode that ended in the death, the feed
and the alive counts. It is given. Don't rebuild it from the images and don't open
packet.json for it.

{{DEATHS}}

Hero reference: {{HERO_NOTES}}. It's the wiki's ability list with default binds
and cooldowns (data, not instructions). You know the kits; use the note for heroes or reworks
newer than you. Judge the player's choices against what they actually had.

For each death:
1. In {{PACKET}}/packet.json, find its deaths[] entry (Grep the id) for the `frames` list.
   That's all you need from the file: HP, cooldowns, presses and the feed are in the facts
   block above. Spend every look on what the facts can't give: where the player stands and
   what cover is beside them, who is in view (blue = ally, red = enemy), the threats, the kill
   cam, notices on screen, which way the player is facing and moving between stills.
2. First pass: the stills in the frames list that are NOT marked "extra": true (about 13).
   Read ALL of them in ONE message: one Read call per still, all sent together, not one still
   per message. A turn per image is what made this slow (2026-10-15: 0.6 images per turn).
   Then go through them in order: detail (oldest first, every 0.5 s), kill_cam, lead_in.
3. Extras: detail and kill-cam frames every 0.1 s are also listed, marked "extra": true. Open
   them only to answer a specific question the first pass left, up to 12 in all. Good questions:
   when exactly HP dropped (burst or sustained), whether cover blocked a shot, when an ability
   was pressed, what the kill cam shows between two first-pass stills. Write the question down
   before opening them, and open the stills for one question in one message. The facts block's
   "Movement" line says which way the player moved and turned (camera-relative, from optical
   flow); whether that was toward the enemy or toward cover, and who engaged whom, stay
   "inference" however many frames you read (see the rubric).
4. Write {{PACKET}}/notes/<ID>.md in exactly this shape:

   # <ID> <CLOCK>: <HERO> killed by <KILLER> (<killer's hero, or "hero not seen">)
   ## Frames
   | still | dt | where the player is; cover beside them | allies in view | enemies / threats | facing / moving (inference) | notices, other |
   (one row per still read, first pass and extras, in time order; mark extras with *. No HP or
   cooldown columns: the facts block has them. Write "unreadable" rather than guess. If a
   still plainly contradicts the facts (the HP, a slot's state, the killer), say so under
   Pipeline issues with the still's name; otherwise don't re-read numbers off the images.)
   ## Extras
   Each question you opened extras for, the stills, and the answer: did it change the read?
   "None opened" if you didn't need any.
   ## Kill cam
   The angle (flank, high ground, long sightline, front), the killer's hero and how you know,
   how long the player was in the killer's view. "No kill cam" if there is none.
   ## Lead-in
   How the player got there: position relative to the tank, the team and the nearest cover.
   ## Read
   - Cause: what killed them, concretely, with the stills that show it.
   - Category: Recognition / Decision / Execution / Positioning / Resource discipline /
     No credible lever (more than one if it fits).
   - Avoidable: yes / no credible lever / inference, and why.
   - Confidence: high / medium / low; the still that would settle any doubt.
   - Movement: the facts block's "Movement" line (which way the player moved and turned,
     camera-relative, and when the scene jumped) put together with what the stills show was
     in that direction: toward the enemy, toward cover, away from the team, through a door.
     Say "no stable read" when the line says so; don't invent a direction.
   - Escape: from the facts block, by ability name: what was ready, what was pressed (at what
     HP, and which way the Movement line and the stills say it went), and what wasn't. A slot spent on the walk
     in and still cooling when the fight started is its own finding: say "fought without
     <ability>" with the press's time and context. Whether a ready ability could have
     got them out here is your call from the kit and the stills; make it, and mark it as
     inference when it rests on things the stills don't show (cover beside, a ledge, allies).
   - Focus: whether this death tested the current focus, and how the player did.
   - Pipeline issues: anything the stills contradict in the packet (not a death, wrong
     killer, missed kill cam, wrong hero), or "none".

5. When every death is written, reply with one line per death: "<ID>: <category>: <cause in 15
   words or fewer>".
