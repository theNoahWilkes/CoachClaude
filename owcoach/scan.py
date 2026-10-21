"""Pass 1: decode a session recording once, cheaply, into a thumbnail cache.

Everything downstream (state detection, splitting, later death/ult detection)
reads this cache instead of re-decoding a 30+ GB file.

Sampling:
  keyframes  - `-skip_frame nokey`: the decoder only touches I-frames, so cost
               scales with keyframe count, not frame count. ShadowPlay emits a
               keyframe every 0.5 s, so this is a free 2 fps sample.
  fps=N      - decode everything, keep N frames/sec. Slower, uniform spacing.

The scan is chunked and resumable: each chunk of `chunk` seconds is written to
its own folder with a sidecar JSON, and finished chunks are skipped on rerun.
`--budget` stops before starting a chunk that won't finish in time, so it can
run inside a shell with a hard timeout and just be called again.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
from pathlib import Path

from .probe import cuda_decode_ok, detect_crop, probe

SHOWINFO_RE = re.compile(r"\bn:\s*(\d+).*?\bpts_time:\s*(-?[0-9.]+)")

TONEMAP = ("zscale=tin=smpte2084:min=bt2020nc:pin=bt2020:rin=full:t=linear:npl=200,"
           "format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def _setup(video: Path, cache: Path, mode: str, width: int, crop, hwaccel: str) -> dict:
    cfg_path = cache / "scan.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text())
    meta = probe(video)
    if crop == "auto":
        crop = detect_crop(video)
        if tuple(crop) == (meta["width"], meta["height"], 0, 0):
            crop = None
    if hwaccel == "auto":
        hwaccel = "cuda" if cuda_decode_ok(video) else "none"
    cfg = {"video": str(video), "mode": mode, "width": width,
           "crop": list(crop) if crop else None, "hwaccel": hwaccel, "probe": meta}
    cache.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=1))
    return cfg


def _scan_chunk(cfg: dict, cache: Path, start: float, dur: float, quiet: bool) -> int:
    video, meta = Path(cfg["video"]), cfg["probe"]
    tag = f"{int(start):05d}"
    out = cache / "frames" / tag
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()

    # NVDEC decodes; frames come back to system memory and the cheap per-thumbnail work
    # (crop/scale/tonemap) stays on the CPU. Output is bit-identical to CPU decode.
    cuda = cfg.get("hwaccel") == "cuda"
    vf = [f"hwdownload,format={'p010le' if meta.get('pix_fmt', '').endswith('10le') else 'nv12'}"] if cuda else []
    if cfg["mode"].startswith("fps="):
        vf.append(f"fps={cfg['mode'].split('=', 1)[1]}")
    if cfg["crop"]:
        vf.append("crop={}:{}:{}:{}".format(*cfg["crop"]))
    vf.append(f"scale={cfg['width']}:-2:flags=area")
    if meta.get("hdr"):
        vf.append(TONEMAP)
    vf.append("showinfo")

    pre = ["-hide_banner", "-nostdin"]
    if cuda:
        pre += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    if cfg["mode"] == "keyframes":
        pre += ["-skip_frame", "nokey"]
    cmd = ["ffmpeg", *pre, "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-copyts",
           "-i", str(video), "-an", "-sn", "-dn", "-vf", ",".join(vf),
           "-fps_mode", "passthrough", "-q:v", "4", str(out / "%05d.jpg"), "-y"]

    times: list[float] = []
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, errors="replace")
    assert proc.stderr is not None
    for line in proc.stderr:
        if "Parsed_showinfo" in line and (m := SHOWINFO_RE.search(line)):
            times.append(float(m.group(2)))
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {' '.join(cmd)}")
    files = sorted(out.glob("*.jpg"))
    if len(files) != len(times):
        raise RuntimeError(f"chunk {tag}: {len(files)} files vs {len(times)} timestamps")
    entries = [{"f": f"{tag}/{p.name}", "t": round(t, 3)} for p, t in zip(files, times)]
    (cache / "frames" / f"{tag}.json").write_text(json.dumps(entries))
    if not quiet:
        print(f"  chunk {tag}: {len(entries)} frames", flush=True)
    return len(entries)


def scan(video: Path, cache: Path, mode: str = "keyframes", width: int = 1280,
         crop="auto", chunk: float = 600.0, budget: float | None = None,
         jobs: int = 2, quiet: bool = False, hwaccel: str = "auto") -> dict | None:
    """Scan (or resume scanning) `video`. Returns the index when complete, else None.

    HEVC keyframe-only decode is close to single-threaded, so `jobs` chunks run
    side by side (one ffmpeg each) to use the other cores.
    """
    from concurrent.futures import ThreadPoolExecutor

    cfg = _setup(video, cache, mode, width, crop, hwaccel)
    dur = cfg["probe"]["duration"]
    starts = [i * chunk for i in range(math.ceil(dur / chunk))]
    done = lambda s: (cache / "frames" / f"{int(s):05d}.json").exists()  # noqa: E731
    t0, per_round = time.time(), None
    while pending := [s for s in starts if not done(s)]:
        if budget is not None and per_round is not None and \
                time.time() - t0 + per_round * 1.1 > budget:
            print(f"budget reached: {len(starts) - len(pending)}/{len(starts)} chunks done; "
                  "rerun to continue")
            return None
        batch = pending[:jobs]
        r0 = time.time()
        with ThreadPoolExecutor(len(batch)) as ex:
            list(ex.map(lambda s: _scan_chunk(cfg, cache, s, min(chunk, dur - s), quiet), batch))
        per_round = max(per_round or 0, time.time() - r0)
    return build_index(cache)


def build_index(cache: Path) -> dict:
    cfg = json.loads((cache / "scan.json").read_text())
    frames: list[dict] = []
    for side in sorted((cache / "frames").glob("*.json")):
        for e in json.loads(side.read_text()):
            # chunks are cut at keyframes, so a boundary frame can appear twice
            if frames and e["t"] <= frames[-1]["t"] + 1e-3:
                continue
            frames.append(e)
    index = {**cfg, "frames": frames}
    (cache / "index.json").write_text(json.dumps(index))
    return index


def grab_frame(cache: Path, t: float, dst: Path, roi: tuple[float, float, float, float] | None = None,
               width: int | None = None) -> Path:
    """Pull one full-resolution frame (game area, tonemapped) straight from the source video.

    roi = (x0, y0, x1, y1) as fractions of the game area. Input-side -ss seeks to the
    nearest keyframe (every 0.5 s here), so this costs about a second.
    """
    cfg = json.loads((cache / "scan.json").read_text())
    vf = []
    if cfg["crop"]:
        vf.append("crop={}:{}:{}:{}".format(*cfg["crop"]))
    if roi:
        x0, y0, x1, y1 = roi
        vf.append(f"crop=iw*{x1 - x0:.4f}:ih*{y1 - y0:.4f}:iw*{x0:.4f}:ih*{y0:.4f}")
    if width:
        vf.append(f"scale={width}:-2:flags=area")
    if cfg["probe"].get("hdr"):
        vf.append(TONEMAP)
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                    *(["-hwaccel", "cuda"] if cfg.get("hwaccel") == "cuda" else []),
                    "-ss", f"{t:.3f}", "-i", cfg["video"], "-frames:v", "1", "-an",
                    "-vf", ",".join(vf), "-q:v", "2", str(dst)], check=True)
    return dst


def load_index(cache: Path) -> dict:
    return json.loads((cache / "index.json").read_text())


def frame_path(cache: Path, entry: dict) -> Path:
    return cache / "frames" / entry["f"]
