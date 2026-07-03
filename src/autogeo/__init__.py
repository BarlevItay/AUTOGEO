"""AUTOGEO — automatic georeferencing of as-built PDFs/TIFFs.

Pipeline spine: ingest+ocr+context -> DocumentContext -> gis -> ControlLayers
-> match tiers -> CandidateGCPs -> solve -> SolveResult -> gate -> GateDecision
-> output/assist -> GeorefReport. All contracts live in `autogeo.models`.
"""

__version__ = "0.1.0"
