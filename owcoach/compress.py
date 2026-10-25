"""Compress a match for long-term storage: re-encode its match.mp4 on the GPU, in place.

The default split (`--video header`) is a lossless stream copy, about 3x the size of the
`--video encode` re-encode. A match the player wants to keep but not review again can be
compressed later, from the page or with `owcoach compress SESSION [m01 ...]`.

The input is the match.mp4 the library already has, so the recording doesn't need to exist. A
header-cropped clip decodes to the game area already (the decoder applies the header's crop),
so it is encoded as it comes; a plain copy with bars gets the crop filter, as split would.
Same NVENC settings as split (CQ, preset, 0.5 s GOP, HDR tags), so clip times don't move and
clip_offset stays. The encode goes to match.part.mp4 and replaces match.mp4 only when its
duration matches; match.json's clip_video then records "... cq 23".
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from .config import cache_for, library
from .probe import cuda_decode_ok, nvenc_ok, probe

CROP_RE = re.compile(r"crop (\d+):(\d+):(\d+):(\d+)")
SPEED = 3.5            # x realtime, NVENC p3 on a 3080 Ti (2026-10-25)
TOLERANCE_S = 0.5      # one GOP


def state(gdir: Path) -> str | None:
    """'compressed', 'big' (a stream copy) or None (no clip)."""
    if not (gdir / "match.mp4").exists():
        return None
    tag = _match_json(gdir).get("clip_video") or "copy"
    return "compressed" if " cq " in f" {tag} " else "big"


def _match_json(gdir: Path) -> dict:
    try:
        return json.loads((gdir / "match.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _scan_cfg(gdir: Path) -> dict:
    """The session's scan.json (crop, hwaccel), if the cache still has it."""
    try:
        sj = json.loads((gdir.parent / "session.json").read_text(encoding="utf-8"))
        return json.loads((cache_for(sj["video"]) / "scan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return {}


def match_dir(rel: str) -> Path:
    """A library-relative match folder from the page -> its path, refusing anything outside the library."""
    lib = library().resolve()
    d = (lib / rel).resolve()
    if d.parent.parent != lib or not (d / "match.json").exists():
        raise ValueError(f"no match folder {rel!r} in the library")
    return d


def compress(gdir: Path) -> str:
    """Re-encode one match.mp4 in place. Returns a line for the player."""
    from .split import CQ, video_args          # split needs OpenCV; the page only needs state()
    clip = gdir / "match.mp4"
    name = f"{gdir.parent.name[:10]} {gdir.name}"
    if state(gdir) != "big":
        return f"{name}: nothing to compress"
    if not nvenc_ok():
        raise RuntimeError("compressing needs an NVIDIA GPU (hevc_nvenc)")
    mj = _match_json(gdir)
    tag = mj.get("clip_video") or "copy"
    scan = _scan_cfg(gdir)
    meta = probe(clip)
    m = CROP_RE.search(tag)
    if m and tag.endswith("header"):
        w, h, x, y = map(int, m.groups())
        crop, keep = [w, h, 0, 0], [w, h, x, y]     # decoded frames are the game area already
    elif scan.get("crop"):
        crop = keep = list(scan["crop"])            # a plain copy, bars and all
    else:
        crop, keep = [meta["width"], meta["height"], 0, 0], None
    cfg = {"probe": meta, "crop": crop, "hwaccel": scan.get("hwaccel") or ("cuda" if cuda_decode_ok(clip) else "none")}
    pre, venc = video_args(cfg, "encode")
    tmp = gdir / "match.part.mp4"
    before = clip.stat().st_size
    t0 = time.monotonic()
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *pre, "-i", str(clip), *venc, str(tmp)],
                   check=True)
    got = probe(tmp)["duration"]
    if abs(got - meta["duration"]) > TOLERANCE_S:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"the encode is {got:.1f} s long, the original {meta['duration']:.1f} s; kept the original")
    for attempt in range(120):      # Windows: the browser or an indexer can hold match.mp4 for a moment
        try:
            tmp.replace(clip)
            break
        except PermissionError:
            if attempt == 119:
                raise
            time.sleep(0.5)
    mj["clip_video"] = ("crop {}:{}:{}:{} cq {}".format(*keep, CQ) if keep else f"cq {CQ}")
    (gdir / "match.json").write_text(json.dumps(mj, indent=1))
    after = clip.stat().st_size
    return (f"{name}: compressed {before / 1e9:.1f} GB -> {after / 1e9:.1f} GB "
            f"in {(time.monotonic() - t0) / 60:.0f} min")


def estimate_min(gdir: Path) -> float:
    """Minutes the encode should take, from the clip's length."""
    d = _match_json(gdir).get("clip_duration") or 0
    return d / SPEED / 60
