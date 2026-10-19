from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

TOOLS = ("ffmpeg", "ffprobe", "tesseract")


def _registry_path() -> list[str]:
    """Machine + user PATH as currently saved (Windows), for shells started before an install."""
    try:
        import winreg
    except ImportError:
        return []
    dirs = []
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                dirs += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(";")
        except OSError:
            pass
    return [d for d in dirs if d]


def ensure_tools() -> None:
    """Put ffmpeg/ffprobe/tesseract on PATH if they're installed but not visible. Fails loudly if absent."""
    missing = [t for t in TOOLS if not shutil.which(t)]
    if missing:
        from .config import tesseract_dir
        extra = [str(tesseract_dir())] if tesseract_dir() else []
        os.environ["PATH"] = os.pathsep.join([os.environ["PATH"], *extra, *_registry_path(),
                                              str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR")])
    if missing := [t for t in TOOLS if not shutil.which(t)]:
        raise SystemExit(f"not found: {', '.join(missing)} (winget install Gyan.FFmpeg / UB-Mannheim.TesseractOCR)")


def cuda_decode_ok(video: Path) -> bool:
    """True if NVDEC can decode this file (one keyframe, discarded)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-skip_frame", "nokey",
                        "-i", str(video), "-frames:v", "1", "-f", "null", "-"], capture_output=True)
    return r.returncode == 0


def probe(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries",
         "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,bit_rate,pix_fmt,color_transfer,color_primaries:format=duration,size",
         "-of", "json", str(video)],
        check=True, capture_output=True, text=True).stdout
    j = json.loads(out)
    s, f = j["streams"][0], j["format"]

    def rate(r: str) -> float:
        n, d = r.split("/")
        return float(n) / float(d) if float(d) else 0.0

    return {
        "codec": s.get("codec_name"),
        "width": int(s["width"]),
        "height": int(s["height"]),
        "avg_fps": round(rate(s["avg_frame_rate"]), 3),
        "r_fps": round(rate(s["r_frame_rate"]), 3),
        "pix_fmt": s.get("pix_fmt"),
        "hdr": s.get("color_transfer") in ("smpte2084", "arib-std-b67"),
        "color_transfer": s.get("color_transfer"),
        "vfr": abs(rate(s["avg_frame_rate"]) - rate(s["r_frame_rate"])) > 0.5,
        "duration": float(f.get("duration", 0)),
        "size": int(f.get("size", 0)),
    }


def keyframe_times(video: Path, limit_s: float = 120.0) -> list[float]:
    """Keyframe timestamps in the first `limit_s` seconds, from packet flags (no decode)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-read_intervals", f"%+{limit_s}",
         "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", str(video)],
        check=True, capture_output=True, text=True).stdout
    ts = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and "K" in parts[1] and parts[0] not in ("", "N/A"):
            ts.append(float(parts[0]))
    return sorted(ts)


def detect_crop(video: Path, at: float | None = None, thresh: int = 8) -> tuple[int, int, int, int]:
    """Find the active game area inside letter/pillarboxing (e.g. 21:9 game in a 32:9 capture).

    Reads one keyframe as 16-bit gray and returns (w, h, x, y) for ffmpeg's crop filter.
    Bars are the frame's darkest level: ~0 if ffmpeg treats the source as full range, ~16
    if video range (ffmpeg builds differ). Anything `thresh` (16-bit scale /256) above that counts.
    """
    import numpy as np
    meta = probe(video)
    W, H = meta["width"], meta["height"]
    cands: list[tuple[int, int, int, int]] = []
    spots = [at] if at is not None else [meta["duration"] * f for f in (0.25, 0.5, 0.75)]
    for t in spots:
        raw = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-skip_frame", "nokey",
             "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-an",
             "-f", "rawvideo", "-pix_fmt", "gray16le", "-"],
            check=True, capture_output=True).stdout
        a = np.frombuffer(raw, np.uint16).reshape(H, W) >> 8
        floor = int(a.min())
        cols = np.where(a.max(0) > floor + thresh)[0]
        rows = np.where(a.max(1) > floor + thresh)[0]
        if len(cols) == 0 or len(rows) == 0:
            continue
        x0, x1, y0, y1 = cols.min(), cols.max(), rows.min(), rows.max()
        cands.append((int(x1 - x0 + 1) // 2 * 2, int(y1 - y0 + 1) // 2 * 2, int(x0), int(y0)))
    # largest active area seen wins (a dark scene can under-detect)
    return max(cands, key=lambda c: c[0] * c[1]) if cands else (W, H, 0, 0)
