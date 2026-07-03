"""National baseline control layers (BLM PLSS, NGS, TIGERweb, NHD).

Trivial by design: baselines are curated entries in config, converted here so
the "baseline" trust label is assigned in exactly one place. Queried only when
the jurisdiction lacks a tier (gis.catalog decides that).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autogeo.gis.catalog import curated_to_control

if TYPE_CHECKING:
    from autogeo.config.schema import BaselinesConfig
    from autogeo.models.control import ControlLayer


def baseline_layers(baselines_cfg: BaselinesConfig) -> list[ControlLayer]:
    """Convert configured baseline overrides to ControlLayers (source="baseline")."""
    if not baselines_cfg.enabled:
        return []
    return [curated_to_control(entry, "baseline") for entry in baselines_cfg.overrides]
