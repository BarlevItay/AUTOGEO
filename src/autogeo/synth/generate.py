"""Render a SynthFeatureSet into a plan-like document under a known transform.

Design notes that keep the ground truth honest:
- Rotation/skew is BAKED INTO the affine transform (drawn already-rotated), so
  affine cases have an exact closed-form truth.
- Noise/blur/bilevel threshold are image-space and never move points — they
  model the real corpus (every in-hand TIFF is bilevel 300 DPI).
- Optional low-frequency warp displaces the image AND the truth GCPs together,
  so GCPs stay exact even for non-affine (TPS-escalation) cases.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from autogeo.synth.model import (
    AffineTruth,
    RenderStyle,
    SynthFeatureSet,
    SynthTruth,
    TruthGCP,
)

_FONT_CANDIDATES = ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf"]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def build_affine(
    envelope_world: tuple[float, float, float, float],
    page_size_px: tuple[int, int],
    rotation_deg: float = 0.0,
    fill: float = 0.82,
) -> AffineTruth:
    """Similarity world->pixel: uniform scale, rotation, world-y-up -> pixel-y-down,
    centered so the envelope fills the page with a margin."""
    xmin, ymin, xmax, ymax = envelope_world
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    pw, ph = page_size_px
    theta = math.radians(rotation_deg)
    ct, st = math.cos(theta), math.sin(theta)
    # rotated extent of the envelope, to fit after rotation
    ew, eh = (xmax - xmin), (ymax - ymin)
    rot_w = abs(ew * ct) + abs(eh * st)
    rot_h = abs(ew * st) + abs(eh * ct)
    s = fill * min(pw / rot_w, ph / rot_h)  # pixels per world unit
    # A = s * F @ R, F = diag(1, -1) for y-flip
    a, b = s * ct, -s * st
    d, e = -s * st, -s * ct
    # translate so world center -> page center
    tx = pw / 2 - (a * cx + b * cy)
    ty = ph / 2 - (d * cx + e * cy)
    return AffineTruth(a=a, b=b, d=d, e=e, tx=tx, ty=ty)


def _apply_warp(
    img: Image.Image, gcps: list[TruthGCP], amp_px: float, periods: float, rng: np.random.Generator
) -> tuple[Image.Image, list[TruthGCP]]:
    """Low-frequency sinusoidal displacement (models paper/scan warp). Moves the
    image and the GCP pixel coords together so GCPs remain ground truth."""
    w, h = img.size
    phase_x = rng.uniform(0, 2 * math.pi)
    phase_y = rng.uniform(0, 2 * math.pi)
    k = 2 * math.pi * periods

    def disp(px: float, py: float) -> tuple[float, float]:
        dx = amp_px * math.sin(k * py / h + phase_x)
        dy = amp_px * math.sin(k * px / w + phase_y)
        return dx, dy

    src = np.asarray(img, dtype=np.float32)
    ys, xs = np.mgrid[0:h, 0:w]
    dxg = amp_px * np.sin(k * ys / h + phase_x)
    dyg = amp_px * np.sin(k * xs / w + phase_y)
    # sample source at (x - dx, y - dy) via nearest neighbor (bilevel-safe)
    sx = np.clip((xs - dxg).round().astype(int), 0, w - 1)
    sy = np.clip((ys - dyg).round().astype(int), 0, h - 1)
    warped = Image.fromarray(src[sy, sx].astype(np.uint8))
    moved = []
    for g in gcps:
        dx, dy = disp(g.pixel_x, g.pixel_y)
        moved.append(g.model_copy(update={"pixel_x": g.pixel_x + dx, "pixel_y": g.pixel_y + dy}))
    return warped, moved


def render(
    fs: SynthFeatureSet,
    truth_affine: AffineTruth,
    *,
    case_id: str,
    style: RenderStyle,
    page_size_px: tuple[int, int] = (5100, 3300),  # ~17x11in at 300dpi
    dpi: int = 300,
    era_year: int = 1990,
    seed: int = 0,
    warp_amp_px: float = 0.0,
    warp_periods: float = 1.5,
    rotation_deg: float = 0.0,
    noise: float = 0.0,
    blur: float = 0.0,
) -> tuple[Image.Image, SynthTruth]:
    """Render `fs` and return (image, truth). Image is RGB for clean, mode '1'
    (bilevel) for scan_degraded to match the real corpus."""
    rng = np.random.default_rng(seed)
    pw, ph = page_size_px
    img = Image.new("L", (pw, ph), color=255)
    draw = ImageDraw.Draw(img)
    T = truth_affine

    label_font = _font(28)
    small_font = _font(22)
    gcps: list[TruthGCP] = []

    # centerlines first (so labels/symbols sit on top)
    for feat in fs.features:
        if feat.kind in ("centerline", "parcel"):
            pts = [T.world_to_pixel(x, y) for x, y in feat.world_coords]
            draw.line(pts, fill=0, width=3, joint="curve")

    for feat in fs.features:
        if feat.kind == "centerline" and feat.label and len(feat.world_coords) >= 2:
            # place the street name near the midpoint of the longest span
            mid = len(feat.world_coords) // 2
            (x0, y0), (x1, y1) = feat.world_coords[mid - 1], feat.world_coords[mid]
            px, py = T.world_to_pixel((x0 + x1) / 2, (y0 + y1) / 2)
            draw.text((px + 6, py + 6), feat.label.upper(), fill=0, font=small_font)
        elif feat.kind in ("intersection", "monument"):
            wx, wy = feat.world_coords[0]
            px, py = T.world_to_pixel(wx, wy)
            if feat.kind == "monument":
                r = 10
                draw.line([(px - r, py - r), (px + r, py + r)], fill=0, width=2)
                draw.line([(px - r, py + r), (px + r, py - r)], fill=0, width=2)
            else:
                draw.ellipse([px - 5, py - 5, px + 5, py + 5], outline=0, width=2)
            if feat.label:
                draw.text((px + 8, py - 26), feat.label.upper(), fill=0, font=small_font)
            gcps.append(TruthGCP(pixel_x=px, pixel_y=py, world_x=wx, world_y=wy,
                                 label=feat.label, kind=feat.kind))

    scale_ratio = dpi / math.hypot(T.a, T.d)  # ground ftUS per paper inch
    _draw_title_block(draw, page_size_px, fs.world_crs, era_year, scale_ratio,
                      label_font, small_font)

    degradation: dict = {}
    if style == "scan_degraded":
        if blur:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur))
            degradation["blur"] = blur
        if noise:
            arr = np.asarray(img, dtype=np.float32)
            arr += rng.normal(0, noise * 255, arr.shape)
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
            degradation["noise"] = noise
        if warp_amp_px:
            img, gcps = _apply_warp(img, gcps, warp_amp_px, warp_periods, rng)
            degradation["warp_amp_px"] = warp_amp_px
            degradation["warp_periods"] = warp_periods
        img = img.convert("1")  # bilevel, like every real corpus scan
        degradation["bilevel"] = True
        degradation["rotation_deg"] = rotation_deg

    truth = SynthTruth(
        case_id=case_id, style=style, world_crs=fs.world_crs,
        page_size_px=page_size_px, dpi=dpi, era_year=era_year,
        scale_ratio=scale_ratio, transform=T, envelope_world=fs.envelope_world,
        gcps=gcps, degradation=degradation,
    )
    return img, truth


def _draw_title_block(draw, page_size_px, world_crs, era_year, scale_ratio,
                      font, small_font) -> None:
    pw, ph = page_size_px
    bw, bh = 900, 260
    x0, y0 = pw - bw - 40, ph - bh - 40
    draw.rectangle([x0, y0, x0 + bw, y0 + bh], outline=0, width=3)
    inch_ft = scale_ratio / 12.0  # e.g. 40 for 1"=40'
    lines = [
        "CITY OF LOS ANGELES",
        "BUREAU OF ENGINEERING",
        f'SCALE: 1" = {inch_ft:.0f}\'',
        f"CALIFORNIA COORDINATE SYSTEM ZONE V",
        f"DATE: {era_year}",
    ]
    for i, line in enumerate(lines):
        draw.text((x0 + 20, y0 + 20 + i * 44), line, fill=0, font=font)
    # north arrow
    ax, ay = x0 - 120, y0 + 60
    draw.line([(ax, ay + 60), (ax, ay - 60)], fill=0, width=3)
    draw.polygon([(ax, ay - 70), (ax - 12, ay - 40), (ax + 12, ay - 40)], fill=0)
    draw.text((ax - 8, ay - 105), "N", fill=0, font=font)


def save_case(img: Image.Image, truth: SynthTruth, out_dir: Path) -> Path:
    """Write <case_id>.tif + truth.json under out_dir/<case_id>/."""
    case_dir = out_dir / truth.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    ext = "tif"
    img.save(case_dir / f"{truth.case_id}.{ext}", dpi=(truth.dpi, truth.dpi))
    (case_dir / "truth.json").write_text(truth.model_dump_json(indent=1), encoding="utf-8")
    return case_dir
