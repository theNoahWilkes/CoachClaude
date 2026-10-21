You are reading the ultimates from an Overwatch 2 coaching packet, for a coach who will not see
the images. Record what the stills show; another session writes the coaching.

Packet folder: {{PACKET}}
Player {{PLAYER}} ({{HEROES}}). Ults: {{ULTS}}.
Rubric: {{SKILL_DIR}}/references/rubric.md. Read its "Ults" and "Blind spots" sections first.

1. In {{PACKET}}/packet.json read ults[] in full, and for each ult the timeline, deaths,
   final_blows and alive_series entries in its hold window (ready to used).
2. Read every ult's stills in ONE message (one Read call each, all sent together).
3. Write {{PACKET}}/notes/ults.md in exactly this shape:

   # Ults
   ## uNN <ready clock> to <used clock>: <hero>, <outcome>, held <held_s> s
   | still | dt | what it shows (allies, enemies, effect, notices) |
   - Hold window: the fights in it (from the timeline and alive counts) and whether the ult
     could have changed one.
   - Use: early or late in the fight, combined with team ults if visible, what it achieved.
   (one section per ult)
   ## Ults read
   One line per ult: good / questionable / wasted, and why.

4. Reply with one line: "ults: <n> read, <one-line summary>".
