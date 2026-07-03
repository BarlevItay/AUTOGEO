"""The full Settings tree. Every threshold, keyword map, and jurisdiction
specific hangs off this — module code must never hardcode any of it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from autogeo.models.control import JurisdictionLevel


class ProjectConfig(BaseModel):
    name: str = "autogeo"
    target_crs: str = "EPSG:2229"  # overridden per jurisdiction/run
    output_dir: Path = Path("runs")


class RmseThreshold(BaseModel):
    era_band: str  # e.g. "modern_vector", "pre1980_scan"
    max_m: float


class GateConfig(BaseModel):
    rmse_thresholds: list[RmseThreshold] = Field(default_factory=list)
    min_gcps: int = 5
    min_hull_area_ratio: float = 0.15
    min_collinearity_ratio: float = 0.10
    loo_factor: float = 1.5  # LOO residuals must stay within loo_factor * threshold
    holdout_factor: float = 2.0  # independent holdout within holdout_factor * threshold
    mode: Literal["conservative", "permissive"] = "conservative"
    # error budget: gate threshold is max(era threshold, budget_factor * achievable_rmse)
    error_budget_factor: float = 1.0


class DoctrineConfig(BaseModel):
    keyword_map: dict[str, list[str]] = Field(default_factory=dict)  # "tier1" -> regexes
    label_field_map: dict[str, list[str]] = Field(default_factory=dict)  # "tier1" -> field regexes
    min_score: float = 2.0
    min_features_per_tier: int = 10
    # era bias: tier preference order per era band
    tier_order_pre1980: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    tier_order_modern: list[int] = Field(default_factory=lambda: [2, 1, 3, 4, 5])
    # per-state availability, e.g. {"NY": [2, 3, 4, 5]} — no PLSS in NY
    state_tier_availability: dict[str, list[int]] = Field(default_factory=dict)


class CuratedLayer(BaseModel):
    """A hand-verified registry entry — the primary control path for v1.

    Mirrors ControlLayer minus computed fields; gis.catalog converts and
    assigns the stable layer_key.
    """

    service_url: str
    layer_id: int
    name: str
    geometry_type: Literal["point", "polyline", "polygon"]
    doctrine_tier: int = Field(ge=1, le=5)
    jurisdiction_level: JurisdictionLevel
    label_fields: list[str] = Field(default_factory=list)
    layer_crs: str | None = None
    positional_accuracy_m: float | None = None
    reliability_filter: str | None = None
    notes: str = ""


class JurisdictionConfig(BaseModel):
    display_name: str = ""
    state: str = ""  # two-letter, keys state_tier_availability
    rest_roots: list[str] = Field(default_factory=list)  # discovery-assistant roots
    default_crs: str | None = None
    envelope_wgs84: tuple[float, float, float, float] | None = None
    layers: list[CuratedLayer] = Field(default_factory=list)  # the curated registry


class BaselinesConfig(BaseModel):
    enabled: bool = True
    overrides: list[CuratedLayer] = Field(default_factory=list)


class ArcgisConfig(BaseModel):
    timeout_s: float = 30.0
    retries: int = 3
    politeness_delay_s: float = 0.2
    max_features_per_query: int = 5000
    max_services: int = 500  # discovery walk cap


class CacheConfig(BaseModel):
    dir: Path = Path("data/cache")
    catalog_ttl_days: int = 7
    feature_ttl_days: int = 30


class IngestConfig(BaseModel):
    dpi: int = 300
    deskew: bool = True


class OcrConfig(BaseModel):
    tesseract_cmd: str | None = None  # None = use PATH
    lang: str = "eng"
    min_conf: float = 40.0


class LlmTitleblockConfig(BaseModel):
    enabled: bool = True


class LlmTier3Config(BaseModel):
    enabled: bool = True
    max_calls_per_doc: int = 2


class LlmConfig(BaseModel):
    enabled: bool = True
    model: str = "claude-sonnet-5"  # vision-capable; per-call volume favors sonnet tier
    max_image_px: int = 2048
    titleblock: LlmTitleblockConfig = Field(default_factory=LlmTitleblockConfig)
    tier3: LlmTier3Config = Field(default_factory=LlmTier3Config)


class SolverConfig(BaseModel):
    ransac_threshold_factor: float = 2.0  # x gate tolerance, in meters
    ransac_max_trials: int = 2000
    tps_min_gcps: int = 8
    allow_poly2: bool = True  # scans only; still LOO-guarded
    holdout_n: int = 2


class TiersConfig(BaseModel):
    tier2_trigger_min_t1_gcps: int = 6  # run tier2 if tier1 produced fewer
    tier3_trigger_min_gcps: int = 5  # run tier3 if tiers 1+2 produced fewer


class OutputConfig(BaseModel):
    formats: list[Literal["geotiff", "gpkg", "geojson", "dxf"]] = Field(
        default_factory=lambda: ["geotiff", "gpkg", "geojson", "dxf"]
    )
    report_pdf: bool = True
    overviews: bool = True


class BatchConfig(BaseModel):
    workers: int = 4
    continue_on_error: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: Literal["console", "json"] = "console"
    per_doc_file: bool = True


class Settings(BaseModel):
    """Immutable merged configuration for a run."""

    model_config = {"frozen": True}

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    gate: GateConfig = Field(default_factory=GateConfig)
    doctrine: DoctrineConfig = Field(default_factory=DoctrineConfig)
    jurisdictions: dict[str, JurisdictionConfig] = Field(default_factory=dict)
    baselines: BaselinesConfig = Field(default_factory=BaselinesConfig)
    arcgis: ArcgisConfig = Field(default_factory=ArcgisConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    tiers: TiersConfig = Field(default_factory=TiersConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    batch: BatchConfig = Field(default_factory=BatchConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
