"""Contact sheets: grids of cached thumbnails with timestamps burned in.

Used for eyeballing a session (and for calibrating detectors) without
opening the video.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .scan import frame_path, load_index


def fmt_t(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def contact_sheets(cache: Path, out_dir: Path, every: int = 10, cols: int = 8,
                   rows: int = 8, tile_w: int = 240, start: float = 0,
                   end: float | None = None, labels: dict[str, str] | None = None) -> list[Path]:
    idx = load_index(cache)
    frames = [f for f in idx["frames"]
              if f["t"] >= start and (end is None or f["t"] <= end)][::every]
    out_dir.mkdir(parents=True, exist_ok=True)
    per = cols * rows
    paths = []
    for s in range(0, len(frames), per):
        chunk = frames[s:s + per]
        tiles = []
        for f in chunk:
            img = cv2.imread(str(frame_path(cache, f)))
            h = int(img.shape[0] * tile_w / img.shape[1])
            img = cv2.resize(img, (tile_w, h), interpolation=cv2.INTER_AREA)
            txt = fmt_t(f["t"])
            if labels and f["f"] in labels:
                txt += " " + labels[f["f"]]
            cv2.rectangle(img, (0, 0), (tile_w, 16), (0, 0, 0), -1)
            cv2.putText(img, txt, (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(img)
        th, tw = tiles[0].shape[:2]
        while len(tiles) % cols:
            tiles.append(np.zeros((th, tw, 3), np.uint8))
        grid = np.vstack([np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)])
        p = out_dir / f"sheet_{s // per:03d}.jpg"
        cv2.imwrite(str(p), grid, [cv2.IMWRITE_JPEG_QUALITY, 85])
        paths.append(p)
    return paths
