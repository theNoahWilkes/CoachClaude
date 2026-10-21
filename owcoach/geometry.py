"""Screen regions anchored to the game area, in units of its height.

Overwatch scales its HUD with the render height and pins each element to a corner or an
edge (on ultrawide the HUD spreads to the edges rather than staying in a 16:9 box). So a
region is (anchor, x0, y0, x1, y1) where the offsets are measured from the anchor point
in multiples of the game-area height: +x is right, +y is down.

    anchor  point
    tl/tr   top-left / top-right corner
    bl/br   bottom-left / bottom-right corner
    tc/bc   middle of the top / bottom edge
    c       centre

The same region then works on any thumbnail or full-res frame of any aspect ratio.
New regions (stage 4 on) are written this way; older ones still use 21:9 thumbnail px
and are to be converted once a non-21:9 recording is available to test against.
"""
from __future__ import annotations

import numpy as np

Region = tuple[str, float, float, float, float]

_ANCHOR = {"tl": (0, 0), "tr": (1, 0), "bl": (0, 1), "br": (1, 1),
           "tc": (0.5, 0), "bc": (0.5, 1), "c": (0.5, 0.5)}


def box(shape: tuple[int, ...], r: Region, dx: float = 0.0) -> tuple[int, int, int, int]:
    """Region -> pixel (x0, y0, x1, y1) for an image of this shape. dx shifts right, in px of
    this image (the HUD text block slides with the portrait frame)."""
    H, W = shape[:2]
    a, x0, y0, x1, y1 = r
    ax, ay = _ANCHOR[a]
    px, py = ax * W, ay * H
    return (int(round(px + x0 * H + dx)), int(round(py + y0 * H)),
            int(round(px + x1 * H + dx)), int(round(py + y1 * H)))


def crop(img: np.ndarray, r: Region, dx: float = 0.0) -> np.ndarray:
    x0, y0, x1, y1 = box(img.shape, r, dx)
    H, W = img.shape[:2]
    return img[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]


def fractions(r: Region, aspect: float) -> tuple[float, float, float, float]:
    """Region -> game-area fractions (for scan.grab_frame's roi), given width / height."""
    a, x0, y0, x1, y1 = r
    ax, ay = _ANCHOR[a]
    return (ax + x0 / aspect, ay + y0, ax + x1 / aspect, ay + y1)
