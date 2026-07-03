"""Synthetic generator: transform math is exact, degradations behave, and the
truth GCPs recover the injected transform (generator round-trip sanity — the
foundation the whole label-free validation stands on)."""

import math

import numpy as np
import pytest

from autogeo.synth.generate import build_affine, render, save_case
from autogeo.synth.model import SynthFeature, SynthFeatureSet

# A small grid of "streets" in EPSG:2229 ftUS near downtown LA, with named
# intersections at the crossings — the minimal thing the matcher will consume.
ENV = (6_480_000.0, 1_840_000.0, 6_483_000.0, 1_842_000.0)


def make_feature_set() -> SynthFeatureSet:
    feats: list[SynthFeature] = []
    xs = [6_480_500, 6_481_500, 6_482_500]
    ys = [1_840_500, 1_841_000, 1_841_500]
    names_ns = ["MAIN ST", "SPRING ST", "HILL ST"]
    names_ew = ["1ST ST", "2ND ST", "3RD ST"]
    for x, nm in zip(xs, names_ns):
        feats.append(SynthFeature(kind="centerline",
                                  world_coords=[(x, ENV[1]), (x, ENV[3])], label=nm))
    for y, nm in zip(ys, names_ew):
        feats.append(SynthFeature(kind="centerline",
                                  world_coords=[(ENV[0], y), (ENV[2], y)], label=nm))
    for x, nx in zip(xs, names_ns):
        for y, ny in zip(ys, names_ew):
            feats.append(SynthFeature(kind="intersection", world_coords=[(x, y)],
                                      label=f"{nx} & {ny}"))
    feats.append(SynthFeature(kind="monument", world_coords=[(6_481_000, 1_840_200)],
                              label="BM 08-1234"))
    return SynthFeatureSet(world_crs="EPSG:2229", envelope_world=ENV, features=feats)


def test_build_affine_centers_and_flips_y():
    T = build_affine(ENV, (5100, 3300), rotation_deg=0)
    cx, cy = (ENV[0] + ENV[2]) / 2, (ENV[1] + ENV[3]) / 2
    px, py = T.world_to_pixel(cx, cy)
    assert px == pytest.approx(2550, abs=1)
    assert py == pytest.approx(1650, abs=1)
    # world-y up must become pixel-y down
    _, py_low = T.world_to_pixel(cx, ENV[1])
    _, py_high = T.world_to_pixel(cx, ENV[3])
    assert py_low > py_high


def test_render_clean_dimensions_and_gcps():
    fs = make_feature_set()
    T = build_affine(ENV, (5100, 3300))
    img, truth = render(fs, T, case_id="c1", style="vector_clean",
                        page_size_px=(5100, 3300), era_year=1995)
    assert img.size == (5100, 3300)
    assert len(truth.gcps) == 10  # 9 intersections + 1 monument
    assert truth.scale_ratio > 0


def test_scan_style_is_bilevel_matching_corpus():
    fs = make_feature_set()
    T = build_affine(ENV, (3400, 2200), rotation_deg=1.5)
    img, truth = render(fs, T, case_id="s1", style="scan_degraded",
                        page_size_px=(3400, 2200), era_year=1968,
                        seed=7, noise=0.05, blur=0.6)
    assert img.mode == "1"  # every real corpus TIFF is bilevel
    assert truth.degradation.get("bilevel") is True
    assert truth.era_year == 1968


def test_truth_gcps_recover_injected_affine():
    """The load-bearing sanity check: fitting pixel->world on the truth GCPs must
    recover the exact inverse of the injected transform. If this drifts, every
    downstream accuracy number built on synthetic cases is meaningless."""
    fs = make_feature_set()
    T = build_affine(ENV, (5100, 3300), rotation_deg=12.0)
    _, truth = render(fs, T, case_id="c2", style="vector_clean")
    # design matrix [px, py, 1] -> world x and y
    P = np.array([[g.pixel_x, g.pixel_y, 1.0] for g in truth.gcps])
    WX = np.array([g.world_x for g in truth.gcps])
    WY = np.array([g.world_y for g in truth.gcps])
    cx, *_ = np.linalg.lstsq(P, WX, rcond=None)
    cy, *_ = np.linalg.lstsq(P, WY, rcond=None)
    max_err_ft = 0.0
    for g in truth.gcps:
        row = np.array([g.pixel_x, g.pixel_y, 1.0])
        rx, ry = cx @ row, cy @ row
        max_err_ft = max(max_err_ft, math.hypot(rx - g.world_x, ry - g.world_y))
    # sub-0.01 ft: the injected transform is exactly affine, lstsq must nail it
    assert max_err_ft < 0.01, f"round-trip error {max_err_ft:.4f} ft"


def test_warp_moves_gcps_but_keeps_them_truth():
    fs = make_feature_set()
    T = build_affine(ENV, (3400, 2200))
    _, clean = render(fs, T, case_id="w0", style="vector_clean", page_size_px=(3400, 2200))
    _, warped = render(fs, T, case_id="w1", style="scan_degraded", page_size_px=(3400, 2200),
                       seed=3, warp_amp_px=12.0, warp_periods=2.0)
    assert warped.degradation.get("warp_amp_px") == 12.0
    # at least one GCP shifted relative to the un-warped render
    shifts = [math.hypot(w.pixel_x - c.pixel_x, w.pixel_y - c.pixel_y)
              for w, c in zip(warped.gcps, clean.gcps)]
    assert max(shifts) > 1.0


def test_save_case_writes_files(tmp_path):
    fs = make_feature_set()
    T = build_affine(ENV, (2000, 1400))
    img, truth = render(fs, T, case_id="save1", style="vector_clean", page_size_px=(2000, 1400))
    case_dir = save_case(img, truth, tmp_path)
    assert (case_dir / "save1.tif").exists()
    assert (case_dir / "truth.json").exists()
    from autogeo.synth.model import SynthTruth
    reloaded = SynthTruth.model_validate_json((case_dir / "truth.json").read_text())
    assert reloaded == truth
