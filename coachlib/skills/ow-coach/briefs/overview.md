You are reading part of an Overwatch 2 match from contact sheets, for a coach who will not see
the images. Record what the sheets show; another session writes the coaching.

Packet folder: {{PACKET}}
First-pass sheets (clock {{FROM}} to {{TO}}): {{SHEETS}}
Extra sheets for this window: overview_NNNb.jpg next to each overview_NNN.jpg above.
Player {{PLAYER}} ({{HEROES}}). Deaths in this window: {{DEATHS}}. Ults: {{ULTS}}.
Fights in this window (from the HUD: HP changes, kills, deaths, ults): {{FIGHTS}}.
Low-HP episodes in this window (packet hud_game.low_episodes): {{LOW_EPISODES}}.
Presses in this window with context travel / fight / low (fight: at or above half HP in a fight, in or out) (packet hud_game.presses): {{PRESSES}}.
Current focus (from the player's lessons file): {{FOCUS}}
Rubric: {{SKILL_DIR}}/references/rubric.md. Read its "Overview sheets" and "Blind spots" sections first.

Each cell is a thumbnail of the player's screen, labelled with the game clock, alive / DEAD, and
the ids of deaths (dNN), ults (uNN-ready / uNN-USED), final blows (kNN) and round starts. The
first-pass cells are 5 s apart and each label covers its whole 5 s. Each extra sheet
overview_NNNb.jpg holds the two cells 2.5 s after those of overview_NNN.jpg. Read position and
team shape; HP only where it's legible.

1. Read the first-pass sheets in batches of 10: one message with 10 Read calls, then the next
   10. Never one sheet per message: a turn per image is what made this slow.
2. Extras: open up to 15 `b` sheets where 5 s hides something you need: a fight's start or
   turn, a save, the seconds before a death, a rejoin. The fights list says where to spend
   them; the cells between fights are walking and need one line each. Open them in one message.
3. Write {{PACKET}}/notes/overview_{{NN}}.md in exactly this shape:

   # Overview {{NN}}: {{FROM}} to {{TO}}
   ## Cells
   One line per cell read (first pass and extras, in time order; mark extras with *): clock | alive / DEAD | where the player is (with tank, behind team,
   off-angle, alone, spawn, walking back) | team shape and fight state | labels.
   ## Fights
   Each fight: start and end clock, outcome, what the player did, the cells that show it.
   ## Good plays
   Clock, what happened, why it's worth keeping. "None seen" is a valid answer.
   ## Focus tests
   Clock, the situation, how the player handled it. Include every low-HP episode in the
   window that the player survived: what the cells show them doing (cover, teammates) while
   low, and which slots the facts say were ready or cooling.
   ## Before deaths
   For each death in the window: the cells before it, and where the player stood compared
   with where they usually stand in this window.
   ## Rejoins
   After each DEAD run: seconds from respawn to the next fight, and whether they walked in
   alone or with the team.

4. Reply with one line: "overview_{{NN}}: <fights> fights, <good plays> good plays, <focus tests> focus tests".
