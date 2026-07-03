"""Data contracts (pydantic v2). Leaf package: imports nothing else from autogeo.

Every pipeline stage reads/writes these models as JSON in the per-document
workdir; changing a contract here is a schema change for the whole pipeline.
"""

from autogeo.models.control import ControlLayer, EpochValidity, JurisdictionLevel
from autogeo.models.document import (
    DocClass,
    DocumentContext,
    EraEstimate,
    LocationPrior,
    SheetType,
    StatedCRS,
    TextItem,
    UnitsEstimate,
)
from autogeo.models.gate import Decision, GateCheck, GateDecision, Route
from autogeo.models.gcp import CandidateGCP, GCPProvenance, GCPStatus
from autogeo.models.report import GeorefReport
from autogeo.models.solve import (
    DistributionMetrics,
    ErrorBudget,
    ResidualRecord,
    SolveResult,
    TransformType,
)

__all__ = [
    "CandidateGCP",
    "ControlLayer",
    "Decision",
    "DistributionMetrics",
    "DocClass",
    "DocumentContext",
    "EpochValidity",
    "EraEstimate",
    "ErrorBudget",
    "GCPProvenance",
    "GCPStatus",
    "GateCheck",
    "GateDecision",
    "GeorefReport",
    "JurisdictionLevel",
    "LocationPrior",
    "ResidualRecord",
    "Route",
    "SheetType",
    "SolveResult",
    "StatedCRS",
    "TextItem",
    "TransformType",
    "UnitsEstimate",
]
