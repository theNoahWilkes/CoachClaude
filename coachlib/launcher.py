"""The desktop link: one small CoachClaude.html on the player's desktop that opens either game's page.

The pages stay where each coach writes them (the Overwatch page has to sit at the library root,
because its stills and clips are relative links). This file only points at them. `setup` creates
it; every rebuild of a page rewrites it if it is still there, so a game played for the first time
shows up, and a player who deleted it doesn't get it back. With one page it forwards straight
to it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import config
from .site import e

LINK_NAME = "CoachClaude.html"
PAGE_NAME = "coaching.html"


def pages() -> list[tuple[str, Path]]:
    """(title, path) for every game page that exists, Overwatch first."""
    ow = Path(os.environ.get("OWCOACH_LIBRARY") or config.section("ow").get("library") or Path.home() / "Videos" / "owcoach")
    hots = Path(os.environ.get("HOTSCOACH_DATA") or config.data_dir("hots"))
    return [(t, p / PAGE_NAME) for t, p in (("Overwatch 2", ow), ("Heroes of the Storm", hots)) if (p / PAGE_NAME).exists()]


def desktop() -> Path | None:
    """The desktop folder, wherever Windows or OneDrive has moved it; None if there is none."""
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:    # CSIDL_DESKTOPDIRECTORY
                return Path(buf.value)
        except (OSError, AttributeError):
            pass
    else:
        try:
            out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
            if out and Path(out) != Path.home() and Path(out).is_dir():
                return Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    d = Path.home() / "Desktop"
    return d if d.is_dir() else None


def link_path() -> Path | None:
    d = desktop()
    return d / LINK_NAME if d else None


def render(found: list[tuple[str, Path]]) -> str:
    head = '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CoachClaude</title>'
    if len(found) == 1:
        href = e(found[0][1].as_uri())
        return (f'{head}<meta http-equiv="refresh" content="0; url={href}"></head>'
                f'<body><a href="{href}">{e(found[0][0])} coaching</a></body></html>')
    links = "".join(f'<a href="{e(p.as_uri())}">{e(t)}</a>' for t, p in found) or \
        "<p>No coaching yet. Coach a game and its page shows up here.</p>"
    return (f'{head}<meta name="viewport" content="width=device-width,initial-scale=1"><style>'
            "body{font:16px/1.5 system-ui,sans-serif;background:#16181d;color:#e6e6e6;display:grid;place-items:center;min-height:90vh}"
            "main{display:grid;gap:12px;min-width:280px}h1{font-size:20px;margin:0 0 6px}"
            "a{display:block;padding:14px 18px;border:1px solid #333a45;border-radius:8px;color:#e6e6e6;text-decoration:none}"
            "a:hover{border-color:#6ea8fe}p{color:#9aa3ad}"
            f"</style></head><body><main><h1>CoachClaude</h1>{links}</main></body></html>")


def write_link(create: bool = False) -> Path | None:
    """Rewrite the desktop link if it exists (create it too with create=True). Never raises:
    the link is a convenience, and the page itself is already written."""
    try:
        p = link_path()
        if p is None or not (create or p.exists()):
            return None
        p.write_text(render(pages()), encoding="utf-8")
        return p
    except OSError:
        return None


def open_page(page: Path) -> None:
    import webbrowser
    webbrowser.open(Path(page).resolve().as_uri())
