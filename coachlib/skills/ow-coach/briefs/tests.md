You are reading the focus tests of one Overwatch 2 match from contact sheets, for a coach who
will not see the images. Record what the sheets show; another session writes the coaching.

Packet folder: {{PACKET}}
Player {{PLAYER}} ({{HEROES}}). Current focus (from the player's lessons file): {{FOCUS}}
Rubric: {{SKILL_DIR}}/references/rubric.md. Read its "Overview sheets" and "Blind spots" sections first.

The focus tests are the windows where the focus could be tested, found from the HUD and the
alive counter (packet focus_tests). They are given:
{{TESTS}}

Moments the triage asked about in this match, with no death to anchor them:
{{MOMENTS}}

Sheets to read (first pass, the cells covering the windows above): {{SHEETS}}
Extra sheets: overview_NNNb.jpg next to each overview_NNN.jpg holds the cells 2.5 s later.

Each cell is a thumbnail of the player's screen, labelled with the game clock, alive / DEAD, and
the ids of deaths (dNN), ults (uNN-ready / uNN-USED), final blows (kNN) and round starts. The
first-pass cells are 5 s apart. Read position and team shape: where the player stands, what
cover is beside them, who is near. HP only where it's legible; the facts already have it.

1. Read the sheets in batches of 10: one message with 10 Read calls, then the next 10. Never one
   sheet per message: a turn per image is what made this slow.
2. Extras: open up to 10 `b` sheets where 5 s hides the answer to a test (the second the player
   broke line of sight, the step out of cover). Open them in one message.
3. Write {{PACKET}}/notes/tests_{{NN}}.md in exactly this shape:

   # Focus tests {{NN}}: {{WINDOWS}}
   ## Tests
   One line per test above: <fNN> <clock> | held / broke / unclear | what the cells show, in plain
   words: where the player stood, the cover beside them, who was near, which way they went
   (e.g. "behind the arch wall, healing the Rein, stayed until the escape was back"). Mark
   extras you used with *. "unclear" when the cells can't settle it; say why.
   ## Moments
   For each moment above: <clock> | what the cells show and whether it is what the triage
   thought. "None asked." when there were none.
   ## Tests read
   One line: <n> held, <n> broke, <n> unclear.

4. Reply with one line: "tests_{{NN}}: <n> held, <n> broke, <n> unclear".
