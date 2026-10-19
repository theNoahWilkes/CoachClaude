"""Pass 1b: full-resolution crops of a few screen regions, at the thumbnail keyframes.

Some signals (the kill feed's names and hero icons) are too small to read on 1280-wide
thumbnails. Grabbing full-res frames one ffmpeg call at a time costs ~1 s each, so this
pass decodes each chunk once more and writes only the regions, cropped *before* the
tonemap (the expensive step, now run on a few small images instead of a 5K frame).

Same keyframes and chunking as scan.py, and the same file names:
    roi/<region>/<chunk>/<n>.jpg  <->  frames/<chunk>/<n>.jpg
so a thumbnail index entry {"f": "00600/00012.jpg"} finds its crops directly.
Regions are geometry.Region tuples (anchored, in units of the game-area height).
"""
from __future__ import annotations

import json
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .geometry import Region, box
from .scan import TONEMAP

REGIONS: dict[str, Region] = {
    # kill feed: up to ~6 rows under the players-alive counter
    "feed": ("tr", -0.40, 0.065, -0.02, 0.33),
    # ult meter: ring + percentage, bottom centre
    "ult": ("bc", -0.07, -0.205, 0.07, -0.07),
    # players alive: "[blue] 2 vs [red] 4" under the performance overlay
    "alive": ("tr", -0.18, 0.022, -0.02, 0.066),
    # objective HUD: phase label, scores, %, distances, timers, bar, CONTESTED!/OVERTIME under it
    "objective": ("tc", -0.32, 0.0, 0.32, 0.19),
    # the player's HUD strips, the same two crops a detail still carries (hud.py reads them):
    # HP readout + health bar bottom left, ability squares + weapon bottom right
    "hud_hp": ("bl", 0.0, -0.181, 0.542, 0.0),
    "hud_abil": ("br", -0.547, -0.181, 0.0, 0.0),
}


def _chunk(cfg: dict, cache: Path, tag: str, start: float, dur: float, regions: dict[str, Region]) -> int:
    meta = cfg["probe"]
    gw, gh = (cfg["crop"][0], cfg["crop"][1]) if cfg["crop"] else (meta["width"], meta["height"])
    cuda = cfg.get("hwaccel") == "cuda"
    head = [f"hwdownload,format={'p010le' if meta.get('pix_fmt', '').endswith('10le') else 'nv12'}"] if cuda else []
    if cfg["crop"]:
        head.append("crop={}:{}:{}:{}".format(*cfg["crop"]))
    names = list(regions)
    graph = [f"[0:v]{','.join(head) or 'null'},split={len(names)}"
             + "".join(f"[s{i}]" for i in range(len(names)))]
    outs = []
    for i, n in enumerate(names):
        x0, y0, x1, y1 = box((gh, gw), regions[n])
        x0, y0 = max(0, x0) & ~1, max(0, y0) & ~1
        w, h = (min(gw, x1) - x0) & ~1, (min(gh, y1) - y0) & ~1
        chain = [f"crop={w}:{h}:{x0}:{y0}"] + ([TONEMAP] if meta.get("hdr") else [])
        graph.append(f"[s{i}]{','.join(chain)}[o{i}]")
        d = cache / "roi" / n / tag
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.jpg"):
            old.unlink()
        outs += ["-map", f"[o{i}]", "-fps_mode", "passthrough", "-q:v", "3", str(d / "%05d.jpg")]
    pre = ["-hide_banner", "-nostdin", "-loglevel", "error"]
    if cuda:
        pre += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    if cfg["mode"] != "keyframes":
        raise ValueError("roiscan follows keyframe scans only")
    cmd = ["ffmpeg", *pre, "-skip_frame", "nokey", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-copyts",
           "-i", cfg["video"], "-an", "-sn", "-dn", "-filter_complex", ";".join(graph), *outs, "-y"]
    subprocess.run(cmd, check=True)
    want = len(json.loads((cache / "frames" / f"{tag}.json").read_text()))
    for n in names:
        got = len(list((cache / "roi" / n / tag).glob("*.jpg")))
        if got != want:
            raise RuntimeError(f"roi {n} chunk {tag}: {got} crops vs {want} thumbnails")
    (cache / "roi" / f"{tag}.done").write_text(json.dumps(names))
    return want


def roiscan(cache: Path, regions: dict[str, Region] | None = None, jobs: int = 4, quiet: bool = False) -> None:
    """Crop `regions` (default REGIONS) for every scanned chunk; finished chunks are skipped
    unless the region set changed."""
    regions = regions or REGIONS
    cfg = json.loads((cache / "scan.json").read_text())
    chunk = None
    tags = sorted(p.stem for p in (cache / "frames").glob("*.json"))
    starts = [int(t) for t in tags]
    if len(starts) > 1:
        chunk = starts[1] - starts[0]
    dur = cfg["probe"]["duration"]

    def todo(tag):
        p = cache / "roi" / f"{tag}.done"
        return not p.exists() or json.loads(p.read_text()) != list(regions)

    def job(tag):
        s = int(tag)
        n = _chunk(cfg, cache, tag, s, min(chunk or dur, dur - s), regions)
        if not quiet:
            print(f"  roi chunk {tag}: {n} frames", flush=True)

    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(job, [t for t in tags if todo(t)]))
