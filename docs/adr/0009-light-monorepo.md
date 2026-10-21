# A light monorepo for both games

The Overwatch coach (`owcoach`) and the Heroes of the Storm coach live in one repo,
CoachClaude, and share only what both need: `coachlib` holds the config file (one file, a
section per game), the page renderer, the skill installer and the version. Everything else
stays per game. `hotscoach.py` stays a single script at the repo root, and each game gets its
own page, cross-linked in the sidebar. owcoach came in as one squashed commit (2d7d72a; its 55
commits stay in the old repo), and merges into this repo are squashed. The author's words for the
shape: "light monorepo", "separate pages", "always squash".

Why: the author wanted owcoach packaged for others with a shared core and one viewer over both
coaches, without turning the two pipelines into one (731314b).

## Consequences

- `coachlib.site` became data-driven: a collector per game (`owcoach/site.py` for Overwatch)
  hands it days, sessions and matches, and the renderer knows neither game.
- `hotscoach.py` is no longer fully standalone. `version()` imports `coachlib`, which it finds
  by putting the script's own folder on `sys.path`, so `uv run hotscoach.py` works only next to
  a `coachlib` folder (a clone). At the same time the script keeps its own copy of the config
  path, data dir and `dev_mode()` "so the script still runs on its own", duplicating
  `coachlib.config`. That coupling is unresolved: either the script depends on `coachlib` or it
  doesn't.
