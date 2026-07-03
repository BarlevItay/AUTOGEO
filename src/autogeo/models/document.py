"""Document-side contracts: what the ingest/ocr/context stages know about a page.

All pixel coordinates are in the canonical pixel frame: the page rendered at
`dpi` (default 300), origin top-left, y-down, `px = pdf_pt * dpi / 72`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DocClass = Literal["vector", "scanned", "hybrid"]
SheetType = Literal["plan", "plan_and_profile", "schematic", "cover_notes_index", "unknown"]


class TextItem(BaseModel):
    """One word/span of text located on the page, from native PDF text or OCR."""

    text: str
    pixel_bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in pixel frame
    angle_deg: float = 0.0
    source: Literal["native", "ocr"]
    ocr_conf: float | None = None  # 0..100 tesseract confidence; None for native


class EraEstimate(BaseModel):
    """Estimated document era; drives control-tier bias and the gate's era band."""

    year_estimate: int | None = None
    year_min: int | None = None
    year_max: int | None = None
    confidence: float = 0.0  # 0..1
    evidence: list[str] = Field(default_factory=list)  # e.g. "titleblock date '3-12-1964'"


class StatedCRS(BaseModel):
    """The CRS the document claims (title block) or that we assume (prior)."""

    crs_auth_code: str | None = None  # e.g. "EPSG:2229"
    crs_wkt: str | None = None
    datum: Literal["NAD27", "NAD83", "NAD83_HARN", "NAD83_2011", "WGS84", "unknown"] = "unknown"
    unit: Literal["us_survey_foot", "international_foot", "meter", "unknown"] = "unknown"
    zone_text: str | None = None  # raw title-block wording
    source: Literal["titleblock", "layer_prior", "config_default"] = "config_default"
    confidence: float = 0.0


class UnitsEstimate(BaseModel):
    """Drawing scale inference (scale bar / '1\"=40'' notes). Never blocks the pipeline."""

    scale_ratio: float | None = None  # drawing units per paper unit, e.g. 480 for 1"=40'
    drawing_unit: Literal["us_survey_foot", "international_foot", "meter", "unknown"] = "unknown"
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class LocationPrior(BaseModel):
    """Where on Earth to search for control."""

    jurisdiction_id: str | None = None  # key into config.jurisdictions
    envelope_wgs84: tuple[float, float, float, float] | None = None  # xmin, ymin, xmax, ymax
    source: Literal["config", "titleblock", "tier1_match", "manual"] = "config"


class DocumentContext(BaseModel):
    """Everything Tier 0 established about one page. Input to all matching tiers."""

    doc_id: str
    source_path: str
    page_number: int = 0  # zero-based page within the source document
    doc_class: DocClass
    sheet_type: SheetType = "unknown"
    dpi: int = 300
    page_size_px: tuple[int, int]  # width, height of the canonical pixel frame
    working_raster: str  # path relative to the workdir
    era: EraEstimate = Field(default_factory=EraEstimate)
    stated_crs: StatedCRS = Field(default_factory=StatedCRS)
    units: UnitsEstimate = Field(default_factory=UnitsEstimate)
    location_prior: LocationPrior = Field(default_factory=LocationPrior)
    titleblock_facts: dict = Field(default_factory=dict)  # raw LLM output, provenance kept
