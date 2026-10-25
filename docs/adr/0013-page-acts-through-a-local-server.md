---
status: accepted
---

# The page acts through a small local server

The page showed the player what to do next and then sent them to a terminal: the focus proposal
said "run `owcoach focus N`", and keeping a match small for storage meant `split --video
encode` by hand. A page opened as a file can't run a command or write a file, so the buttons
need something on the player's machine to answer them.

- **`owcoach serve`** serves the page folder on `http://127.0.0.1:8765/` and answers the page's
  buttons (`coachlib/serve.py`, standard library only). Each button calls the same function as
  the CLI command it replaces, so the page and the terminal can't drift.
- **The desktop shortcut starts it.** On Windows `setup` makes a CoachClaude shortcut that runs
  the server with no console window and opens the page; the server stops itself after 30
  minutes with no page open and nothing queued. A second start opens the running one.
- **Local only.** It binds 127.0.0.1, answers only Host `127.0.0.1` / `localhost` (no DNS
  rebinding), and every action needs a token the server writes into the page it serves (no
  cross-site posts). This keeps [0002](0002-scope.md): nothing leaves the machine, and the page
  is still the only GUI.
- **The file page keeps working.** Opened as a file, the same buttons copy their command to
  the clipboard.
- **Slow actions queue.** A compress is a GPU re-encode of minutes, so it joins one background
  queue; the page shows it and can cancel what hasn't started.

Today's actions are Overwatch's: pick the focus from the focus proposal, and compress a match
(or a whole day) for storage. The HotS page is served too (at `/hots/`) but has no buttons yet;
it has no focus proposal or clips to act on, a gap from [0001](0001-experience-contract.md)
until the focus loop of [0003](0003-focus-loop.md) lands there.

## Considered Options

- **Copy-command buttons only.** Rejected as the main path: the player still ends up in a
  terminal. Kept as the fallback for the file page.
- **The player runs `owcoach serve` by hand.** Rejected: one more thing to remember, when the
  desktop shortcut can do it.
- **The page writes a queue file that the next `owcoach run` picks up.** Rejected: a browser
  can't write files from a file page without a download prompt, and the result comes a run
  later.
