"""Error-budget invariants: the gate can never demand better than physics allows."""

import math

import pytest

from autogeo.models.control import ControlLayer
from autogeo.solve.budget import (
    UNKNOWN_CONTROL_ACCURACY_M,
    compute_error_budget,
    gate_threshold_m,
    scan_resolution_m,
)


def layer(accuracy: float | None, tier: int = 2) -> ControlLayer:
    return ControlLayer(
        layer_key="k", service_url="https://x", layer_id=0, name="L",
        geometry_type="polyline", doctrine_tier=tier, source="jurisdiction",
        positional_accuracy_m=accuracy,
    )


def test_worst_layer_bounds_the_budget():
    budget = compute_error_budget([layer(0.5), layer(2.0)], False, 300, None)
    assert budget.control_accuracy_m == 2.0
    assert budget.achievable_rmse_m == pytest.approx(2.0)


def test_unknown_accuracy_is_conservative_not_optimistic():
    budget = compute_error_budget([layer(None)], False, 300, None)
    assert budget.control_accuracy_m == UNKNOWN_CONTROL_ACCURACY_M


def test_datum_and_pixel_terms_combine_rss():
    budget = compute_error_budget([layer(1.0)], True, 300, 480, datum_uncertainty_m=0.15)
    pixel = scan_resolution_m(300, 480)
    assert pixel == pytest.approx(480 / 300 * 0.0254)  # 1"=40' at 300dpi ~ 4 cm
    assert budget.achievable_rmse_m == pytest.approx(
        math.sqrt(1.0**2 + 0.15**2 + pixel**2)
    )


def test_unknown_scale_contributes_zero():
    assert scan_resolution_m(300, None) == 0.0
    assert scan_resolution_m(300, 0) == 0.0


def test_gate_threshold_never_stricter_than_physics():
    budget = compute_error_budget([layer(2.0)], False, 300, None)
    # era band says 0.5 m but control is 2 m: threshold must relax to the budget
    assert gate_threshold_m(0.5, budget, budget_factor=1.0) == pytest.approx(2.0)
    # tight budget leaves the era band in charge
    tight = compute_error_budget([layer(0.1)], False, 300, None)
    assert gate_threshold_m(0.5, tight, budget_factor=1.0) == 0.5


def test_1965_scan_scenario():
    """A pre-1980 scan on 2 m centerline control with a NAD27 shift: the honest
    floor is ~2 m — reporting 0.5 m RMSE as 'accuracy' would be a lie."""
    budget = compute_error_budget([layer(2.0), layer(0.5, tier=1)], True, 300, 600)
    assert budget.achievable_rmse_m > 2.0
    assert gate_threshold_m(1.5, budget, 1.0) == pytest.approx(budget.achievable_rmse_m)
