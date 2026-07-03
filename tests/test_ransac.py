"""T3 (invariants) for RANSAC: gross outliers are rejected, degenerate samples
are skipped, and the same seed yields the same inlier mask."""

import numpy as np

from autogeo.solve.ransac import _normalized_triangle_area, ransac_affine

FACTOR = 0.3048006096  # EPSG:2229 ftUS -> m


def _pix_world(truth):
    px = np.array([[g.pixel_x, g.pixel_y] for g in truth.gcps], dtype=float)
    w = np.array([[g.world_x, g.world_y] for g in truth.gcps], dtype=float)
    return px, w


def test_rejects_gross_outliers(render_truth):
    truth = render_truth(rotation_deg=4.0)
    px, w = _pix_world(truth)
    w_corrupt = w.copy()
    outliers = [2, 6]
    w_corrupt[outliers] += 400.0  # ~122 m off the true world position
    rr = ransac_affine(px, w_corrupt, threshold_m=2.0, factor=FACTOR, rng=np.random.default_rng(0))
    assert not rr.inlier_mask[outliers].any()
    assert int(rr.inlier_mask.sum()) == len(truth.gcps) - len(outliers)


def test_determinism_same_seed(render_truth):
    truth = render_truth()
    px, w = _pix_world(truth)
    w[3] += 500.0
    m1 = ransac_affine(px, w, 2.0, FACTOR, rng=np.random.default_rng(42)).inlier_mask
    m2 = ransac_affine(px, w, 2.0, FACTOR, rng=np.random.default_rng(42)).inlier_mask
    assert np.array_equal(m1, m2)


def test_clean_data_keeps_all_inliers(render_truth):
    truth = render_truth(rotation_deg=8.0)
    px, w = _pix_world(truth)
    rr = ransac_affine(px, w, 1.0, FACTOR, rng=np.random.default_rng(1))
    assert rr.inlier_mask.all()


def test_normalized_triangle_area_flags_collinear():
    collinear = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    assert _normalized_triangle_area(collinear) < 1e-9
    spread = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
    assert _normalized_triangle_area(spread) > 0.4
