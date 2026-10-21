# Working on CoachClaude

CoachClaude coaches a player after they play. It looks back at a **session** of **matches**,
says what went well, what went poorly and what to try next, and keeps a record. There is one
coach per **game** (Overwatch 2 in `owcoach/`, Heroes of the Storm in `hotscoach.py`), and they
share `coachlib/` for config, install and the page renderer. The skills (the coaches
themselves) live in `coachlib/skills/`. This file is for people and agents changing the code;
the README is for players.

## Vocabulary

[GLOSSARY.md](GLOSSARY.md) defines the domain terms: session, match, focus, pattern, match log,
lessons file and the rest. Use them exactly, in code, docs and skill text. Game sections of the
glossary may add terms but never redefine a shared one. When a new concept needs a name, add it
there in the same change.

## Decisions

[docs/adr/](docs/adr/) records the decisions that are hard to reverse or easy to undo by
accident. Read the relevant ADR before changing anything it covers. A change that contradicts
one starts with a new ADR that supersedes it. The ones most often relevant:

- **The experience is the contract** ([0001](docs/adr/0001-experience-contract.md)). The
  coach's voice, the focus loop, the landing page and the user-facing commands are the same in
  every game. Rubrics and pipelines specialize freely. Prefer the lighter option for the player.
- **Scope** ([0002](docs/adr/0002-scope.md)). Local only, finished recordings and replays only,
  and the page is the only GUI.
- **The focus loop** ([0003](docs/adr/0003-focus-loop.md)).
- **Facts vs judgement** ([0004](docs/adr/0004-facts-vs-judgement.md)). The CLI extracts facts
  deterministically and at no cost. The coach only judges. Each record has one owner.
- **Dev mode is enforced in code** ([0005](docs/adr/0005-dev-mode-enforced-in-code.md)).

Overwatch pipeline internals, stage by stage, are in [docs/ow/pipeline.md](docs/ow/pipeline.md).

## Where the code still lags the docs

These were decided on 2026-10-21 and are not built yet. Code that disagrees with an ADR here is
known debt, not precedent. Strike each item when it lands.

- [ ] Both coaches follow the focus loop in ADR 0003: check-in, single proposal, pattern finder
      separate from the focus grader, decline timeouts, retired focus. Today Overwatch uses a
      proposal menu (`owcoach focus N`) and HotS edits its own focus.
- [ ] Coaching runs enforce dev mode (ADR 0005).
- [ ] A session is one sitting in Overwatch too: retire one-recording sessions and "combined"
      summaries.
- [ ] "match" replaces "game" for a single match in CLIs, flags (`--games`), the page and HotS
      folder names.
- [ ] User-facing verbs match across `owcoach` and `hotscoach`; Overwatch diagnostics move
      under a developer group.
- [ ] The lessons-file section is "Session log" in both games (the Overwatch template says
      "Sessions"), and `.gitignore` covers both lessons file names.
- [ ] Leftovers: the half-edited sentence in `coachlib/skills/ow-coach/SKILL.md` (~line 101),
      the stale `scripts/coach_session.sh` reference in that skill, `requires-python` differs
      between `hotscoach.py` (3.9) and `pyproject.toml` (3.10), and `hotscoach.py` duplicates
      coachlib's config and dev-mode helpers.
