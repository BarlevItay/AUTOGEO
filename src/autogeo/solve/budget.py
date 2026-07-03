"""Error-budget model: the honest floor on achievable accuracy.

RMSE against control can never legitimately beat the control's own absolute
accuracy, the datum-shift uncertainty, or the ground size of a scan pixel.
The gate compares solve RMSE against max(era threshold, budgeted floor) and
itemizes the budget in the report — "consistent with control accuracy", not
a fabricated half-meter claim against two-meter centerlines.
"""

from __future__ import annotations

import math

from autogeo.models.control import ControlLayer
from autogeo.models.solve import ErrorBudget

# NADCON NAD27->NAD83 uncertainty: ~0.15 m (67%) in CONUS, up to ~1.0 m in
# sparse-data areas. LA is data-dense; callers may override for rural docs.
DATUM_SHIFT_UNCERTAINTY_M = 0.15
# Discovered layers with unknown accuracy get a conservative default.
UNKNOWN_CONTROL_ACCURACY_M = 5.0

_INCH_M = 0.0254


def scan_resolution_m(dpi: int, scale_ratio: float | None) -> float:
    """Ground size of one pixel: (scale_ratio / dpi) inches on the ground.

    scale_ratio is drawing scale as ground-units-per-paper-unit (1"=40'
    -> 480). Unknown scale contributes 0 — the budget must not inflate on
    missing metadata; the gate handles low-confidence scale elsewhere.
    """
    if not scale_ratio or dpi <= 0:
        return 0.0
    return (scale_ratio / dpi) * _INCH_M


def compute_error_budget(
    layers_used: list[ControlLayer],
    datum_shift_applied: bool,
    dpi: int,
    scale_ratio: float | None,
    datum_uncertainty_m: float = DATUM_SHIFT_UNCERTAINTY_M,
) -> ErrorBudget:
    """Root-sum-square of the independent error sources for a solve."""
    accuracies = [
        layer.positional_accuracy_m
        if layer.positional_accuracy_m is not None
        else UNKNOWN_CONTROL_ACCURACY_M
        for layer in layers_used
    ]
    # Worst layer bounds the solve: mixed-tier GCP sets inherit the weakest
    # control actually used, not an optimistic average.
    control = max(accuracies) if accuracies else UNKNOWN_CONTROL_ACCURACY_M
    datum = datum_uncertainty_m if datum_shift_applied else 0.0
    pixel = scan_resolution_m(dpi, scale_ratio)
    return ErrorBudget(
        control_accuracy_m=control,
        datum_uncertainty_m=datum,
        scan_resolution_m=pixel,
        achievable_rmse_m=math.sqrt(control**2 + datum**2 + pixel**2),
    )


def gate_threshold_m(era_band_max_m: float, budget: ErrorBudget, budget_factor: float) -> float:
    """The threshold the gate actually applies: never stricter than physics."""
    return max(era_band_max_m, budget_factor * budget.achievable_rmse_m)
