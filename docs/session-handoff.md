# Session Handoff — resume point

**Last session end:** 2026-07-03. **Repo:** https://github.com/BarlevItay/AUTOGEO.git (main @ `813a140`, 7 commits, pushed).
**Tests:** 78 green (`.venv/Scripts/python.exe -m pytest tests/`; live tests with `-m live`).

## State: Phase 0 complete, Phase 1 not started

Built & committed: contracts (`models/`), config (`config/` + curated LA registry in `defaults.yaml`), CRS/datum registry with NADCON guards (`context/crs.py`), full GIS layer (`gis/`), error-budget model (`solve/budget.py`), synthetic generator (`synth/` — generate + model, round-trip verified; **features.py + suite script still TODO**), LLM vision client (`ocr/llm_client.py`), sliding-window tiler (`ingest/tiling.py`). CLI: `autogeo catalog show|discover` work; `autogeo run` is still a stub.

Spikes done: corpus census (`data/census/`), control reliability, LA municipal GIS, **OCR-yield (R2 retired)**. Findings in `docs/spike-findings.md`.

## Locked decisions (do not relitigate)
- **No hand-labeled ground truth, ever.** Validation = synthetic (T1) + self-consistency: cross-tier, cross-source, mosaic misclosure on the 24-sheet run (T2). QGIS = production assisted editor only.
- **Provider = Claude** (anthropic SDK); `.env` has a valid `sk-ant-` key (gitignored). **Vision model is primary OCR**, no Tesseract.
- **LA-city-first**; jurisdiction specifics live only in config. Era-scaled + error-budget gate (0.5 m modern / 1.5 m pre-1980, relaxed to control accuracy).

## Next session — start here
1. **Solver core** (task #13, do first — synth generator already gives it ground truth): `solve/transforms.py`, `ransac.py`, `validate.py` (LOO-CV, distribution), `solver.py` → `SolveResult`. Cross-check vs GDAL (T2). This is the shared spine; build it before the tiers.
2. **Phase 1 steel thread** (task #12): ingest (native vector extract → canonical pixel frame) → `ocr/titleblock` + `context/era` → `match/tier1_labels` (street-pair→intersection GCP, monument→point GCP against curated LA layers) → solver → gate → `output/` (GeoTIFF+worldfile, GPKG, `.points`, report) → wire `autogeo run`. Demo on an in-hand text-bearing BOE PDF (`LA/PDF/BOEApproved_REL_1_A00XDHF_CRAN_LAYOUT.pdf` or the Zayo/NE-11 sets).
3. **Synth suite** (task #14): `synth/features.py` (live LA fetch) + `scripts/make_synth.py` → `data/synth/` suite; then `autogeo validate --synthetic`.

Optional: wrong-datum gate demo (task #9) — mostly redundant with the CRS suite; fold into the gate tests instead.

## Gotchas (also in CLAUDE.md profile)
- pyproj NAD27→NAD83 needs `only_best=True` + CONUS area_of_interest (else pulls the Canada grid) + NADCON grids present.
- PLSS corners ±30 m, NGS 90% SCALED ±150 m — reliability filters mandatory.
- LA County on-prem hosts are Incapsula-walled → use their AGOL org `services.arcgis.com/RmCCgQtiZLDCtblq`.
- QGIS `.points` sourceY is negative — handle sign in gcpfile round-trip.
- Every in-hand TIFF is bilevel 300 DPI E-size (~11000×7500) — OCR must tile (2048 px, 20% overlap); full-page downscale starves Tier 1.
- Some in-hand vector PDFs are text-as-curves (zero /Font) — OCR-of-rendered-raster path needed even for "vector" docs.
