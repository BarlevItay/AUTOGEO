"""Control-layer contracts: a discovered/curated GIS layer usable as GCP source.

Doctrine tiers rank temporal stability (1 = monuments/PLSS ... 5 = buildings),
but effective rank is min(temporal stability, positional accuracy): a ±30 m
GCDB-digitized PLSS corner must lose to a ±2 m street centerline.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JurisdictionLevel = Literal["city", "county", "state", "national"]


class EpochValidity(BaseModel):
    """Temporal validity of the layer's features as document-era control."""

    valid_from_year: int | None = None  # earliest era this control can anchor
    valid_to_year: int | None = None  # None = still valid
    stability: Literal["permanent", "decades", "high", "low", "lowest"] = "high"


class ControlLayer(BaseModel):
    """One queryable control source. `source` records how we came to trust it."""

    layer_key: str  # stable hash of service_url + layer_id
    service_url: str
    layer_id: int
    name: str
    geometry_type: Literal["point", "polyline", "polygon"]
    doctrine_tier: int = Field(ge=1, le=5)
    jurisdiction_level: JurisdictionLevel = "national"
    source: Literal["jurisdiction", "baseline", "manual"]
    label_fields: list[str] = Field(default_factory=list)  # fields usable for Tier-1 match
    layer_crs: str | None = None  # e.g. "EPSG:2229"
    feature_count: int | None = None
    epoch: EpochValidity = Field(default_factory=EpochValidity)
    positional_accuracy_m: float | None = None  # published/estimated absolute accuracy
    reliability_filter: str | None = None  # SQL where-clause excluding low-quality features
    score: float = 1.0  # doctrine classification confidence (1.0 for curated entries)
    matched_keywords: list[str] = Field(default_factory=list)
    notes: str = ""
