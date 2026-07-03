"""Sliding-window tiling for OCR of large-format sheets.

E-size as-builts are ~11000x7500 px at 300 DPI. Downscaling a whole sheet to a
vision model's effective input (~1568 px long edge) shrinks 1/10" annotation
text below the legibility floor. Instead we crop overlapping tiles at native
resolution, each sized so it needs little or no downscaling, and remap every
detection back into the ONE canonical pixel frame. Overlap ensures labels that
straddle a tile boundary appear whole in at least one tile.

Pure geometry (`tile_positions`, `tile_boxes`) is separated from PIL cropping so
the layout is unit-testable without images.
"""

from __future__ import annotations

from dataclasses import dataclass


def tile_positions(length: int, tile: int, step: int) -> list[int]:
    """Start offsets along one axis so tiles of `tile` px, stepping by `step`,
    fully cover [0, length]. The final tile is clamped flush to the end so the
    trailing strip is never dropped (its overlap with the previous tile grows)."""
    if length <= tile:
        return [0]
    starts = list(range(0, length - tile + 1, step))
    if not starts or starts[-1] != length - tile:
        starts.append(length - tile)
    return starts


@dataclass(frozen=True)
class TileBox:
    """A tile's box in full-frame pixel coords (x0,y0 inclusive, x1,y1 exclusive)."""

    x0: int
    y0: int
    x1: int
    y1: int

    def to_full(self, tx: float, ty: float) -> tuple[float, float]:
        """Map a tile-local pixel coordinate back to the canonical full frame."""
        return (self.x0 + tx, self.y0 + ty)


def tile_boxes(width: int, height: int, tile: int = 2048, overlap: float = 0.2) -> list[TileBox]:
    """Overlapping tile layout covering a (width x height) image.

    `tile` is the native-pixel tile size (chosen so downscaling to the model cap
    stays above the text-legibility floor); `overlap` is the fraction shared
    between adjacent tiles (0.2 = 20%)."""
    if not (0.0 <= overlap < 1.0):
        raise ValueError("overlap must be in [0, 1)")
    step = max(1, round(tile * (1.0 - overlap)))
    xs = tile_positions(width, tile, step)
    ys = tile_positions(height, tile, step)
    boxes = []
    for y0 in ys:
        for x0 in xs:
            boxes.append(TileBox(x0, y0, min(x0 + tile, width), min(y0 + tile, height)))
    return boxes


def crop_tiles(image, tile: int = 2048, overlap: float = 0.2):
    """Yield (TileBox, PIL.Image) crops. `image` is a PIL Image."""
    for box in tile_boxes(image.width, image.height, tile, overlap):
        yield box, image.crop((box.x0, box.y0, box.x1, box.y1))
