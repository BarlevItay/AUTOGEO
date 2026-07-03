"""Corpus census, metadata level (spike 1, non-vision half).

Inventories every document in LA/: raster dimensions/DPI/compression for TIFFs,
page count + per-page vector/raster/text profile for PDFs. Output: CSV + JSON
under data/census/. The vision half (sheet type, era, street names) appends to
the same inventory once ANTHROPIC_API_KEY is available.

Run: .venv/Scripts/python.exe scripts/corpus_census.py
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import fitz  # pymupdf
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # vault scans are huge; we trust our own corpus

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "LA"
OUT_DIR = REPO / "data" / "census"


def census_tiff(path: Path) -> dict:
    with Image.open(path) as img:
        raw_dpi = img.info.get("dpi")
        dpi = (float(raw_dpi[0]), float(raw_dpi[1])) if raw_dpi else None
        frames = getattr(img, "n_frames", 1)
        return {
            "doc_id": path.stem,
            "path": str(path.relative_to(REPO)),
            "kind": "tiff",
            "pages": frames,
            "width_px": img.width,
            "height_px": img.height,
            "dpi": round(dpi[0]) if dpi else None,
            "mode": img.mode,  # '1' = bilevel scan, 'L' = grayscale, 'RGB'
            "compression": img.info.get("compression"),
            "sheet_in_wide": round(img.width / dpi[0], 1) if dpi and dpi[0] else None,
        }


def census_pdf(path: Path) -> list[dict]:
    rows = []
    with fitz.open(path) as doc:
        for page_no, page in enumerate(doc):
            text = page.get_text("text")
            drawings = page.get_drawings()
            images = page.get_images(full=True)
            # crude class per page: real text + paths = vector; big images = scanned
            has_text = len(text.strip()) > 50
            n_paths = len(drawings)
            page_class = (
                "vector" if (has_text or n_paths > 100) and len(images) <= 2
                else "scanned" if images
                else "vector"
            )
            rows.append({
                "doc_id": f"{path.stem}_p{page_no}",
                "path": str(path.relative_to(REPO)),
                "kind": "pdf_page",
                "pages": doc.page_count,
                "page_number": page_no,
                "width_px": round(page.rect.width * 300 / 72),  # canonical frame size
                "height_px": round(page.rect.height * 300 / 72),
                "page_class": page_class,
                "n_text_chars": len(text.strip()),
                "n_paths": n_paths,
                "n_images": len(images),
                "is_ocr_needed": not has_text,
            })
    return rows


def main() -> None:
    rows: list[dict] = []
    for tif in sorted((CORPUS / "TIFF").glob("*.tif*")):
        rows.append(census_tiff(tif))
    for pdf in sorted((CORPUS / "PDF").glob("*.pdf")):
        rows.extend(census_pdf(pdf))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    fields: list[str] = sorted({k for r in rows for k in r})
    with open(OUT_DIR / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (OUT_DIR / "inventory.json").write_text(
        json.dumps({"censused": stamp, "rows": rows}, indent=1), encoding="utf-8"
    )

    tiffs = [r for r in rows if r["kind"] == "tiff"]
    pdf_pages = [r for r in rows if r["kind"] == "pdf_page"]
    # contiguous document-number runs approximate distinct projects
    ids = sorted(int(t["doc_id"].removeprefix("la").lstrip("0") or 0) for t in tiffs)
    runs = 1 + sum(1 for a, b in zip(ids, ids[1:]) if b - a > 1)
    print(f"TIFF sheets: {len(tiffs)} in ~{runs} contiguous runs (projects)")
    print(f"  modes: { {t['mode'] for t in tiffs} }, dpi: { {t['dpi'] for t in tiffs} }")
    print(f"PDF docs: {len(set(r['path'] for r in pdf_pages))}, pages: {len(pdf_pages)}")
    print(f"  vector pages: {sum(1 for r in pdf_pages if r['page_class'] == 'vector')}, "
          f"scanned pages: {sum(1 for r in pdf_pages if r['page_class'] == 'scanned')}, "
          f"pages needing OCR: {sum(1 for r in pdf_pages if r['is_ocr_needed'])}")
    print(f"wrote {OUT_DIR / 'inventory.csv'} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
