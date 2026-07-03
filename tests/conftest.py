"""Shared fixtures for the solver-core tests.

Reuses the synthetic generator (the label-free ground truth) to render cases and
convert their truth GCPs into CandidateGCPs — the solver's input currency.
"""

from __future__ import annotations

import pytest

from autogeo.config.schema import GateConfig, SolverConfig
from autogeo.models import CandidateGCP, GCPProvenance
from autogeo.models.control import ControlLayer
from autogeo.synth.generate import build_affine, render
from autogeo.synth.model import SynthFeature, SynthFeatureSet, SynthTruth

# A small grid of streets in EPSG:2229 ftUS near downtown LA, named intersections
# at the crossings + one monument — mirrors tests/test_synth.py.
ENV = (6_480_000.0, 1_840_000.0, 6_483_000.0, 1_842_000.0)


def _feature_set(grid: tuple[int, int] = (3, 3)) -> SynthFeatureSet:
    """A `grid` = (n_ns, n_ew) network of streets with a named intersection at
    every crossing (n_ns*n_ew GCPs) plus one monument. Denser grids give
    escalation (poly2/tps) real redundancy."""
    n_ns, n_ew = grid
    feats: list[SynthFeature] = []
    x0, y0, x1, y1 = ENV
    xs = [x0 + (x1 - x0) * (i + 1) / (n_ns + 1) for i in range(n_ns)]
    ys = [y0 + (y1 - y0) * (j + 1) / (n_ew + 1) for j in range(n_ew)]
    for i, x in enumerate(xs):
        feats.append(SynthFeature(kind="centerline", world_coords=[(x, ENV[1]), (x, ENV[3])], label=f"{i}-AVE"))
    for j, y in enumerate(ys):
        feats.append(SynthFeature(kind="centerline", world_coords=[(ENV[0], y), (ENV[2], y)], label=f"{j}-ST"))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            feats.append(SynthFeature(kind="intersection", world_coords=[(x, y)], label=f"{i}-AVE & {j}-ST"))
    feats.append(SynthFeature(kind="monument", world_coords=[(6_481_000, 1_840_200)], label="BM 08-1234"))
    return SynthFeatureSet(world_crs="EPSG:2229", envelope_world=ENV, features=feats)


def _render_truth(
    style: str = "vector_clean",
    *,
    rotation_deg: float = 0.0,
    page_size_px: tuple[int, int] = (5100, 3300),
    grid: tuple[int, int] = (3, 3),
    **render_kw,
) -> SynthTruth:
    fs = _feature_set(grid)
    T = build_affine(ENV, page_size_px, rotation_deg=rotation_deg)
    _, truth = render(
        fs, T, case_id="case", style=style, page_size_px=page_size_px,
        rotation_deg=rotation_deg, **render_kw,
    )
    return truth


def _candidates_from_truth(truth: SynthTruth, world_crs: str = "EPSG:2229") -> list[CandidateGCP]:
    return [
        CandidateGCP(
            gcp_id=f"t1-{i:04d}",
            pixel_x=g.pixel_x, pixel_y=g.pixel_y,
            world_x=g.world_x, world_y=g.world_y, world_crs=world_crs,
            source_tier=1, doctrine_tier=2, confidence=0.9,
            provenance=GCPProvenance(method="tier1_intersection", matched_label=g.label),
        )
        for i, g in enumerate(truth.gcps)
    ]


def _street_layer(accuracy_m: float | None = 1.0) -> ControlLayer:
    return ControlLayer(
        layer_key="centerlines", service_url="https://x/FeatureServer", layer_id=0,
        name="Street Centerlines", geometry_type="polyline", doctrine_tier=2,
        jurisdiction_level="city", source="jurisdiction", positional_accuracy_m=accuracy_m,
    )


@pytest.fixture
def render_truth():
    return _render_truth


@pytest.fixture
def candidates_from_truth():
    return _candidates_from_truth


@pytest.fixture
def street_layer():
    return _street_layer


@pytest.fixture
def solver_cfg() -> SolverConfig:
    return SolverConfig()


@pytest.fixture
def gate_cfg() -> GateConfig:
    return GateConfig()
