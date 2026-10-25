# Packaged skills and fixed data locations

The coaching skills ship inside the package as package data, under `coachlib/skills/`
(`ow-coach`, `hots-coach`), not in `.claude/skills/` (moved in 4b8ccd2). `install-skill` links
them into `~/.claude/skills` from a git checkout, so editing the repo edits the live skill, and
copies them from a release install, so a player runs the skill text of the version they
installed and a coaching session can't edit it. A copied folder carries a `.coachclaude`
marker holding the version that wrote it; a folder without the marker is someone else's and
is left alone (`coachlib/install.py`).

Both coaches read one config file, `~/.config/coachclaude/config.json`, with a section per game
and a top-level `dev` key. Data goes under `~/.local/share/coachclaude/<game>/` unless the
config says otherwise; the one exception by default is the Overwatch library of sessions and
clips, `~/Videos/owcoach`. Nothing is written next to the recordings or replays, which are
read-only input.

## Consequences

- Developer mode (`dev`, off by default and on no release) is what lets a skill edit the
  pipeline when a rule misses; with it off the skill records the miss under "Pipeline issues"
  instead. Today only the skill text enforces that; see
  [0005](0005-dev-mode-enforced-in-code.md).
- The one file written outside those folders is `CoachClaude.html` on the desktop
  (`coachlib/launcher.py`), a link to each game's page. `setup` creates it and a page rebuild
  only rewrites it if it is still there, so deleting it is how a player opts out.
