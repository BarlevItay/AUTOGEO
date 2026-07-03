"""Residuals, cross-validation, distribution metrics, and the world-unit ->
meters conversion — everything needed to judge a fit honestly.

Residuals are computed in the target CRS itself (predicted world vs control
world, same CRS on both sides), so there is no datum shift *inside* the residual
and the conversion to meters is a pure isotropic unit scale for a projected
linear CRS. The scalar factor (meters per linear unit) is the single source of
truth shared by residuals, RANSAC, LOO, and holdout.
"""

from __future__ import annotations

import numpy as np
from pyproj import CRS
from shapely.geometry import MultiPoint

from autogeo.models import DistributionMetrics, ResidualRecord
from autogeo.models.solve import TransformType
from autogeo.solve.transforms import apply_transform, fit_transform, min_points


# ---- world units -> meters ------------------------------------------------


def linear_unit_to_m(target_crs: str) -> float:
    """Meters per one linear unit of a projected CRS axis. EPSG:2229 (US survey
    foot) -> 0.3048006096...; metric SPCS zones -> 1.0.

    Guards against a geographic (degree) target: the isotropic scalar would be
    meaningless, so refuse rather than silently mis-scale. Every v1 target is a
    projected SPCS zone.
    """
    crs = CRS.from_user_input(target_crs)
    if crs.is_geographic:
        raise NotImplementedError(
            f"{target_crs} is geographic; residual meters require a projected "
            "target CRS (v1 targets are all projected SPCS zones)."
        )
    return float(crs.axis_info[0].unit_conversion_factor)


# ---- residuals ------------------------------------------------------------


def residuals_m(
    kind: TransformType, params: dict, pixels, world, factor: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (dx_m, dy_m, magnitude_m) — components already in meters so the
    ResidualRecord.dx_m/dy_m fields don't lie for a ftUS CRS."""
    pred = apply_transform(kind, params, pixels)
    d = np.asarray(world, dtype=float) - pred
    dx_m = d[:, 0] * factor
    dy_m = d[:, 1] * factor
    mag_m = np.hypot(dx_m, dy_m)
    return dx_m, dy_m, mag_m


def rmse(mag_m) -> float:
    m = np.asarray(mag_m, dtype=float)
    if len(m) == 0:
        return 0.0
    return float(np.sqrt(np.mean(m**2)))


# ---- leave-one-out cross-validation ---------------------------------------


def loo_residuals(kind: TransformType, pixels, world, factor: float) -> np.ndarray:
    """Per-point residual (meters) when that point is left out of the fit.

    Returns an all-NaN array when there is too little redundancy to leave one
    out (N-1 < min_points); a per-point NaN marks a degenerate leave-one-out
    subset. The caller (loo_stats) is NaN-aware.
    """
    px = np.asarray(pixels, dtype=float)
    w = np.asarray(world, dtype=float)
    n = len(px)
    out = np.full(n, np.nan)
    if n - 1 < min_points(kind):
        return out
    idx = np.arange(n)
    for i in range(n):
        keep = idx != i
        try:
            params = fit_transform(kind, px[keep], w[keep])
        except Exception:
            continue
        pred = apply_transform(kind, params, px[i : i + 1])[0]
        d = w[i] - pred
        out[i] = float(np.hypot(d[0], d[1]) * factor)
    return out


def loo_stats(loo: np.ndarray) -> tuple[float | None, float | None]:
    arr = np.asarray(loo, dtype=float)
    finite = arr[np.isfinite(arr)]
    if len(finite) == 0:
        return None, None
    return float(finite.max()), float(finite.mean())


# ---- distribution (guards degenerate control geometry) --------------------


def distribution_metrics(pixels, page_size_px: tuple[int, int]) -> DistributionMetrics:
    px = np.asarray(pixels, dtype=float)
    pw, ph = float(page_size_px[0]), float(page_size_px[1])
    page_area = pw * ph

    if len(px) >= 3 and page_area > 0:
        hull = MultiPoint([tuple(p) for p in px]).convex_hull
        hull_area_ratio = float(getattr(hull, "area", 0.0)) / page_area
    else:
        hull_area_ratio = 0.0

    if len(px) >= 2:
        cov = np.cov(px.T)  # variables in rows -> 2x2
        eig = np.linalg.eigvalsh(cov)  # ascending
        lam1 = float(eig[-1])
        lam2 = max(0.0, float(eig[0]))
        collinearity_ratio = float(np.sqrt(lam2 / lam1)) if lam1 > 0 else 0.0
    else:
        collinearity_ratio = 0.0

    quadrants = {(x >= pw / 2, y >= ph / 2) for x, y in px}
    quadrant_coverage = len(quadrants) if len(px) else 0

    return DistributionMetrics(
        hull_area_ratio=hull_area_ratio,
        collinearity_ratio=collinearity_ratio,
        quadrant_coverage=quadrant_coverage,
    )


# ---- independent holdout --------------------------------------------------


def holdout_records(
    kind: TransformType, params: dict, ids: list[str], pixels, world, factor: float
) -> list[ResidualRecord]:
    """Residuals of the held-out points against the final fit they were excluded
    from. loo_residual_m stays None — holdout is a separate, already-independent
    guard from LOO."""
    if len(ids) == 0:
        return []
    dx_m, dy_m, mag_m = residuals_m(kind, params, pixels, world, factor)
    return [
        ResidualRecord(
            gcp_id=gid,
            dx_m=float(dx_m[i]),
            dy_m=float(dy_m[i]),
            residual_m=float(mag_m[i]),
            loo_residual_m=None,
        )
        for i, gid in enumerate(ids)
    ]
