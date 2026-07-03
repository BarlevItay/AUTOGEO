"""Doctrine classification: score discovered layers into control tiers.

Scoring is deliberately dumb and inspectable: keyword regex hits on
name+description, label-field regex hits on the schema, and a hard geometry
gate (a polygon named "monuments" is an index grid, not monuments). Output is
PROPOSALS — a human promotes survivors into the curated registry; nothing here
is auto-trusted.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from autogeo.gis.catalog import layer_key
from autogeo.logging import get_logger
from autogeo.models.control import ControlLayer

if TYPE_CHECKING:
    from autogeo.config.schema import DoctrineConfig
    from autogeo.gis.discovery import LayerInfo

log = get_logger("gis.doctrine")

# Geometry each tier's control is expected to be; tier 3 (hydro/structures)
# is legitimately mixed, so it carries no gate.
_EXPECTED_GEOMETRY = {1: "point", 2: "polyline", 4: "polygon", 5: "polygon"}
_GEOMETRY_MISMATCH_PENALTY = 3.0


def _tier_number(tier_name: str) -> int:
    return int(tier_name.removeprefix("tier"))


def _score_tier(
    info: LayerInfo, tier_name: str, doctrine_cfg: DoctrineConfig
) -> tuple[float, list[str], list[str]]:
    """Return (score, matched_keywords, label_fields) for one candidate tier."""
    text = f"{info.name} {info.description}"
    matched = [
        pattern
        for pattern in doctrine_cfg.keyword_map.get(tier_name, [])
        if re.search(pattern, text, re.IGNORECASE)
    ]
    score = float(len(matched))

    label_fields: list[str] = []
    for pattern in doctrine_cfg.label_field_map.get(tier_name, []):
        hits = [f for f in info.fields if re.search(pattern, f, re.IGNORECASE)]
        if hits:
            score += 1.0
            label_fields.extend(h for h in hits if h not in label_fields)

    expected = _EXPECTED_GEOMETRY.get(_tier_number(tier_name))
    if expected is not None and info.geometry_type != expected:
        score -= _GEOMETRY_MISMATCH_PENALTY
    return score, matched, label_fields


def classify_layers(infos: list[LayerInfo], doctrine_cfg: DoctrineConfig) -> list[ControlLayer]:
    """Classify each layer into its best tier; drop everything below min_score."""
    proposals: list[ControlLayer] = []
    for info in infos:
        best: tuple[float, str, list[str], list[str]] | None = None
        for tier_name in doctrine_cfg.keyword_map:
            score, matched, label_fields = _score_tier(info, tier_name, doctrine_cfg)
            if best is None or score > best[0]:
                best = (score, tier_name, matched, label_fields)
        if best is None or best[0] < doctrine_cfg.min_score:
            continue
        score, tier_name, matched, label_fields = best
        proposals.append(
            ControlLayer(
                layer_key=layer_key(info.url, info.layer_id),
                service_url=info.url,
                layer_id=info.layer_id,
                name=info.name,
                geometry_type=info.geometry_type,  # type: ignore[arg-type]  # discovery normalizes
                doctrine_tier=_tier_number(tier_name),
                source="jurisdiction",
                label_fields=label_fields,
                score=score,
                matched_keywords=matched,
                positional_accuracy_m=None,  # unknown until verified by a human
            )
        )
        log.debug("classified %s/%s as %s (score=%.1f)",
                  info.url, info.layer_id, tier_name, score)
    return proposals
