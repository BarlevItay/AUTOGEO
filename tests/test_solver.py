"""T2 (independent cross-check vs rasterio/GDAL) + end-to-end solver behavior:
clean recovery, outlier rejection, and warp escalation."""

import numpy as np
import pytest
from rasterio.control import GroundControlPoint
from rasterio.transform import from_gcps

from autogeo.solve.solver import solve
from autogeo.solve.transforms import apply_affine, fit_affine

FACTOR = 0.3048006096


def _pix_world(truth):
    px = np.array([[g.pixel_x, g.pixel_y] for g in truth.gcps], dtype=float)
    w = np.array([[g.world_x, g.world_y] for g in truth.gcps], dtype=float)
    return px, w


def _solve(truth, cands, solver_cfg, gate_cfg, street_layer, **kw):
    defaults = dict(
        target_crs="EPSG:2229",
        cfg=solver_cfg,
        gate_cfg=gate_cfg,
        page_size_px=truth.page_size_px,
        dpi=truth.dpi,
        scale_ratio=truth.scale_ratio,
        layers_used=[street_layer()],
        datum_shift_applied=False,
        era_band_max_m=0.5,
        rng_seed=0,
    )
    defaults.update(kw)
    return solve(cands, **defaults)


def test_fit_agrees_with_rasterio(render_truth):
    """T2: our least-squares affine agrees with rasterio's from_gcps (GDAL's
    independent GCPToGeoTransform) to sub-millimeter at the page corners."""
    truth = render_truth(rotation_deg=9.0)
    px, w = _pix_world(truth)
    params = fit_affine(px, w)
    gcps = [
        GroundControlPoint(row=float(p[1]), col=float(p[0]), x=float(wi[0]), y=float(wi[1]))
        for p, wi in zip(px, w)
    ]
    aff = from_gcps(gcps)  # rasterio Affine: (x, y) = aff * (col, row)
    pw, ph = truth.page_size_px
    corners = np.array([[0, 0], [pw, 0], [0, ph], [pw, ph]], float)
    ours = apply_affine(params, corners)
    theirs = np.array([aff * (c[0], c[1]) for c in corners])
    max_dev_m = float(np.max(np.hypot(ours[:, 0] - theirs[:, 0], ours[:, 1] - theirs[:, 1]))) * FACTOR
    assert max_dev_m < 1e-3


def test_solve_clean_synth(render_truth, candidates_from_truth, street_layer, solver_cfg, gate_cfg):
    truth = render_truth(rotation_deg=5.0)
    cands = candidates_from_truth(truth)
    res = _solve(truth, cands, solver_cfg, gate_cfg, street_layer)

    assert res.transform_type == "affine"
    assert res.escalation_reason is None
    assert res.rmse_m < 0.05
    assert res.error_budget is not None
    # three disjoint id lists partition the candidates; clean data -> no outliers
    assert res.n_inliers + len(res.holdout_ids) == res.n_candidates
    assert len(res.outlier_ids) == 0
    assert len(res.holdout_ids) == solver_cfg.holdout_n
    # ftUS mirror is a pure unit conversion of the meters RMSE
    assert res.rmse_ft_us * FACTOR == pytest.approx(res.rmse_m, rel=1e-9)
    # held-out points are genuinely independent yet still land well
    assert max((r.residual_m for r in res.holdout_residuals), default=0.0) < 0.5
    # statuses + residuals written back onto the candidates
    assert {c.status for c in cands} == {"used", "held_out"}
    assert all(c.residual_m is not None for c in cands)


def test_solve_rejects_gross_outlier(render_truth, candidates_from_truth, street_layer, solver_cfg, gate_cfg):
    truth = render_truth(rotation_deg=2.0)
    cands = candidates_from_truth(truth)
    cands[4].world_x += 400.0  # ~122 m wrong match
    cands[4].world_y -= 400.0
    res = _solve(truth, cands, solver_cfg, gate_cfg, street_layer)

    assert "t1-0004" in res.outlier_ids
    assert cands[4].status == "ransac_outlier"
    assert res.transform_type == "affine"
    assert res.rmse_m < 0.05  # the fit itself is unpolluted by the rejected point


def test_solve_warp_escalates(render_truth, candidates_from_truth, street_layer, solver_cfg, gate_cfg):
    """A smooth scan warp breaks affine (elevated LOO) with healthy geometry ->
    the solver escalates to a higher-order family that clears cross-validation."""
    truth = render_truth(style="scan_degraded", grid=(5, 5), warp_amp_px=15.0, warp_periods=1.0, seed=1)
    cands = candidates_from_truth(truth)
    res = _solve(truth, cands, solver_cfg, gate_cfg, street_layer, era_band_max_m=1.0)

    assert res.escalation_reason is not None
    assert res.transform_type in ("poly2", "tps")
    assert len(res.outlier_ids) == 0  # warp is not gross outliers


def test_solve_rejects_crs_mismatch(render_truth, candidates_from_truth, street_layer, solver_cfg, gate_cfg):
    truth = render_truth()
    cands = candidates_from_truth(truth, world_crs="EPSG:2226")  # wrong SPCS zone
    with pytest.raises(ValueError, match="pre-projected"):
        _solve(truth, cands, solver_cfg, gate_cfg, street_layer)
