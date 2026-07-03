"""Tiling geometry: full coverage, correct overlap, exact detection remap."""

from PIL import Image

from autogeo.ingest.tiling import TileBox, crop_tiles, tile_boxes, tile_positions


def test_positions_cover_and_clamp_end():
    starts = tile_positions(11104, tile=2048, step=1638)
    assert starts[0] == 0
    assert starts[-1] == 11104 - 2048  # last tile flush to the right edge
    # every pixel is covered: consecutive tiles overlap (step < tile)
    for a, b in zip(starts, starts[1:]):
        assert b - a <= 2048


def test_small_image_single_tile():
    assert tile_positions(1000, tile=2048, step=1638) == [0]


def test_boxes_cover_whole_image():
    w, h = 11104, 7520
    boxes = tile_boxes(w, h, tile=2048, overlap=0.2)
    assert boxes[0] == TileBox(0, 0, 2048, 2048)
    # union of boxes covers the full frame
    assert min(b.x0 for b in boxes) == 0 and min(b.y0 for b in boxes) == 0
    assert max(b.x1 for b in boxes) == w and max(b.y1 for b in boxes) == h
    # a coarse coverage check: every 512-grid point lands in some box
    for gx in range(0, w, 512):
        for gy in range(0, h, 512):
            assert any(b.x0 <= gx < b.x1 and b.y0 <= gy < b.y1 for b in boxes)


def test_overlap_reduces_to_grid_when_zero():
    boxes = tile_boxes(4096, 2048, tile=2048, overlap=0.0)
    assert len(boxes) == 2
    assert boxes[0].x1 == 2048 and boxes[1].x0 == 2048


def test_detection_remap_to_full_frame():
    box = TileBox(1638, 3276, 3686, 5324)
    # a label found at tile-local (100, 50) must map to full-frame coords
    assert box.to_full(100, 50) == (1738, 3326)


def test_crop_tiles_offsets_match_boxes():
    img = Image.new("L", (5000, 3000), color=255)
    tiles = list(crop_tiles(img, tile=2048, overlap=0.2))
    for box, crop in tiles:
        assert crop.size == (box.x1 - box.x0, box.y1 - box.y0)
