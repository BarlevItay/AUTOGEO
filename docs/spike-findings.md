# Week-1 Spike Findings

Empirical results that parameterize the pipeline. Reproduce with the scripts in `scripts/`.

## Corpus census (spike 1) — `scripts/corpus_census.py` → `data/census/inventory.csv`

- **33 TIFFs**, all **bilevel (mode `1`), 300 DPI**, in **~3 contiguous document-number runs** (≈3 projects; one is a 24-sheet set → mosaic-consistency asset).
- **9 PDFs = 59 pages**: 14 vector pages, 45 scanned pages, **27 pages need OCR** (no extractable text layer — includes the two text-as-curves vector plans).
- Implication: the scanned path is the majority of real pages; OCR-of-rendered-raster is mandatory, not optional. Vision census (sheet type / era / street names) is the follow-up half, gated on running the Claude-vision pass.

## Control reliability (spike 5 / R6) — `scripts/spike_reliability.py`

Confirms the adversarial review's accuracy-inversion warning with real numbers. Both tier-1 national sources are **poison unfiltered**:

**BLM CA PLSS corners** (`BLM_CA_CADNSDI/FeatureServer/0`, rural Kern sample n=200). Fields: `RELYTXT`, `RELYNUMB` (reliability, **in feet**), `ERRORX/Y`, `COORDMETH`.
- RELYNUMB distribution: ~60% at 2 ft, then a long tail — 18 ft, 12 ft, 42 ft, **71 ft**.
- Filter adopted: **`RELYNUMB <= 10`** (≤ ~3 m); `positional_accuracy_m: 3.0` post-filter.

**NOAA NGS marks** (`NGS_Datasheets_Feature_Service/FeatureServer/1` = ALL_DATASHEETS — no layer 0; urban-LA sample n=200). Fields: `POS_SRCE`, `POS_ORDER`, `VERT_ORDER`, `LAST_COND`.
- POS_SRCE: **90.5% SCALED** (±150 m, hand-plotted), 8% hand-held GPS, **only 1.5% ADJUSTED**.
- LAST_COND: 5% "MARK NOT FOUND".
- Filter adopted: **`POS_SRCE = 'ADJUSTED' AND LAST_COND <> 'MARK NOT FOUND'`**; `positional_accuracy_m: 0.05`.

Both filters are live in `src/autogeo/config/defaults.yaml` baselines. Takeaway: "Tier 1" ≠ accurate; the `reliability_filter` is what makes the doctrine honest.

## LA municipal GIS (spike 2 / R-municipal) — see `defaults.yaml` `jurisdictions.los_angeles_city`

City of LA control is unusually strong (no city-level tier-1 gap): **109,604 BOE survey control points** (with NAD83 SP-ftUS attribute coords + `graphically_placed` flag) and **61,623 named street intersections** (`FROM_ST`/`TO_ST`) — near-direct Tier-1 label matching. All no-auth on `maps.lacity.org`. County on-prem hosts are Incapsula-walled; use their AGOL org. 8 layers curated (tiers 1–5). Live client test returned exactly 61,623 intersections (matches documented count).
