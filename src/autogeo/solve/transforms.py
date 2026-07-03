"""Transform fit/apply — the family-agnostic core of the solver.

Every fit is pixel->world: the canonical y-down pixel frame (300 DPI render) to
world CRS units. The affine path reuses the exact least-squares form the
synthetic generator's round-trip test certifies (tests/test_synth.py): design
matrix ``[px, py, 1]``, one solve for world_x, one for world_y. Affine therefore
recovers the injected similarity transform exactly (affine >= similarity), which
is why the T1 check hits < 0.01 ft.

``SolveResult.params`` is an untyped ``dict``; THIS module is the authoritative
schema for what goes in it per transform family. Downstream stages (RANSAC
refit, the GeoTIFF/worldfile writer) depend on these shapes:

- affine : ``{"a","b","c","d","e","f"}``
    world_x = a*px + b*py + c ; world_y = d*px + e*py + f
- poly2  : ``{"cx":[6], "cy":[6], "order":2}``
    design [px, py, px^2, px*py, py^2, 1]; two coefficient vectors
- tps    : ``{"control_px":[[x,y]...], "control_world":[[x,y]...],
             "smoothing":float, "kind":"tps"}``
    rebuilt on apply via scipy RBFInterpolator (thin-plate-spline kernel)
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import RBFInterpolator

from autogeo.models import TransformType

_TPS_KERNEL = "thin_plate_spline"

_MIN_POINTS: dict[str, int] = {"affine": 3, "poly2": 6, "tps": 3}


def min_points(kind: TransformType) -> int:
    """Mathematical minimum for an exact fit. tps policy floor (tps_min_gcps)
    is enforced separately by the solver."""
    try:
        return _MIN_POINTS[kind]
    except KeyError:
        raise ValueError(f"unknown transform type: {kind!r}")


def _as_xy(a) -> np.ndarray:
    arr = np.asarray(a, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"expected an [N,2] array, got shape {arr.shape}")
    return arr


# ---- affine ---------------------------------------------------------------


def fit_affine(pixels, world) -> dict:
    """Least-squares pixel->world affine. Needs >= 3 non-collinear points."""
    px = _as_xy(pixels)
    w = _as_xy(world)
    if len(px) < 3:
        raise ValueError(f"affine needs >= 3 points, got {len(px)}")
    design = np.column_stack([px[:, 0], px[:, 1], np.ones(len(px))])
    cx, *_ = np.linalg.lstsq(design, w[:, 0], rcond=None)
    cy, *_ = np.linalg.lstsq(design, w[:, 1], rcond=None)
    a, b, c = cx
    d, e, f = cy
    return {
        "a": float(a), "b": float(b), "c": float(c),
        "d": float(d), "e": float(e), "f": float(f),
    }


def apply_affine(params: dict, pixels) -> np.ndarray:
    px = _as_xy(pixels)
    wx = params["a"] * px[:, 0] + params["b"] * px[:, 1] + params["c"]
    wy = params["d"] * px[:, 0] + params["e"] * px[:, 1] + params["f"]
    return np.column_stack([wx, wy])


# ---- poly2 (2nd-order polynomial; scans only, still LOO-guarded) -----------


def _poly2_design(px: np.ndarray) -> np.ndarray:
    x, y = px[:, 0], px[:, 1]
    return np.column_stack([x, y, x * x, x * y, y * y, np.ones(len(px))])


def fit_poly2(pixels, world) -> dict:
    px = _as_xy(pixels)
    w = _as_xy(world)
    if len(px) < 6:
        raise ValueError(f"poly2 needs >= 6 points, got {len(px)}")
    design = _poly2_design(px)
    cx, *_ = np.linalg.lstsq(design, w[:, 0], rcond=None)
    cy, *_ = np.linalg.lstsq(design, w[:, 1], rcond=None)
    return {"cx": [float(v) for v in cx], "cy": [float(v) for v in cy], "order": 2}


def apply_poly2(params: dict, pixels) -> np.ndarray:
    px = _as_xy(pixels)
    design = _poly2_design(px)
    cx = np.asarray(params["cx"], dtype=float)
    cy = np.asarray(params["cy"], dtype=float)
    return np.column_stack([design @ cx, design @ cy])


# ---- tps (thin-plate spline; interpolating, escalation target) ------------


def fit_tps(pixels, world, smoothing: float = 0.0) -> dict:
    px = _as_xy(pixels)
    w = _as_xy(world)
    if len(px) < 3:
        raise ValueError(f"tps needs >= 3 points, got {len(px)}")
    # Build once to fail fast on a degenerate control set; store the control
    # arrays so apply can rebuild an identical interpolator (RBFInterpolator is
    # not directly serializable).
    RBFInterpolator(px, w, kernel=_TPS_KERNEL, smoothing=smoothing)
    return {
        "control_px": px.tolist(),
        "control_world": w.tolist(),
        "smoothing": float(smoothing),
        "kind": "tps",
    }


def apply_tps(params: dict, pixels) -> np.ndarray:
    control_px = _as_xy(params["control_px"])
    control_world = _as_xy(params["control_world"])
    rbf = RBFInterpolator(
        control_px, control_world,
        kernel=_TPS_KERNEL, smoothing=float(params.get("smoothing", 0.0)),
    )
    return rbf(_as_xy(pixels))


# ---- dispatchers ----------------------------------------------------------


def fit_transform(kind: TransformType, pixels, world, *, smoothing: float = 0.0) -> dict:
    if kind == "affine":
        return fit_affine(pixels, world)
    if kind == "poly2":
        return fit_poly2(pixels, world)
    if kind == "tps":
        return fit_tps(pixels, world, smoothing=smoothing)
    raise ValueError(f"unknown transform type: {kind!r}")


def apply_transform(kind: TransformType, params: dict, pixels) -> np.ndarray:
    if kind == "affine":
        return apply_affine(params, pixels)
    if kind == "poly2":
        return apply_poly2(params, pixels)
    if kind == "tps":
        return apply_tps(params, pixels)
    raise ValueError(f"unknown transform type: {kind!r}")
