"""The solver spine: candidate GCPs -> a validated ``SolveResult``.

Ordering is load-bearing (see the approved plan):

1. Error budget FIRST — the RANSAC inlier threshold is scaled to the *honest*
   tolerance (era band OR control/datum/pixel floor), never the optimistic era
   band. Physics sets the gate; the gate sets RANSAC.
2. RANSAC over ALL candidates — strongest consensus; no gross outlier can reach
   the holdout.
3. Holdout AFTER RANSAC, BEFORE the final fit — points drawn from confirmed
   inliers but excluded from the least-squares fit, so they independently test
   the *reported* transform. Conditional: skip when too few GCPs remain.
4-8. Fit -> residuals -> LOO-CV (used set only) -> distribution -> holdout
   residuals, all through the shared transforms/validate path.
9. Escalation — affine stands unless geometry is healthy AND LOO/holdout show
   systematic non-affine error, in which case poly2 then tps are tried and
   accepted only if they pass cross-validation.

Precondition: candidates are already expressed in ``target_crs``. Reprojection
belongs to the matching stage (it knows the area of interest); solving silently
under a CRS mismatch would mis-scale every residual, so a mismatch raises.

The solver cannot, alone, catch a *coherent* wrong-input shift (wrong datum,
wrong street block, a profile-viewport cluster) — those fit well by
construction. Its duty is an honest ``error_budget`` and a spatially-spread
holdout; the wrong-block/datum verdict belongs to the gate + upstream
localization (see the plan's premortem).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from autogeo.config.schema import GateConfig, SolverConfig
from autogeo.models import CandidateGCP, DistributionMetrics, ResidualRecord, SolveResult
from autogeo.models.control import ControlLayer
from autogeo.models.solve import TransformType
from autogeo.solve.budget import compute_error_budget, gate_threshold_m
from autogeo.solve.ransac import ransac_affine
from autogeo.solve.transforms import fit_transform, min_points
from autogeo.solve.validate import (
    distribution_metrics,
    holdout_records,
    linear_unit_to_m,
    loo_residuals,
    loo_stats,
    residuals_m,
    rmse,
)

_US_FOOT_M = 0.3048006096  # 1 US survey foot in meters (meters -> ftUS reporting mirror)


@dataclass
class _Outcome:
    kind: TransformType
    params: dict
    used_idx: np.ndarray
    residuals: list[ResidualRecord]
    holdout_residuals: list[ResidualRecord]
    distribution: DistributionMetrics
    rmse_m: float
    loo_max_m: float | None
    loo_mean_m: float | None


def solve(
    candidates: list[CandidateGCP],
    *,
    target_crs: str,
    cfg: SolverConfig,
    gate_cfg: GateConfig,
    page_size_px: tuple[int, int],
    dpi: int,
    scale_ratio: float | None,
    layers_used: list[ControlLayer],
    datum_shift_applied: bool,
    era_band_max_m: float,
    rng_seed: int = 0,
) -> SolveResult:
    # --- 0. extract + precondition -----------------------------------------
    mismatched = sorted({c.world_crs for c in candidates if c.world_crs != target_crs})
    if mismatched:
        raise ValueError(
            f"candidates must be pre-projected to target_crs={target_crs}; found "
            f"{mismatched}. Reproject upstream — the matching stage knows the AOI."
        )
    n_candidates = len(candidates)
    if n_candidates < min_points("affine"):
        raise ValueError(
            f"solve needs >= {min_points('affine')} candidates, got {n_candidates}"
        )
    ids = [c.gcp_id for c in candidates]
    by_id = {c.gcp_id: c for c in candidates}
    pixels = np.array([[c.pixel_x, c.pixel_y] for c in candidates], dtype=float)
    world = np.array([[c.world_x, c.world_y] for c in candidates], dtype=float)
    factor = linear_unit_to_m(target_crs)

    # --- 1. error budget -> tolerance -> RANSAC threshold ------------------
    budget = compute_error_budget(layers_used, datum_shift_applied, dpi, scale_ratio)
    tolerance_m = gate_threshold_m(era_band_max_m, budget, gate_cfg.error_budget_factor)
    ransac_thr_m = cfg.ransac_threshold_factor * tolerance_m

    # --- 2. RANSAC over all candidates -------------------------------------
    rng = np.random.default_rng(rng_seed)
    rr = ransac_affine(
        pixels, world, ransac_thr_m, factor, rng=rng, max_trials=cfg.ransac_max_trials
    )
    inlier_idx = np.flatnonzero(rr.inlier_mask)

    # --- 3. holdout selection (after RANSAC, before final fit) -------------
    notes: list[str] = []
    holdout_idx = _select_holdout(inlier_idx, pixels, cfg.holdout_n)
    if len(holdout_idx) and (len(inlier_idx) - len(holdout_idx)) < (min_points("affine") + 1):
        holdout_idx = np.array([], dtype=int)
        notes.append("holdout_skipped_too_few_gcps")
    holdout_set = set(holdout_idx.tolist())
    used_idx = np.array([i for i in inlier_idx.tolist() if i not in holdout_set], dtype=int)

    # --- 4-8. fit + validate affine ----------------------------------------
    result = _fit_and_validate("affine", used_idx, holdout_idx, pixels, world, ids, factor, page_size_px)

    # --- 9. escalation -----------------------------------------------------
    escalation_reason: str | None = None
    dist = result.distribution
    distribution_ok = (
        dist.collinearity_ratio >= gate_cfg.min_collinearity_ratio
        and dist.hull_area_ratio >= gate_cfg.min_hull_area_ratio
    )
    holdout_max = max((r.residual_m for r in result.holdout_residuals), default=0.0)
    affine_inadequate = (
        result.loo_max_m is not None and result.loo_max_m > gate_cfg.loo_factor * tolerance_m
    ) or holdout_max > gate_cfg.holdout_factor * tolerance_m
    if distribution_ok and affine_inadequate:
        escalated = _try_escalation(
            used_idx, holdout_idx, pixels, world, ids, factor, page_size_px, cfg, gate_cfg, tolerance_m
        )
        if escalated is not None:
            result, escalation_reason = escalated

    # --- 10. mark statuses + assemble --------------------------------------
    used_set = set(result.used_idx.tolist())
    outlier_idx = np.array(
        sorted(set(range(n_candidates)) - used_set - holdout_set), dtype=int
    )
    for i, c in enumerate(candidates):
        c.status = "used" if i in used_set else "held_out" if i in holdout_set else "ransac_outlier"
    for rec in result.residuals:
        by_id[rec.gcp_id].residual_m = rec.residual_m
    for rec in result.holdout_residuals:
        by_id[rec.gcp_id].residual_m = rec.residual_m
    if len(outlier_idx):
        _, _, omag = residuals_m(result.kind, result.params, pixels[outlier_idx], world[outlier_idx], factor)
        for j, i in enumerate(outlier_idx):
            by_id[ids[i]].residual_m = float(omag[j])

    if escalation_reason:
        notes.insert(0, escalation_reason)

    return SolveResult(
        transform_type=result.kind,
        params=result.params,
        target_crs=target_crs,
        n_candidates=n_candidates,
        n_inliers=len(result.used_idx),
        inlier_ids=[ids[i] for i in result.used_idx.tolist()],
        outlier_ids=[ids[i] for i in outlier_idx.tolist()],
        holdout_ids=[ids[i] for i in holdout_idx.tolist()],
        rmse_m=result.rmse_m,
        rmse_ft_us=result.rmse_m / _US_FOOT_M,
        loo_max_m=result.loo_max_m,
        loo_mean_m=result.loo_mean_m,
        residuals=result.residuals,
        holdout_residuals=result.holdout_residuals,
        distribution=result.distribution,
        error_budget=budget,
        escalation_reason="; ".join(notes) or None,
    )


def _select_holdout(inlier_idx: np.ndarray, pixels: np.ndarray, holdout_n: int) -> np.ndarray:
    """Deterministic farthest-point selection so the holdout spreads across the
    sheet (an independent check needs geometric spread, not a corner cluster).

    Cross-source/cross-tier preference (premortem #1) is a documented refinement
    for when multi-source candidates exist; single-source inputs are unaffected.
    """
    if holdout_n <= 0 or len(inlier_idx) == 0:
        return np.array([], dtype=int)
    k = min(holdout_n, len(inlier_idx))
    pts = pixels[inlier_idx]
    centroid = pts.mean(axis=0)
    start = int(np.argmin(np.hypot(pts[:, 0] - centroid[0], pts[:, 1] - centroid[1])))
    chosen = [start]
    while len(chosen) < k:
        dist = np.min(
            np.stack([np.hypot(pts[:, 0] - pts[c, 0], pts[:, 1] - pts[c, 1]) for c in chosen]),
            axis=0,
        )
        dist[chosen] = -1.0
        chosen.append(int(np.argmax(dist)))
    return inlier_idx[np.array(chosen, dtype=int)]


def _fit_and_validate(
    kind: TransformType,
    used_idx: np.ndarray,
    holdout_idx: np.ndarray,
    pixels: np.ndarray,
    world: np.ndarray,
    ids: list[str],
    factor: float,
    page_size_px: tuple[int, int],
) -> _Outcome:
    upx, uw = pixels[used_idx], world[used_idx]
    params = fit_transform(kind, upx, uw)
    dx, dy, mag = residuals_m(kind, params, upx, uw, factor)
    loo = loo_residuals(kind, upx, uw, factor)
    loo_max, loo_mean = loo_stats(loo)
    residuals = [
        ResidualRecord(
            gcp_id=ids[used_idx[i]],
            dx_m=float(dx[i]),
            dy_m=float(dy[i]),
            residual_m=float(mag[i]),
            loo_residual_m=None if not np.isfinite(loo[i]) else float(loo[i]),
        )
        for i in range(len(used_idx))
    ]
    dist = distribution_metrics(upx, page_size_px)
    hids = [ids[i] for i in holdout_idx.tolist()]
    holdout_recs = holdout_records(kind, params, hids, pixels[holdout_idx], world[holdout_idx], factor)
    return _Outcome(
        kind=kind,
        params=params,
        used_idx=used_idx,
        residuals=residuals,
        holdout_residuals=holdout_recs,
        distribution=dist,
        rmse_m=rmse(mag),
        loo_max_m=loo_max,
        loo_mean_m=loo_mean,
    )


def _try_escalation(
    used_idx: np.ndarray,
    holdout_idx: np.ndarray,
    pixels: np.ndarray,
    world: np.ndarray,
    ids: list[str],
    factor: float,
    page_size_px: tuple[int, int],
    cfg: SolverConfig,
    gate_cfg: GateConfig,
    tolerance_m: float,
) -> tuple[_Outcome, str] | None:
    """Try poly2 then tps; accept the first that clears cross-validation.

    Refuses to accept a family with NO cross-validation signal (LOO infeasible
    and no holdout) — an unchecked interpolant is exactly the overfit trap."""
    n_used = len(used_idx)
    families: list[TransformType] = []
    if cfg.allow_poly2 and n_used >= min_points("poly2"):
        families.append("poly2")
    if n_used >= cfg.tps_min_gcps:
        families.append("tps")
    for kind in families:
        out = _fit_and_validate(kind, used_idx, holdout_idx, pixels, world, ids, factor, page_size_px)
        has_cv = out.loo_max_m is not None or len(out.holdout_residuals) > 0
        loo_ok = out.loo_max_m is None or out.loo_max_m <= gate_cfg.loo_factor * tolerance_m
        hmax = max((r.residual_m for r in out.holdout_residuals), default=0.0)
        holdout_ok = hmax <= gate_cfg.holdout_factor * tolerance_m
        if has_cv and loo_ok and holdout_ok:
            return out, f"affine LOO/holdout exceeded tolerance; {kind} clears cross-validation"
    return None
