"""The version the coaches report: in `--version`, the page footer, analysis.json and packet.json.

A release install (pip from a tag) reports the package version, e.g. "0.2.0". A checkout
reports pyproject's version plus the commit, e.g. "0.2.0+dev.6fdcc4a" ("+dev.6fdcc4a.dirty" with
uncommitted changes), so a report from a working tree says which build made it.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

PACKAGE = "coachclaude"


def repo_dir() -> Path | None:
    """The checkout this code runs from, or None for an installed copy."""
    root = Path(__file__).resolve().parent.parent
    return root if (root / ".git").exists() and (root / "pyproject.toml").is_file() else None


def is_checkout() -> bool:
    return repo_dir() is not None


def _pyproject_version(root: Path) -> str | None:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def version() -> str:
    root = repo_dir()
    if root:
        v = _pyproject_version(root) or "0.0.0"
        sha = _git(root, "rev-parse", "--short", "HEAD")
        if not sha:
            return v + "+dev"
        dirty = ".dirty" if _git(root, "status", "--porcelain", "--untracked-files=no") else ""
        return f"{v}+dev.{sha}{dirty}"
    try:
        from importlib.metadata import version as _v
        return _v(PACKAGE)
    except Exception:
        return "0.0.0+unknown"
