# Session Handoff — resume point

**Last session end:** 2026-07-03. **Repo:** https://github.com/BarlevItay/AUTOGEO.git (main).
**Tests:** 94 passed, 1 deselected (`.venv/Scripts/python.exe -m pytest tests/`; live tests with `-m live`).

## State: Phase 0 complete + Solver core (#13) complete. Phase 1 not started.

Phase 0 (prior): contracts (`models/`), config + curated LA registry, CRS/datum registry with NADCON
guards (`context/crs.py`), GIS layer (`gis/`), error-budget model (`solve/budget.py`), synthetic
generator (`synth/` — generate+model; **features.py + suite script still TODO**), LLM vision client
(`ocr/llm_client.py`), sliding-window tiler (`ingest/tiling.py`). CLI: `catalog show|discover` work;
`run` is still a stub.

**Solver core (#13, this session) — DONE, certified T1/T2/T3.** New under `src/autogeo/solve/`:
- `transforms.py` — affine/poly2/tps fit+apply + dispatchers; module docstring is the authoritative
  `SolveResult.params` schema per family (affine `{a,b,c,d,e,f}` pixel→world).
- `ransac.py` — hand-rolled affine consensus, meters-scaled inlier gate, seeded (deterministic).
- `validate.py` — `linear_unit_to_m` (geographic-CRS guarded), residuals, LOO-CV, distribution
  metrics (hull/collinearity/quadrant), holdout.
- `solver.py` — `solve(candidates, *, target_crs, cfg, gate_cfg, page_size_px, dpi, scale_ratio,
  layers_used, datum_shift_applied, era_band_max_m, rng_seed=0) -> SolveResult`. Ordering:
  budget→RANSAC→holdout→fit→LOO→distribution→holdout residuals→escalation. Mutates each
  `CandidateGCP.status`/`.residual_m`.

Tests (21): `test_transforms.py` `test_ransac.py` `test_validate.py` `test_solver.py` + `conftest.py`
(synth→CandidateGCP fixtures). Verified: T1 recover injected affine ≈1.5e-08 ft; T2 agree with
`rasterio.from_gcps` ≈1.3e-08 m at corners; T3 outlier rejection / LOO leverage / collinearity /
determinism / warp→tps escalation.

## Solver contract for #12 to call
`solve()` requires candidates **already projected to `target_crs`** (CRS mismatch raises — reproject
in matching, which knows the AOI). It never needs the doc's stated CRS. `era_band_max_m` comes from
the era-band lookup the gate owns; pass the band max (0.5 modern_vector / 1.0 modern_scan /
1.5 pre1980_scan). Returns a fully-populated `SolveResult` (rmse m+ftUS, LOO, holdout, distribution,
error_budget); the gate reads it.

## Locked decisions (do not relitigate)
- **No hand-labeled ground truth, ever.** Validation = synthetic (T1) + self-consistency (cross-tier,
  cross-source, mosaic misclosure). Synth generator IS the "day-one ground truth" (answers the peer
  review's Gap 3). QGIS = production assisted editor only.
- **Provider = Claude** (anthropic SDK), vision = **primary OCR**, no Tesseract.
- **LA-city-first**; jurisdiction specifics only in config. Era-scaled + error-budget gate.

## Next session — start here
1. **Phase 1 steel thread (#12).** ingest (native vector extract → canonical pixel frame) →
   `ocr/titleblock` + `context/era` → `match/tier1_labels` (street-pair→intersection GCP,
   monument→point GCP against curated LA layers, **reproject matches to target_crs**) → `solve()` →
   **gate** (`gate/` — reads SolveResult vs `gate_threshold_m`; distribution/LOO/holdout/min_gcps
   checks) → `output/` (GeoTIFF+worldfile, GPKG, `.points`, report) → wire `autogeo run`. Demo on an
   in-hand text-bearing BOE PDF (`LA/PDF/BOEApproved_REL_1_A00XDHF_CRAN_LAYOUT.pdf`).
   **#12 MUST supply the solver's upstream guarantees (peer review):** coarse localization (candidate
   neighborhood, defends gridded-street wrong-block), sheet/viewport classification + plan-viewport
   clip (never feed profile/detail GCPs to solve), and the gate's absolute-position check (solved
   page-corner extent ⊂ `location_prior` envelope) + `datum_ambiguity`/`cross_family_independence`.
2. **Synth suite (#14).** `synth/features.py` (live LA fetch) + `scripts/make_synth.py` → `data/synth/`
   suite; then `autogeo validate --synthetic`. **Co-tune warp amplitude to the escalation band and the
   gate's `min_hull_area_ratio` to representative GCP spread** — see `project-autogeo-solver-warp-band`
   memory + notes below.

Optional: wrong-datum gate demo (#9) — fold into #12 gate tests (redundant with the CRS suite).

## New notes this session (also in memory: project-autogeo-solver-warp-band)
- **Escalation fires only in a warp band.** RANSAC threshold = `ransac_threshold_factor(2.0) ×
  tolerance`; a warp larger than that is rejected as outliers (routes to assisted, correctly) instead
  of escalating. Verified on 5×5/26-GCP synth: amp≈12→poly2, ≈15–18→tps, ≈22→affine+3 outliers.
  #14 warp cases must sit in-band. Do NOT widen the RANSAC threshold to force escalation.
- **Distribution guard is real:** 3×3 synth used-set hull_area_ratio=0.13 < GateConfig 0.15 → the gate
  would flag it clustered. #14 synth spread and the hull threshold must be co-tuned.
- `Reviewer/asbuilt-georeferencing-reviewer_opinion.md` is the user's peer review; reconciliation is in
  the approved plan (`~/.claude/plans/session-wrapped-per-the-compiled-haven.md`). Left untracked.

## Gotchas (also in CLAUDE.md profile)
- pyproj NAD27→NAD83 needs `only_best=True` + CONUS area_of_interest + NADCON grids present.
- PLSS corners ±30 m, NGS 90% SCALED ±150 m — reliability filters mandatory.
- LA County on-prem hosts Incapsula-walled → use AGOL org `services.arcgis.com/RmCCgQtiZLDCtblq`.
- QGIS `.points` sourceY is negative — handle sign in gcpfile round-trip.
- Every in-hand TIFF is bilevel 300 DPI E-size — OCR must tile (2048 px, 20% overlap).
- Some in-hand vector PDFs are text-as-curves (zero /Font) — OCR-of-rendered-raster path needed.
- RMSE+LOO-CV cannot detect a coherent datum/era shift OR a wrong-block/viewport-cluster fit — those
  are gate + upstream-localization guards, not solver-catchable (see plan premortem).
