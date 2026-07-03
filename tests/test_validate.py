"""T3 (invariants) for validate: meters conversion, distribution guards, and
LOO-CV flagging an unstable point."""

import numpy as np
import pytest

from autogeo.solve.transforms import fit_affine
from autogeo.solve.validate import (
    distribution_metrics,
    linear_unit_to_m,
    loo_residuals,
    loo_stats,
    residuals_m,
    rmse,
)


def test_linear_unit_to_m():
    assert linear_unit_to_m("EPSG:2229") == pytest.approx(0.3048006096, abs=1e-9)
    assert linear_unit_to_m("EPSG:32611") == pytest.approx(1.0)  # UTM 11N, meters
    with pytest.raises(NotImplementedError):
        linear_unit_to_m("EPSG:4326")  # geographic degrees -> refuse, don't mis-scale


def test_distribution_spread_is_healthy():
    page = (1000, 1000)
    spread = np.array([[100, 100], [900, 100], [100, 900], [900, 900], [500, 500]], float)
    d = distribution_metrics(spread, page)
    assert d.quadrant_coverage == 4
    assert d.collinearity_ratio > 0.5
    assert d.hull_area_ratio > 0.3


def test_distribution_collinear_is_caught():
    page = (1000, 1000)
    collinear = np.array([[100, 100], [300, 300], [500, 500], [700, 700]], float)
    d = distribution_metrics(collinear, page)
    assert d.collinearity_ratio < 0.10  # below GateConfig.min_collinearity_ratio
    assert d.hull_area_ratio < 0.01


def test_loo_flags_high_leverage_point():
    # 8 points on an exact affine; perturb one point's world coord.
    px = np.array([[x, y] for x in (0.0, 100.0, 200.0, 300.0) for y in (0.0, 100.0)], float)
    world = np.column_stack(
        [2.0 * px[:, 0] + 3.0 * px[:, 1] + 1000.0, -px[:, 0] + 2.0 * px[:, 1] + 500.0]
    )
    world[3] += np.array([50.0, 0.0])  # one bad point
    loo = loo_residuals("affine", px, world, factor=1.0)
    _, _, mag = residuals_m("affine", fit_affine(px, world), px, world, factor=1.0)
    assert np.isfinite(loo).all()
    assert int(np.argmax(loo)) == 3
    assert loo[3] > mag[3]  # leave-one-out amplifies the in-fit residual


def test_loo_infeasible_returns_nan():
    px = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])  # exactly affine minimum
    loo = loo_residuals("affine", px, px, factor=1.0)
    assert np.isnan(loo).all()
    assert loo_stats(loo) == (None, None)


def test_rmse_zero_and_known():
    assert rmse(np.array([])) == 0.0
    assert rmse(np.array([3.0, 4.0])) == pytest.approx(np.sqrt(12.5))
