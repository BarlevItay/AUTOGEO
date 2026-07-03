# AUTOGEO — Automatic Georeferencing of As-Built Records

Georeferences municipal as-built documents — both **native vector PDFs** and **scanned raster PDFs/TIFFs** — by matching their content to **temporally invariant GIS control** (survey monuments, PLSS corners, street centerlines) discovered from ArcGIS REST services. Emits a georeferenced **GeoTIFF** (+ world file) and **vectors** in the target CRS (GeoPackage / GeoJSON / DXF), with a per-GCP residual table, overall RMSE, and an honest auto-accept / assisted-review gate.

**Status:** Phase 0 (scaffold + control foundation). First test case: **City of Los Angeles**.

## Design pillars

- **One solver core, two pipelines** — vector and scanned documents share the same ground-control → transform → validation spine.
- **Invariant-first, accuracy-aware control** — control ranked by `min(temporal stability, GIS positional accuracy)`; a 1965 plan is tied to monuments and old rights-of-way, never today's parcel fabric — and never to a ±30 m digitized PLSS corner either.
- **Honest gating** — era- and error-budget-scaled RMSE thresholds, leave-one-out cross-validation, cross-family independent holdout, dual-datum hypothesis testing. No silent placement; documents the tool can't place route to a QGIS assisted-review round-trip.
- **Headless batch** — one CLI for a single document or a directory of thousands; per-document resumable workdirs.

## Layout

```
src/autogeo/     the package (contracts in models/, pipeline stages per module)
scripts/         corpus acquisition and labeling utilities
tests/           unit + fixture-based integration tests
Problem Statement/  original project brief
LA/              (gitignored) in-hand LA test corpus
data/            (gitignored) raw corpus, labeled golden set, caches
runs/            (gitignored) per-document output workdirs
```

Full architecture, data contracts, risk register, and phase plan: see the approved implementation plan (referenced in `CLAUDE.md`).
