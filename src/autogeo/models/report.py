"""GeorefReport — the per-document report.json root and batch-rollup row source."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from autogeo.models.control import ControlLayer
from autogeo.models.document import DocumentContext
from autogeo.models.gate import GateDecision
from autogeo.models.gcp import CandidateGCP
from autogeo.models.solve import SolveResult


class GeorefReport(BaseModel):
    schema_version: str = "1.0"
    tool_version: str
    created_at: datetime
    config_hash: str
    document: DocumentContext
    control_layers_used: list[ControlLayer] = Field(default_factory=list)
    tier_summary: dict[str, int] = Field(default_factory=dict)  # {"tier1_candidates": 14, ...}
    gcps: list[CandidateGCP] = Field(default_factory=list)  # final statuses + residuals
    solve: SolveResult | None = None  # None when not_georeferenceable / no solve reached
    gate: GateDecision
    outputs: dict[str, str] = Field(default_factory=dict)  # {"geotiff": "...", "gpkg": "..."}
    timings_s: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
