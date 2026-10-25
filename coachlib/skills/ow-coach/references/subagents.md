# Pieces and briefs

No single context reads a match's images. The driver (`owcoach coach`) cuts the match into
pieces, fills a brief per piece from `packet.json` and the lessons file, and runs one `claude -p`
process per piece with a fresh context (ADR 0011). Each still and each overview sheet is read
exactly once, by the reader whose piece it is in, which writes what it saw to `packet/notes/`.
One writer per match then judges from the notes.

**Why:** one session that reads a whole game's images (150+ for a 20-min game) outgrows its
context. Claude Code clears old tool results, the coach forgets stills and re-reads them, and
each clear breaks the prompt cache. A 21-min game cost ~$70 API-equivalent and never finished
(A/B experiment, 2026-10-15). Per-piece contexts stay at 20-100k and read each image once. The
per-match main context that used to launch the pieces as subagents was then a quarter of every
match's cost on its own, re-reading 100k+ of context 20 times to paste facts blocks into briefs
(issue #20); the driver fills the briefs now, as code.

## Pieces

| Piece | One process per | Notes file | Images |
|---|---|---|---|
| Triage | session, before any reader (ADR 0012) | `<session>/triage.md` (from `<session>/digest.md`) | none |
| Deaths | two consecutive shortlisted deaths (every death in the full read) | `notes/dNN.md`, one per death | each death's first-pass `frames`, plus up to 12 extras per death on demand |
| Focus tests | 30 first-pass sheets covering the focus tests and the clock-only moments | `notes/tests_NN.md` | those sheets, plus up to 10 extra (`b`) sheets on demand |
| Overview (full read only) | 5 min of game clock: 30 first-pass sheets (2 cells, 5 s apart) | `notes/overview_NN.md` (NN = chunk number, from 01) | those sheets, plus up to 15 extra (`b`) sheets on demand |
| Ults | the shortlisted ults (every ult in the full read; skip if none) | `notes/ults.md` | those ults' `frames` |
| Writer | game, once all its readers are done | `packet/coaching.md` and `notes/summary.md` | none, or up to 6 stills to settle a conflict |

## Briefs

The brief templates live in `../briefs/`: `triage.md`, `deaths.md`, `tests.md`, `overview.md`, `ults.md`, `writer.md`.
Their `{{FIELD}}` markers are filled by `owcoach/briefs.py`: the packet folder, the player,
the current focus (the bold wording under "## Current focus" in the lessons file), the skill
folder, each death's `facts` block pasted verbatim under `### dNN at CLOCK on HERO`, the hero
reference notes, an overview window's sheets, deaths, ults, fights, low-HP episodes and presses,
the ults list, and for the writer the game, lessons, session and constraints. The wording is
skill text: edit the templates to change what a reader records or how the writer judges. Don't
shorten the notes shapes; they are what the writer relies on.

## How the driver runs them

- Readers run through a pool (`--parallel`, default 12), overview pieces first because they take
  longest, every match's pieces together. Readers get Read, Glob, Grep and Write; the writer
  also Edit; nobody gets the Agent tool, so nothing fans out further.
- Model and effort: readers and writer at effort **low**, all Opus by default (`--effort`,
  `--writer-effort`, `--reader-model`). Low-effort readers scored the same as default on the
  labelled deaths for about 25 % less cost; the low-effort writer gave the same verdicts with a
  third of the wall clock (A/Bs, 2026-10-16). A cheaper reader model did not help a subscriber:
  Sonnet 5.5 tied Opus on quality but used the same share of the plan window (issue #20).
- A match's writer launches as soon as its readers are done and `notes/all.md` is written.
- **Resume:** a reader piece is done when each of its notes files ends with its last section
  (`## Shortlist`, `## Read`, `## Tests read`, `## Rejoins` or `## Ults read`); the writer is done when `coaching.md` and
  `notes/summary.md` are newer than every notes file. Done pieces are not relaunched, so a run
  cut off by a usage limit picks up where it stopped. A piece that exits without finishing is
  relaunched once.
- A process replies with one line; the notes are in the file.
