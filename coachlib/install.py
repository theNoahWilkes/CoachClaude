"""`install-skill`: put the ow-coach and hots-coach skills where Claude Code finds them.

The skills ship inside the package (coachlib/skills/). From a git checkout they are linked into
~/.claude/skills (a junction on Windows), so editing the repo edits the live skill. From a release
install they are copied, so the skill a player runs is the one the installed version shipped, and a
coaching session can't edit it. `--link` / `--copy` force one or the other.

A copied skill folder carries a `.coachclaude` marker with the version that wrote it, so a later
install knows it may replace the folder. A folder without the marker is somebody's own work and
is left alone.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .version import is_checkout, version

SKILLS = ("ow-coach", "hots-coach")
MARKER = ".coachclaude"


def skills_root() -> Path:
    return Path(__file__).resolve().parent / "skills"


def skill_dir(name: str) -> Path:
    """The packaged skill, else the copy under ~/.claude/skills (the templates are read from here)."""
    here = skills_root() / name
    return here if here.is_dir() else Path.home() / ".claude" / "skills" / name


def home_skills() -> Path:
    return Path.home() / ".claude" / "skills"


def _is_link(p: Path) -> bool:
    if p.is_symlink():
        return True
    try:
        return p.is_junction()                      # Python 3.12+
    except AttributeError:
        import stat
        try:
            return bool(os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except (OSError, AttributeError):
            return False


def _remove_link(p: Path) -> None:
    os.rmdir(p) if sys.platform == "win32" else p.unlink()


def _link(src: Path, dst: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], check=True, capture_output=True)
    else:
        dst.symlink_to(src, target_is_directory=True)


def install_skills(mode: str = "auto", names=SKILLS) -> list[str]:
    """mode: auto (link from a checkout, copy otherwise) | link | copy. Returns one line per skill."""
    link = mode == "link" or (mode == "auto" and is_checkout())
    home = home_skills()
    home.mkdir(parents=True, exist_ok=True)
    out = []
    for name in names:
        src = skills_root() / name
        dst = home / name
        if not src.is_dir():
            continue
        if _is_link(dst):
            if link and dst.resolve() == src.resolve():
                out.append(f"already linked: {dst}")
                continue
            _remove_link(dst)
        elif dst.exists():
            if not (dst / MARKER).exists():
                out.append(f"{dst} is a folder this installer didn't write: move it away and rerun")
                continue
            shutil.rmtree(dst)
        if link:
            _link(src, dst)
            out.append(f"linked {dst} -> {src}")
        else:
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (dst / MARKER).write_text(version() + "\n", encoding="utf-8")
            out.append(f"copied {name} {version()} -> {dst}")
    return out
