# Golden-Set Labeling Protocol (Phase 0.5)

Hand-georeferenced sheets are the project's ground truth — every phase validates
against them. Target: **≥ 12 labeled LA sheets (goal 20), ≥ 6 distinct projects,
both artifact classes, ≥ 3 pre-1980 scans, ≥ 1 NAD27-era document.**

## One-time QGIS setup

1. QGIS ≥ 3.28. Set project CRS to **EPSG:2229** (NAD83 / California zone 5, ftUS).
2. Add reference control (Layer → Add Layer → Add ArcGIS REST Server Layer,
   URL `https://maps.lacity.org/lahub/rest/services`):
   - `Survey_Information` → **Survey Control Points** (layer 0) and **Benchmarks** (layer 6)
   - `Street_Information` → **Streets Centerline** (36) and **Intersections** (9)
3. Optional visual aid: Esri World Imagery XYZ tile layer. **Never snap to imagery** —
   snap only to the vector control above.

## Per document

1. Copy the source file to `data/labeled/<doc_id>/` (doc_id = filename stem, e.g. `la000112283`).
2. Raster → Georeferencer. Load the TIFF (for PDFs: render the plan-view page to
   TIFF at 300 DPI first — ask the tool or use any PDF rasterizer; note the page).
3. Place **≥ 6 GCPs, well spread** (all four quadrants of the drawing area if possible;
   avoid clustering on one street). Snap to:
   - labeled street **intersections** (highest preference — matches the tool's Tier 1),
   - survey **control points / benchmarks** identifiable from the drawing's stationing or notes,
   - only as a last resort, parcel/ROW corners — and **never for pre-1990 documents**.
4. Era rule: every GCP must be a feature that **existed at the document's date**
   (a 1965 plan may not use a 1998 cul-de-sac).
5. Transformation: **Polynomial 1 (affine)**, resampling nearest, target CRS EPSG:2229.
6. Save from the Georeferencer:
   - GCP file → `data/labeled/<doc_id>/<doc_id>.points`
   - georeferenced output → `data/labeled/<doc_id>/<doc_id>_georef.tif`
   - note the reported RMSE.
7. Write `data/labeled/<doc_id>/label.json`:

```json
{
  "doc_id": "la000112283",
  "source_path": "LA/TIFF/la000112283.tif",
  "page_number": 0,
  "doc_class": "scanned",
  "sheet_type": "plan_and_profile",
  "era_year": 1964,
  "era_evidence": "title block date 3-12-64",
  "stated_crs_text": "exact title-block wording about datum/zone, or null",
  "jurisdiction": "los_angeles_city",
  "qgis_rmse_reported": 0.8,
  "gcp_notes": "pts 1-4 intersections, 5-6 BOE control pts 08-12345/08-12388",
  "labeler": "IBL",
  "labeled_date": "2026-07-XX",
  "notes": ""
}
```

## Quality gates

- **Reproducibility check (once):** relabel one document on a different day without
  looking at the first attempt; the two georeferenced results must agree within
  **0.3 m RMSE** over shared check locations. If not, tighten this protocol.
- Sheets that are covers, general notes, or schematic traffic-control layouts are
  **not labelable** — record them in the census as `not_georeferenceable` instead
  of forcing points; they become negative test cases.
- If the drawing's datum is stated (NAD27 wording, "CCS Zone VII", etc.), copy the
  exact wording into `stated_crs_text` — these become datum-handling test cases.
