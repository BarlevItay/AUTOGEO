"""Robust affine consensus — RANSAC with a meters-scaled inlier gate.

Hand-rolled rather than ``skimage.measure.ransac`` because the inlier threshold
is in meters (tied to the gate tolerance), while skimage's residuals come back
in world units with no clean unit hook. Reuses the shared ``fit_affine`` so the
whole solver stays on one fit path. Determinism comes from a caller-seeded
``np.random.Generator`` — same seed, same inlier mask.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from autogeo.solve.transforms import apply_affine, fit_affine


@dataclass
class RansacResult:
    params: dict
    inlier_mask: np.ndarray  # bool [N]
    n_trials: int


def _resid_mag_m(params: dict, px: np.ndarray, w: np.ndarray, factor: float) -> np.ndarray:
    resid = (w - apply_affine(params, px)) * factor
    return np.hypot(resid[:, 0], resid[:, 1])


def _normalized_triangle_area(p: np.ndarray) -> float:
    """Triangle area normalized by bounding-box area — a scale-free collinearity
    measure for rejecting degenerate 3-point samples."""
    (x0, y0), (x1, y1), (x2, y2) = p
    area = abs((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)) / 2.0
    bw = max(abs(x0 - x1), abs(x1 - x2), abs(x0 - x2))
    bh = max(abs(y0 - y1), abs(y1 - y2), abs(y0 - y2))
    bbox = bw * bh
    return area / bbox if bbox > 0 else 0.0


def ransac_affine(
    pixels,
    world,
    threshold_m: float,
    factor: float,
    *,
    rng: np.random.Generator,
    max_trials: int = 2000,
    min_samples: int = 3,
    min_sample_area: float = 0.02,
) -> RansacResult:
    """Find the affine transform with the largest meters-consistent inlier set."""
    px = np.asarray(pixels, dtype=float)
    w = np.asarray(world, dtype=float)
    n = len(px)
    if n < min_samples:
        raise ValueError(f"ransac needs >= {min_samples} points, got {n}")

    # Not enough points to sample a proper minimal set: fit all, gate by threshold.
    if n == min_samples:
        params = fit_affine(px, w)
        mask = _resid_mag_m(params, px, w, factor) <= threshold_m
        return RansacResult(params=params, inlier_mask=mask, n_trials=1)

    best_mask: np.ndarray | None = None
    best_count = -1
    best_resid = np.inf
    trials = 0
    for _ in range(max_trials):
        trials += 1
        sample = rng.choice(n, size=min_samples, replace=False)
        if _normalized_triangle_area(px[sample]) < min_sample_area:
            continue  # near-collinear sample -> unstable fit
        try:
            params = fit_affine(px[sample], w[sample])
        except Exception:
            continue
        mag = _resid_mag_m(params, px, w, factor)
        mask = mag <= threshold_m
        count = int(mask.sum())
        resid_sum = float(mag[mask].sum()) if count else np.inf
        if count > best_count or (count == best_count and resid_sum < best_resid):
            best_count, best_resid, best_mask = count, resid_sum, mask

    # No usable consensus: fall back to an all-points fit so the solver still
    # produces a result the gate can reject on RMSE / distribution.
    if best_mask is None or best_count < min_samples:
        params = fit_affine(px, w)
        return RansacResult(params=params, inlier_mask=np.ones(n, dtype=bool), n_trials=trials)

    # Refit on the best consensus set and recompute the mask on that refit — the
    # honest final least-squares fit over its own inliers.
    params = fit_affine(px[best_mask], w[best_mask])
    mask = _resid_mag_m(params, px, w, factor) <= threshold_m
    # A refit should not shrink consensus; if it does (rare, non-monotonic),
    # keep the sampling-consensus fit which is provably >= as large.
    if int(mask.sum()) < best_count:
        params = fit_affine(px[best_mask], w[best_mask])
        mask = best_mask
    return RansacResult(params=params, inlier_mask=mask, n_trials=trials)
