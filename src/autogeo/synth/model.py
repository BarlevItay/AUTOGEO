"""Contracts for the synthetic generator: the input feature set, the injected
transform, and the truth record written beside every rendered case."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RenderStyle = Literal["vector_clean", "scan_degraded"]


class SynthFeature(BaseModel):
    """One real-world GIS feature to draw. World coords in `world_crs`."""

    kind: Literal["centerline", "intersection", "monument", "parcel"]
    # polylines/polygons: list of (x, y) vertices; points: single-element list
    world_coords: list[tuple[float, float]]
    label: str | None = None  # street name, monument designation — drawn as text


class SynthFeatureSet(BaseModel):
    world_crs: str
    envelope_world: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax
    features: list[SynthFeature]


class AffineTruth(BaseModel):
    """The injected world->pixel transform, as `pixel = A @ world + t`.

    Stored so the harness can (a) score the pipeline's recovered transform and
    (b) render/measure ground-truth GCPs. A is row-major [[a, b], [d, e]].
    """

    a: float
    b: float
    d: float
    e: float
    tx: float
    ty: float

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.b * y + self.tx, self.d * x + self.e * y + self.ty)


class TruthGCP(BaseModel):
    pixel_x: float
    pixel_y: float
    world_x: float
    world_y: float
    label: str | None = None
    kind: str


class SynthTruth(BaseModel):
    """Everything needed to score a blind pipeline run against this case."""

    case_id: str
    style: RenderStyle
    world_crs: str
    page_size_px: tuple[int, int]
    dpi: int
    era_year: int
    scale_ratio: float  # ground ftUS per paper inch, e.g. 480 for 1"=40'
    transform: AffineTruth
    envelope_world: tuple[float, float, float, float]
    gcps: list[TruthGCP] = Field(default_factory=list)  # intersections/monuments as GT ties
    degradation: dict = Field(default_factory=dict)  # rotation_deg, noise, blur, warp params
    notes: str = ""
