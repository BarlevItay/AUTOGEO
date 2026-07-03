"""Contract round-trip tests: every model survives JSON serialization intact.

These contracts are the pipeline spine — a field that doesn't round-trip will
corrupt workdir resume and the QGIS assisted loop.
"""

from datetime import datetime, timezone

from autogeo.models import (
    CandidateGCP,
    ControlLayer,
    DistributionMetrics,
    DocumentContext,
    EpochValidity,
    EraEstimate,
    ErrorBudget,
    GCPProvenance,
    GateCheck,
    GateDecision,
    GeorefReport,
    LocationPrior,
    ResidualRecord,
    SolveResult,
    StatedCRS,
    TextItem,
    UnitsEstimate,
)


def make_context() -> DocumentContext:
    return DocumentContext(
        doc_id="la000112283",
        source_path="LA/TIFF/la000112283.tif",
        page_number=0,
        doc_class="scanned",
        sheet_type="plan_and_profile",
        dpi=300,
        page_size_px=(10200, 6600),
        working_raster="working.tif",
        era=EraEstimate(year_estimate=1964, year_min=1960, year_max=1968, confidence=0.8,
                        evidence=["titleblock date '3-12-1964'"]),
        stated_crs=StatedCRS(crs_auth_code="EPSG:2229", datum="NAD27", unit="us_survey_foot",
                             zone_text="CALIF ZONE 5", source="titleblock", confidence=0.7),
        units=UnitsEstimate(scale_ratio=480, drawing_unit="us_survey_foot", confidence=0.9,
                            evidence=["scale note 1\"=40'"]),
        location_prior=LocationPrior(jurisdiction_id="los_angeles_city",
                                     envelope_wgs84=(-118.5, 33.9, -118.1, 34.2),
                                     source="config"),
    )


def make_gcp(i: int = 7) -> CandidateGCP:
    return CandidateGCP(
        gcp_id=f"t1-{i:04d}",
        pixel_x=1234.5, pixel_y=987.6,
        world_x=6.48e6, world_y=1.84e6, world_crs="EPSG:2229",
        source_tier=1, doctrine_tier=2, confidence=0.85, status="used", residual_m=0.31,
        provenance=GCPProvenance(layer_key="abc123", layer_url="https://x/FeatureServer",
                                 feature_oid=42, matched_label="MAIN ST & 5TH ST",
                                 method="tier1_intersection"),
    )


def make_solve() -> SolveResult:
    return SolveResult(
        transform_type="affine",
        params={"a": 0.1, "b": 0.0, "c": 6.4e6, "d": 0.0, "e": -0.1, "f": 1.9e6},
        target_crs="EPSG:2229",
        n_candidates=12, n_inliers=9,
        inlier_ids=[f"t1-{i:04d}" for i in range(9)],
        outlier_ids=["t1-0009"], holdout_ids=["t1-0010", "t2-0001"],
        rmse_m=0.42, rmse_ft_us=1.38, loo_max_m=0.61, loo_mean_m=0.35,
        residuals=[ResidualRecord(gcp_id="t1-0001", dx_m=0.2, dy_m=-0.1,
                                  residual_m=0.22, loo_residual_m=0.30)],
        holdout_residuals=[ResidualRecord(gcp_id="t2-0001", dx_m=0.5, dy_m=0.2, residual_m=0.54)],
        distribution=DistributionMetrics(hull_area_ratio=0.4, collinearity_ratio=0.5,
                                         quadrant_coverage=4),
        error_budget=ErrorBudget(control_accuracy_m=1.0, datum_uncertainty_m=0.15,
                                 scan_resolution_m=0.05, achievable_rmse_m=1.01),
    )


def make_gate() -> GateDecision:
    return GateDecision(
        decision="auto_accept", route="outputs", era_band="pre1980_scan",
        rmse_threshold_m=1.5,
        checks=[GateCheck(name="rmse", passed=True, value=0.42, threshold=1.5),
                GateCheck(name="cross_family_independence", passed=True,
                          detail="holdout from NGS marks, solve from centerlines")],
        reasons=["all checks passed"],
    )


def test_full_report_round_trip():
    report = GeorefReport(
        tool_version="0.1.0",
        created_at=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        config_hash="deadbeef",
        document=make_context(),
        control_layers_used=[ControlLayer(
            layer_key="abc123", service_url="https://x/FeatureServer", layer_id=0,
            name="Street Centerlines", geometry_type="polyline", doctrine_tier=2,
            jurisdiction_level="city", source="jurisdiction", label_fields=["ST_NAME"],
            layer_crs="EPSG:2229", feature_count=75000,
            epoch=EpochValidity(valid_from_year=1900, stability="high"),
            positional_accuracy_m=1.0, reliability_filter=None,
        )],
        tier_summary={"tier1_candidates": 12},
        gcps=[make_gcp()],
        solve=make_solve(),
        gate=make_gate(),
        outputs={"geotiff": "georef.tif", "gpkg": "vectors.gpkg"},
        timings_s={"solve": 0.8},
    )
    dumped = report.model_dump_json()
    reloaded = GeorefReport.model_validate_json(dumped)
    assert reloaded == report


def test_not_georeferenceable_report_has_no_solve():
    report = GeorefReport(
        tool_version="0.1.0",
        created_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        config_hash="deadbeef",
        document=make_context(),
        gate=GateDecision(decision="not_georeferenceable", route="skip",
                          reasons=["sheet type: cover_notes_index"]),
    )
    reloaded = GeorefReport.model_validate_json(report.model_dump_json())
    assert reloaded.solve is None
    assert reloaded.gate.decision == "not_georeferenceable"


def test_text_item_and_gcp_round_trip():
    item = TextItem(text="MAIN ST", pixel_bbox=(10, 20, 110, 40), source="ocr", ocr_conf=88.0)
    assert TextItem.model_validate_json(item.model_dump_json()) == item
    gcp = make_gcp()
    assert CandidateGCP.model_validate_json(gcp.model_dump_json()) == gcp


def test_gcp_rejects_bad_tier_and_confidence():
    import pytest

    with pytest.raises(ValueError):
        make_gcp().model_copy(update={"doctrine_tier": 6}).model_validate(
            make_gcp().model_dump() | {"doctrine_tier": 6}
        )
    with pytest.raises(ValueError):
        CandidateGCP.model_validate(make_gcp().model_dump() | {"confidence": 1.5})
