"""CandidateGCP — the single currency every matching tier trades in."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GCPStatus = Literal[
    "proposed",  # emitted by a tier, not yet solved
    "used",  # inlier in the accepted solve
    "ransac_outlier",
    "held_out",  # reserved for the independent check; never auto-fitted
    "human_confirmed",
    "human_moved",
    "human_deleted",
]


class GCPProvenance(BaseModel):
    """Where a candidate came from — enough to audit or re-derive it."""

    layer_key: str | None = None
    layer_url: str | None = None
    feature_oid: int | None = None
    matched_label: str | None = None  # e.g. "MAIN ST & 5TH ST" or benchmark designation
    method: str  # e.g. "tier1_intersection", "tier2_junction", "tier3_llm", "manual"
    llm_model: str | None = None
    detail: str = ""


class CandidateGCP(BaseModel):
    """One pixel<->world correspondence with confidence and full provenance.

    Pixel coordinates are in the canonical pixel frame (y-down). World
    coordinates always carry their CRS explicitly — no implied CRS anywhere.
    """

    gcp_id: str  # stable, e.g. "t1-0007"
    pixel_x: float
    pixel_y: float
    world_x: float
    world_y: float
    world_crs: str  # e.g. "EPSG:2229"
    source_tier: Literal[0, 1, 2, 3]  # 0 = manual/human
    doctrine_tier: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)  # prior, before solving
    status: GCPStatus = "proposed"
    residual_m: float | None = None  # filled after solve
    provenance: GCPProvenance
