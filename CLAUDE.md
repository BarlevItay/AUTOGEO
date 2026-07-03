# AUTOGEO

Automatic georeferencing of as-built PDFs/TIFFs against temporally-invariant GIS control from ArcGIS REST services. Approved implementation plan: `C:\Users\ItayBar-Lev\.claude\plans\ok-fable-this-is-agile-diffie.md` (architecture, data contracts, risk register, phases). Problem brief: `Problem Statement\asbuilt-georeferencing-brief.md`.

Scoping: **City of Los Angeles first** (corpus in `LA/`, gitignored), then other CA cities via config only, then AZ/NY. Municipal GIS (LA GeoHub/BOE) ranks ahead of county/national in control discovery.

<!-- daily-loop:profile:start -->
## Daily-Loop Profile

**Project:** Georeferences as-built PDFs/TIFFs (vector + scanned) to GIS control with gated RMSE; dual raster+vector output.
**Stack:** Python 3.11 src-layout package `autogeo` (pydantic v2 contracts, GDAL/pyproj/shapely, pymupdf, opencv/scikit-image, typer CLI); QGIS only as human GCP editor; Claude API for title-block parse + Tier-3 tie points.
**External systems:** ArcGIS REST (LA GeoHub/BOE, LA County eGIS, BLM PLSS, NGS, TIGERweb, NHD) | Anthropic API | QGIS `.points` round-trip.

### Run as a real user (must-fill)
- Command / path: `autogeo run <pdf> --jurisdiction los_angeles_city` (single doc) · `autogeo batch <dir>` (headless) · `autogeo resume <workdir>` (after QGIS GCP edit)
- User-visible success: georeferenced GeoTIFF + GPKG land on the correct LA streets in QGIS; report.pdf shows per-GCP residuals, RMSE (m + ftUS), and an honest gate verdict.

### Reality-check definition (must-fill — the core)
- **HARD CONSTRAINT: no hand-labeled ground truth exists or ever will** (user, 2026-07-03 — the stated challenge). Validation is label-free.
- Ground truth: synthetic plans in `data/synth/` rendered from real curated-registry GIS features under KNOWN transforms, both artifact-class styles (clean vector / degraded bilevel scan) — full-pipeline blind recovery is T1.
- The check: `autogeo validate` — (a) synthetic suite recovered blind within era band; (b) real docs: cross-tier agreement (Tier-1-only vs Tier-2-only solves), cross-source holdout (city vs county/national provenance), mosaic misclosure on the 24-sheet contiguous run; control-poor docs REFUSED; wrong-datum construction caught by the gate.
- NOT done here: "pipeline ran", "GeoTIFF written", "RMSE printed", or **any single self-consistency metric alone** — internal RMSE passing on coherently-shifted output is the canonical false green; LLM-vision overlay judgment is triage, never proof.

### Known gotchas (maintained — max ~10 active, one line each; overflow evicts to the memory backend)
- pyproj NAD27→NAD83 silently falls back to multi-meter Helmert without NADCON grids — always `only_best=True` + startup grid assert.
- PLSS corners can be ±30 m (GCDB), NGS SCALED benchmarks ±150 m — reliability filters are mandatory, "Tier 1" ≠ accurate.
- RMSE + LOO-CV cannot detect a coherent datum/era shift — cross-family holdout + dual-datum solve are the guards.
- `LA/` corpus TIFFs are NOT georeferenced (verified 2026-07-03) — corpus, not ground truth.
- Some sheets are unplaceable by design (cover/notes/schematic TCTMC) — triage to `not_georeferenceable`, never count as failures.
- Two in-hand vector PDFs have text-as-curves (zero /Font objects) — Tier 1 needs the OCR-of-rendered-raster path even for vector docs.
- QGIS `.points` sourceY is negative (row) — handle sign explicitly in gcpfile round-trip.
- LA County on-prem GIS hosts (*.lacounty.gov) are Incapsula bot-walled — use their AGOL org `services.arcgis.com/RmCCgQtiZLDCtblq` instead.
- PROJ picks regional grids by CRS pair alone (NAD27→NAD83 pulls the *Canada* NTv2 grid) — always pass a CONUS/LA area_of_interest.
- LLM provider = Claude (anthropic SDK); key in `.env` as `sk-ant-` (108 chars), loaded via load_api_key(). Vision model is the PRIMARY OCR for title blocks AND map labels (user chose no Tesseract); tesseract.py is optional fallback only.

### Memory backend (must-fill — where capture/recall go)
- Backend: LOCAL files at `C:\Users\ItayBar-Lev\.claude\projects\D--Repo-AUTOGEO\memory\` + `MEMORY.md` index (no anchor-mem MCP connected — do not call anchor-mem tools).
- Keys / slice to pull: `project-autogeo-scope`, `reference-autogeo-gis-services`, `feedback-plan-premortem-style`.

### Model overrides (optional; else default routing)
- default routing; solver/gate correctness work stays on the decision model (geospatial outputs feed deliverables).
<!-- daily-loop:profile:end -->

## Working conventions

- Contracts live in `src/autogeo/models/` (leaf package, no I/O, imports nothing from `autogeo`) — change contracts first, consumers second.
- All pixel coordinates are in the canonical pixel frame (300 DPI render, y-down, `px = pdf_pt * dpi / 72`); never mix frames.
- Jurisdiction specifics (URLs, CRS, layer ids) live ONLY in config/registry — never in module code (Phase 4 second-city gate enforces this).
- `data/` and `LA/` are gitignored corpus/cache dirs; runs land in `runs/<doc_id>/`.
