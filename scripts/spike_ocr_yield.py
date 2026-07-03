"""Spike R2: does vision-OCR read enough street/monument labels off the old
bilevel scans to seed Tier-1 matching — and does tiling beat full-page?

For each doc: (a) naive single full-page vision call, (b) full sliding-window
tiled sweep. Aggregate labels, then match street names against the live LA
centerline layer. Reports per-doc yield + match rate + token cost.

Run: .venv/Scripts/python.exe scripts/spike_ocr_yield.py [doc_id ...]
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field

from autogeo.config.loader import load_settings
from autogeo.config.schema import LlmConfig
from autogeo.gis.cache import make_cached_session
from autogeo.gis.rest_client import ArcGisClient
from autogeo.ingest.tiling import crop_tiles
from autogeo.ocr.llm_client import LlmClient

Image.MAX_IMAGE_PIXELS = None
REPO = Path(__file__).resolve().parents[1]

LA_CENTERLINES = "https://maps.lacity.org/lahub/rest/services/Street_Information/MapServer"
CENTERLINE_LAYER = 36
SUFFIX = re.compile(r"\b(ST|STREET|AVE|AVENUE|BLVD|BOULEVARD|DR|DRIVE|RD|ROAD|PL|PLACE|"
                    r"WAY|LN|LANE|CT|COURT|PKWY|HWY|TER|TERRACE)\b\.?", re.I)


class SheetLabels(BaseModel):
    """What the vision model reads off one image (tile or full page)."""

    street_names: list[str] = Field(default_factory=list)
    monument_or_benchmark_ids: list[str] = Field(default_factory=list)
    other_survey_labels: list[str] = Field(default_factory=list)
    title_block_present: bool = False
    title_block_text: str | None = None


PROMPT = (
    "This is a region of a scanned municipal as-built engineering drawing. "
    "Read all legible text. Return: street names (with suffix, e.g. 'MAIN ST'); "
    "any survey monument or benchmark identifiers (e.g. 'BM 08-1234', station numbers); "
    "other survey labels (bearings, tract/lot numbers); and if a title block is present, "
    "its full text verbatim (agency, scale, datum, date, coordinate system). "
    "Only report text you can actually read; do not invent."
)


def norm_street(name: str) -> str:
    return SUFFIX.sub("", name).strip().upper()


def read_image(client: LlmClient, img: Image.Image) -> SheetLabels:
    try:
        return client.parse_image(img, SheetLabels, PROMPT, max_tokens=1500)
    except Exception as exc:  # one bad tile must not kill the sweep
        print(f"    tile error: {exc}")
        return SheetLabels()


def sweep_tiled(client: LlmClient, img: Image.Image) -> SheetLabels:
    tiles = [crop for _, crop in crop_tiles(img, tile=2048, overlap=0.2)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda c: read_image(client, c), tiles))
    merged = SheetLabels(title_block_present=any(r.title_block_present for r in results))
    for r in results:
        merged.street_names += r.street_names
        merged.monument_or_benchmark_ids += r.monument_or_benchmark_ids
        merged.other_survey_labels += r.other_survey_labels
        if r.title_block_present and r.title_block_text and not merged.title_block_text:
            merged.title_block_text = r.title_block_text
    return merged, len(tiles)


def match_streets(gis: ArcGisClient, names: set[str]) -> dict[str, int]:
    hits = {}
    for base in sorted(names):
        if not base:
            continue
        safe = base.replace("'", "''")
        try:
            n = gis.query_layer(LA_CENTERLINES, CENTERLINE_LAYER,
                                where=f"UPPER(STNAME) LIKE '{safe}%'",
                                out_sr="EPSG:2229", count_only=True)
        except Exception:
            n = 0
        hits[base] = n
    return hits


def main() -> None:
    tiffs = sorted((REPO / "LA" / "TIFF").glob("*.tif*"))
    ids = sys.argv[1:] or [tiffs[0].stem, tiffs[len(tiffs) // 2].stem]
    settings = load_settings()
    client = LlmClient(LlmConfig(enabled=True, model=settings.llm.model, max_image_px=2048))
    if not client.available:
        print("LLM unavailable — set a valid sk-ant- key in .env"); return
    gis = ArcGisClient(settings.arcgis, session=make_cached_session(settings.cache))

    for doc_id in ids:
        path = next((t for t in tiffs if t.stem == doc_id), None)
        if not path:
            print(f"{doc_id}: not found"); continue
        img = Image.open(path).convert("L")
        print(f"\n=== {doc_id}  {img.size} ===")

        full = read_image(client, img)
        full_streets = {norm_street(s) for s in full.street_names}

        tiled, n_tiles = sweep_tiled(client, img)
        tiled_streets = {norm_street(s) for s in tiled.street_names}

        hits = match_streets(gis, tiled_streets)
        matched = {k for k, v in hits.items() if v > 0}

        print(f"  full-page: {len(full_streets)} street names, "
              f"{len(full.monument_or_benchmark_ids)} monument ids, "
              f"title_block={full.title_block_present}")
        print(f"  tiled ({n_tiles} tiles): {len(tiled_streets)} street names, "
              f"{len(tiled.monument_or_benchmark_ids)} monument ids, "
              f"title_block={tiled.title_block_present}")
        print(f"  street names matched to live LA centerlines: "
              f"{len(matched)}/{len(tiled_streets)}  -> {sorted(matched)[:12]}")
        if tiled.title_block_text:
            print(f"  title block: {tiled.title_block_text[:200].replace(chr(10),' | ')}")

    print(f"\nLLM totals: {client.calls} calls, "
          f"{client.input_tokens} in / {client.output_tokens} out tokens")


if __name__ == "__main__":
    main()
