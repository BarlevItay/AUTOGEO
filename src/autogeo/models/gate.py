"""Confidence-gate contracts: the auto/assisted/refuse decision, itemized.

`not_georeferenceable` is a first-class outcome for sheets that are unplaceable
by design (cover/notes pages, schematic layouts) — never counted as a failure.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GateCheckName = Literal[
    "rmse",
    "min_gcps",
    "distribution",
    "loo_cv",
    "independent_holdout",
    "cross_family_independence",
    "datum_ambiguity",
    "unit_ambiguity",
    "single_family",
    "majority_tier3",
]

Decision = Literal["auto_accept", "assisted", "reject_insufficient_control", "not_georeferenceable"]
Route = Literal["outputs", "qgis_review", "manual_triage", "skip"]


class GateCheck(BaseModel):
    name: GateCheckName
    passed: bool
    value: float | None = None
    threshold: float | None = None
    detail: str = ""


class GateDecision(BaseModel):
    decision: Decision
    route: Route
    era_band: str = ""  # e.g. "modern_vector" | "pre1980_scan"
    rmse_threshold_m: float | None = None  # the era/error-budget threshold actually applied
    checks: list[GateCheck] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
