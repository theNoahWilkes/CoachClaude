---
status: accepted
---

# AGPL-3.0-or-later

Someone outside the project asked about CoachClaude, and the repo had no license, which means
nobody else could legally use, change or share it. The player wants it to stay open and free
for anyone who wants to use it, including in versions other people change.

- **The code is `AGPL-3.0-or-later`** ([LICENSE](../../LICENSE), SPDX id in `pyproject.toml`).
  Anyone may use, change and share it; whoever shares a changed version, or runs one for other
  people over a network, must offer its source under the same license.
- **"or later"** lets the project move to a future version of the license without asking every
  contributor.
- **Third-party material keeps its own terms.** Hero notes are Overwatch Wiki text under
  CC BY-SA 3.0, and the HUD templates are crops of Blizzard's game art. The README lists both.
  Neither is relicensed, and neither is code the AGPL covers.

## Considered Options

- **GPL-3.0-or-later.** The same copyleft for copies that are handed out, but none for a
  changed version that someone only runs as a service. Rejected: the coach already has a local
  web server ([0013](0013-page-acts-through-a-local-server.md)), and a hosted coaching service
  built on it would be the likeliest way for a closed fork to appear.
- **A permissive license (MIT, Apache-2.0).** Rejected: it lets a fork close the source,
  which is what the player wants to prevent.
- **MPL-2.0 / LGPL.** Rejected: weaker, per-file or library copyleft, aimed at code meant to be
  linked into other programs. CoachClaude is an application.

Third-party dependencies (markdown-it-py, NumPy, OpenCV, mpyq, six, heroprotocol) are under
MIT, BSD or Apache-2.0 licenses, which can all be combined with AGPLv3.
