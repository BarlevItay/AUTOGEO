"""Solver contracts: transform fit, residuals, and cross-validation stats."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TransformType = Literal["affine", "poly2", "tps"]


class ResidualRecord(BaseModel):
    gcp_id: str
    dx_m: float
    dy_m: float
    residual_m: float
    loo_residual_m: float | None = None  # residual when this GCP is left out of the fit


class DistributionMetrics(BaseModel):
    """Guards against collinear/clustered control that makes affine unstable."""

    hull_area_ratio: float  # convex hull(inlier px) / page area
    collinearity_ratio: float  # sqrt(lambda2/lambda1) of centered pixel covariance
    quadrant_coverage: int = Field(ge=0, le=4)


class ErrorBudget(BaseModel):
    """Itemized floor on achievable accuracy — what the RMSE can honestly claim."""

    control_accuracy_m: float  # worst positional_accuracy_m among layers used
    datum_uncertainty_m: float = 0.0  # e.g. NADCON grid-shift uncertainty
    scan_resolution_m: float = 0.0  # ground size of one pixel at drawing scale
    achievable_rmse_m: float  # combined floor (root-sum-square)


class SolveResult(BaseModel):
    transform_type: TransformType
    params: dict  # affine: {a,b,c,d,e,f}; tps/poly2: serialized control points/coeffs
    target_crs: str
    n_candidates: int
    n_inliers: int
    inlier_ids: list[str] = Field(default_factory=list)
    outlier_ids: list[str] = Field(default_factory=list)
    holdout_ids: list[str] = Field(default_factory=list)
    rmse_m: float
    rmse_ft_us: float
    loo_max_m: float | None = None
    loo_mean_m: float | None = None
    residuals: list[ResidualRecord] = Field(default_factory=list)
    holdout_residuals: list[ResidualRecord] = Field(default_factory=list)
    distribution: DistributionMetrics
    error_budget: ErrorBudget | None = None
    escalation_reason: str | None = None  # why TPS/poly2 was chosen over affine
