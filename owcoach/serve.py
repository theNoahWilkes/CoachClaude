"""`owcoach serve`: the coaching page with working buttons (see coachlib.serve).

Each action here calls the same function as its CLI command, so the page and the terminal
can't drift: "focus" is `owcoach focus N` / `owcoach focus --set "..."`, "compress" is
`owcoach compress SESSION m01 ...` (queued: it runs in the background, one match at a time).
"""
from __future__ import annotations

from coachlib import serve as srv

from . import compress, focus
from .config import library
from .site import PAGE_NAME, build


def act_focus(args: dict) -> dict:
    picks = [int(n) for n in args.get("n") or []]
    custom = (args.get("set") or "").strip() or None
    if not picks and not custom:
        raise ValueError("pick an option, or type your own wording")
    msg = focus.apply(picks, custom)
    return {"message": msg.splitlines()[0].replace("focus set (1): ", "Next focus: "), "reload": True}


def compress_action(jobs: srv.Jobs):
    def act(args: dict) -> dict:
        dirs = [compress.match_dir(str(r)) for r in args.get("dirs") or []]
        todo = [d for d in dirs if compress.state(d) == "big"]
        if not todo:
            return {"message": "Nothing to compress there."}
        added = [d for d in todo if jobs.add(str(d.relative_to(library()).as_posix()), f"{d.parent.name[:10]} {d.name[:3]}",
                                               lambda d=d: compress.compress(d))]
        mins = sum(compress.estimate_min(d) for d in added)
        if not added:
            return {"message": "Already queued."}
        return {"message": f"Compressing {len(added)} match{'es' if len(added) != 1 else ''} in the background "
                           f"(about {max(1, round(mins))} min). The page updates when it's done; keep this tab or the "
                           "server open until then."}
    return act


def serve(port: int = srv.PORT, open_browser: bool = True, idle: float = srv.IDLE_S) -> None:
    """The Overwatch page at /, the HotS page (if there is one) at /hots/."""
    import sys
    if sys.stdout is None:          # started by the desktop shortcut (pythonw): no console, so log to a file
        sys.stdout = sys.stderr = open(library() / ".serve.log", "a", encoding="utf-8", buffering=1)
    build()
    jobs = srv.Jobs(on_done=build)
    actions = {"focus": act_focus, "compress": compress_action(jobs)}
    import os
    from pathlib import Path
    from coachlib.config import data_dir
    hots = Path(os.environ.get("HOTSCOACH_DATA") or data_dir("hots"))
    srv.serve(library(), PAGE_NAME, actions, build, jobs=jobs, port=port, open_browser=open_browser, idle=idle,
              mounts={"hots": hots} if (hots / PAGE_NAME).exists() else None)
