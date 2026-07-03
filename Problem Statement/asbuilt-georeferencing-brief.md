# Automatic Georeferencing of As-Built PDFs — Project Brief for Claude Code

**Author:** Itay Bar-Lev · **Role of this doc:** planning + build brief handed to Claude Code (Fable 5). Read fully, produce an architecture + module plan first, then build in the phases at the end. Do not start coding before the plan is agreed.

---

## 1. Problem statement

Municipal, county, and utility as-built records exist as two incompatible artifact classes — **native vector PDFs** and **scanned raster PDFs** (often decades old) — that carry real-world engineering geometry but no usable spatial reference. We need a tool that automatically georeferences both classes by tying them to **temporally invariant GIS control** exposed through ArcGIS REST services (and equivalent sources), then emits both a georeferenced **raster** and **vector** product with a reported, gated **RMSE**.

The hard part is not the transform math — it is **choosing control that is still valid for the epoch of the document**. A 1965 plan cannot be tied to today's parcel fabric; it must be tied to features that have not moved. The tool's intelligence is in selecting the most stable available control per document.

## 2. Goals (success criteria)

1. **Two robust pipelines, one solver core.** Vector-PDF and scanned-PDF paths are first-class and equally reliable; they share a common ground-control → transform → validation core.
2. **Tiered automation.** Auto-georeference when confidence is high; fall back to assisted (human confirms/adjusts GCPs) when it is not. The auto→assisted decision is driven by RMSE and control geometry, not by guesswork.
3. **Invariant-first control selection.** Prefer the most temporally stable control available for the document's era; treat volatile layers as fallback only.
4. **Dual output.** Georeferenced raster (GeoTIFF + world file + sidecar) **and** vectors placed in the target CRS (GeoPackage / GeoJSON / DXF).
5. **Honest, gated accuracy.** Every output carries a per-GCP residual table, overall RMSE, and a pass/fail against a configurable tolerance. No silent placement.
6. **Batch + single.** Runs on one document interactively and on a directory of thousands headlessly.

## 3. Non-goals (scope discipline)

- Not a general CAD/GIS editor. It georeferences and exports; downstream editing happens in QGIS/Civil 3D.
- Not attempting semantic extraction of every drawing feature. Vector-PDF geometry is extracted wholesale; scanned-PDF vectorization is best-effort on control/key linework only (see §7).
- Not a survey-of-record tool. Outputs are positioned intelligence products with stated uncertainty, not legal survey.

## 4. Invariant-feature doctrine (control selection logic)

Rank candidate control by temporal stability and use the highest available; degrade only as needed:

| Tier | Control feature | Stability | Role |
|---|---|---|---|
| 1 | PLSS section/quarter corners, survey monuments, benchmarks | Decades–permanent | **Primary** for old docs |
| 2 | Street/road centerlines, rail centerlines, ROW lines | High (subject to realignment) | Primary for modern docs, strong secondary |
| 3 | Hydrography / permanent structures (bridges, dams) | High | Supplementary |
| 4 | Parcels / lot lines | Low (subdivision churn) | **Fallback only** |
| 5 | Building footprints | Lowest | Last resort / sanity check |

- The document's **estimated era** biases the ranking (older → lean harder on Tiers 1–2).
- Control layers are **discovered**, not hardcoded: the tool queries the jurisdiction's ArcGIS REST catalog and maps available layers onto this doctrine. The feature list is explicitly non-exhaustive and extensible via config.

## 5. Coordinate system & datum handling

- **Detect the stated CRS** by OCR of the title block / notes (e.g., State Plane zone, NAD83 vs NAD27, US Survey Feet vs meters, basis of bearings, named benchmarks).
- Use the CRS of the matched GIS layers as a **prior** when the title block is silent or illegible.
- Handle **datum shifts** explicitly (NAD27↔NAD83/HARN) via `pyproj` transformation grids — critical for older documents.
- Report all outputs in the target project CRS; retain original stated CRS in metadata.

## 6. Tiered matching pipeline

A single document flows through tiers; each tier proposes candidate GCPs with a confidence score. Tiers compound rather than compete.

- **Tier 0 — CRS/era detection.** OCR title block → stated CRS, datum, units, and any date. Establishes search priors.
- **Tier 1 — Label→attribute matching (highest precision).** OCR map text (street names, APNs, station numbers, monument IDs) and match to GIS feature attributes. A matched labeled intersection or monument becomes a high-confidence GCP.
- **Tier 2 — Geometric registration.** Detect linework (road edges/centerlines, ROW, parcel boundaries) via CV; match geometry to GIS vector geometry using point-set registration (feature correspondences → **RANSAC-guarded affine** least squares; **thin-plate spline** for warped scans). No text required.
- **Tier 3 — Multimodal LLM tie-point proposal (fallback for messy scans).** Present the page plus candidate GIS context to a vision model to propose corresponding tie points where Tiers 1–2 are thin. Treated as low-prior candidates, always validated by the solver.
- **Assisted fallback.** If the confidence gate (§8) fails, hand the candidate GCPs to the human-in-loop reviewer for confirm/adjust, then re-solve.

## 7. Transform models & output contract

**Transform selection**
- Default **6-parameter affine** (as-builts are to-scale plans).
- **Thin-plate spline** when scan warp/residual pattern demands it.
- Higher-order polynomial only when guarded and cross-validated (guard against overfit).

**Raster output (both classes):** GeoTIFF + world file + `.aux.xml` (or embedded CRS), plus GCP table.

**Vector output**
- *Vector PDF:* extract native geometry (lines, polylines, text-anchored points) and **transform into target CRS** → GeoPackage / GeoJSON / DXF.
- *Scanned PDF:* georeferenced raster always; vectors are **best-effort** — digitized control features and optionally traced key linework — clearly flagged as derived, not native.

**Report:** per-GCP residuals, overall RMSE (feet *and* meters), transform type/params, control layers used, and pass/fail vs tolerance — as JSON + a human-readable PDF.

## 8. Confidence gate (the tiered decision)

Auto-accept **only if all** hold; otherwise route to assisted:
1. RMSE ≤ configurable tolerance (default e.g. ≤ 0.5 m / survey tolerance — **confirm value/units**).
2. ≥ N well-distributed GCPs (guard against collinear/clustered control).
3. Leave-one-out cross-validation residuals within tolerance.
4. At least one **independent** control check (control not used in the solve) agrees.

The gate threshold and N are exposed in config so the same tool can run conservative (audit-grade) or permissive (triage) modes.

## 9. Recommended tech stack (open to override)

- **Core (Python 3.11):** GDAL/rasterio, `pyproj`, `shapely`, `geopandas`, `opencv-python`, `scikit-image`, `numpy`, `pymupdf`/`pdfplumber` (native vector + text extraction), `requests` (ArcGIS REST).
- **OCR:** Tesseract baseline; multimodal LLM (Claude API) for title-block parsing and Tier-3 tie points.
- **Assisted tier:** QGIS as the human-in-loop GCP editor (mature Georeferencer + GCP table), driven by the tool's candidate-GCP files. *(Alternative: a thin custom review UI — heavier to build; QGIS is the shortest robust path.)*
- **Interface:** CLI + YAML config; headless batch runner; structured logging.

**Recommendation:** Python core does all detection/matching/solving/output; QGIS is invoked only for the assisted-review tier. This keeps batch fully headless while giving the fallback a proven editor. Confirm if you'd rather embed everything in a QGIS plugin instead.

## 10. Acceptance criteria

- Round-trips a labeled **test set** (known-good georeferenced as-builts across CA/NY/AZ jurisdictions and both artifact classes) within tolerance.
- Correctly **refuses** to auto-place documents where control is insufficient (routes to assisted rather than emitting a bad transform).
- Reproduces reported RMSE under leave-one-out validation.
- Batch run over a directory produces per-document reports and a roll-up index.

## 11. Requests to Claude Code (what to do, in order)

1. **Plan first.** Produce module architecture, data contracts between tiers, the ArcGIS REST catalog/invariant-layer discovery design, and a risk register. Pause for review.
2. **Phase 0 — scaffold:** repo, config schema, CRS/datum registry, ArcGIS REST client + invariant-layer catalog mapping (§4).
3. **Phase 1 — vector-PDF pipeline:** native geometry + text extraction → Tier 1 label-match → affine solve → dual raster+vector output → report.
4. **Phase 2 — scanned pipeline:** rasterize → CV linework → OCR → Tier 2 registration → outputs.
5. **Phase 3 — intelligence layer:** Tier 3 multimodal fallback + confidence gate (§8) + QGIS assisted hand-off.
6. **Phase 4 — scale + validation:** batch runner, roll-up reporting, and the test harness against the labeled set.

Each phase ends with a runnable artifact and a short validation note before proceeding.

## 12. Decisions still to confirm (answer inline before Phase 1)

1. **RMSE target + units** for the auto-accept gate (e.g., ≤ 0.5 m, or a project survey tolerance in US survey feet).
2. **Stack shape:** Python-core + QGIS-assisted (recommended) vs. all-in QGIS plugin.
3. **Scanned vectorization depth:** control-only, or attempt traced key linework too.
4. **Multimodal provider** for Tier 3 (Claude API assumed).
5. **ArcGIS access:** live REST query with caching (assumed) vs. pre-staged local layers.
6. **Seed jurisdictions** to build/validate against first (assume CA / NY / AZ from your active work).
