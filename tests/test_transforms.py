"""T1 (ground truth) for the transform fits: recover the injected transform from
the synthetic generator's truth GCPs, and confirm poly2/tps behave."""

import numpy as np
import pytest

from autogeo.solve.transforms import (
    apply_affine,
    apply_poly2,
    apply_tps,
    fit_affine,
    fit_poly2,
    fit_transform,
    fit_tps,
    min_points,
)


def _pix_world(truth):
    px = np.array([[g.pixel_x, g.pixel_y] for g in truth.gcps], dtype=float)
    w = np.array([[g.world_x, g.world_y] for g in truth.gcps], dtype=float)
    return px, w


def _max_err_ft(pred, w):
    return float(np.max(np.hypot(pred[:, 0] - w[:, 0], pred[:, 1] - w[:, 1])))


def test_fit_affine_recovers_injected_transform(render_truth):
    """The load-bearing T1 check: fitting pixel->world on the truth GCPs of a
    rotated case recovers the injected transform to < 0.01 ft."""
    truth = render_truth(rotation_deg=12.0)
    px, w = _pix_world(truth)
    params = fit_affine(px, w)
    assert set(params) == {"a", "b", "c", "d", "e", "f"}
    assert _max_err_ft(apply_affine(params, px), w) < 0.01


def test_apply_fit_roundtrip(render_truth):
    truth = render_truth(rotation_deg=3.0)
    px, w = _pix_world(truth)
    params = fit_affine(px, w)
    assert np.allclose(apply_affine(params, px), w, atol=0.01)


def test_fit_poly2_reduces_to_affine_on_affine_data(render_truth):
    """poly2 must not inject curvature on exact-affine input."""
    truth = render_truth(rotation_deg=7.0)
    px, w = _pix_world(truth)
    params = fit_poly2(px, w)
    assert _max_err_ft(apply_poly2(params, px), w) < 0.1


def test_fit_tps_interpolates_control(render_truth):
    """Interpolating TPS (smoothing=0) reproduces its control points."""
    truth = render_truth()
    px, w = _pix_world(truth)
    params = fit_tps(px, w)
    assert params["kind"] == "tps"
    assert np.allclose(apply_tps(params, px), w, atol=0.05)


def test_min_points_and_dispatcher(render_truth):
    assert (min_points("affine"), min_points("poly2"), min_points("tps")) == (3, 6, 3)
    with pytest.raises(ValueError):
        min_points("nope")
    truth = render_truth()
    px, w = _pix_world(truth)
    assert set(fit_transform("affine", px, w)) == {"a", "b", "c", "d", "e", "f"}
    with pytest.raises(ValueError):
        fit_transform("bogus", px, w)


def test_fit_affine_rejects_too_few_points():
    two = np.array([[0.0, 0.0], [1.0, 1.0]])
    with pytest.raises(ValueError):
        fit_affine(two, two)
