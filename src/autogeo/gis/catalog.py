"""The selection brain: which control layers to query, in what order.

Curated jurisdiction layers are the primary control path for v1; doctrine
tiers rank temporal stability, era bias reorders tiers (pre-1980 documents
prefer monuments over modern centerlines), and national baselines only fill
tiers the jurisdiction lacks. All knobs come from the Settings tree passed in
at construction — this module never loads config itself.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal

from autogeo.models.control import ControlLayer

if TYPE_CHECKING:
    from pathlib import Path

    from autogeo.config.schema import CuratedLayer, Settings

_ALL_TIERS = (1, 2, 3, 4, 5)
_LEVEL_RANK = {"city": 0, "county": 1, "state": 2, "national": 3}


def layer_key(service_url: str, layer_id: int) -> str:
    """Stable 12-hex key for a (service_url, layer_id) pair — the identity used
    by the feature cache and catalog persistence."""
    return hashlib.sha256(f"{service_url}#{layer_id}".encode()).hexdigest()[:12]


def curated_to_control(
    entry: CuratedLayer, source: Literal["jurisdiction", "baseline", "manual"]
) -> ControlLayer:
    """A hand-verified registry entry becomes a fully trusted ControlLayer
    (score 1.0 — curation is the trust ceiling)."""
    return ControlLayer(
        layer_key=layer_key(entry.service_url, entry.layer_id),
        service_url=entry.service_url,
        layer_id=entry.layer_id,
        name=entry.name,
        geometry_type=entry.geometry_type,
        doctrine_tier=entry.doctrine_tier,
        jurisdiction_level=entry.jurisdiction_level,
        source=source,
        label_fields=list(entry.label_fields),
        layer_crs=entry.layer_crs,
        positional_accuracy_m=entry.positional_accuracy_m,
        reliability_filter=entry.reliability_filter,
        score=1.0,
        notes=entry.notes,
    )


def save_layers(layers: list[ControlLayer], path: Path) -> None:
    """Persist a layer list as JSON (used by `catalog discover --save`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [layer.model_dump(mode="json") for layer in layers]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_layers(path: Path) -> list[ControlLayer]:
    return [
        ControlLayer.model_validate(obj)
        for obj in json.loads(path.read_text(encoding="utf-8"))
    ]


class Catalog:
    """Per-jurisdiction view over curated + baseline control layers."""

    def __init__(self, settings: Settings, jurisdiction_id: str) -> None:
        try:
            self.jurisdiction = settings.jurisdictions[jurisdiction_id]
        except KeyError:
            known = ", ".join(sorted(settings.jurisdictions)) or "<none>"
            raise ValueError(
                f"unknown jurisdiction {jurisdiction_id!r} (known: {known})"
            ) from None
        self.jurisdiction_id = jurisdiction_id
        self._doctrine = settings.doctrine
        self._jurisdiction_layers = [
            curated_to_control(entry, "jurisdiction") for entry in self.jurisdiction.layers
        ]
        self._baseline_layers = (
            [curated_to_control(entry, "baseline") for entry in settings.baselines.overrides]
            if settings.baselines.enabled
            else []
        )

    def all_layers(self) -> list[ControlLayer]:
        return [*self._jurisdiction_layers, *self._baseline_layers]

    def layers_for(self, era_year: int | None, state: str) -> list[ControlLayer]:
        """Ordered control layers for a document era in a given state.

        Jurisdiction layers come first, tiers in era order (pre-1980 prefers
        monuments; modern prefers centerlines), city < county < state <
        national within each tier. Baselines are appended only for tiers the
        jurisdiction cannot cover. `state_tier_availability` gates the
        jurisdiction side only (e.g. NY has no PLSS fabric, so tier 1 there
        can only come from national baseline marks).
        """
        pre1980 = era_year is not None and era_year < 1980
        order = self._doctrine.tier_order_pre1980 if pre1980 else self._doctrine.tier_order_modern
        allowed = set(self._doctrine.state_tier_availability.get(state, _ALL_TIERS))

        result: list[ControlLayer] = []
        covered: set[int] = set()
        for tier in order:
            if tier not in allowed:
                continue
            tier_layers = sorted(
                (l for l in self._jurisdiction_layers if l.doctrine_tier == tier),
                key=lambda l: _LEVEL_RANK[l.jurisdiction_level],
            )
            if tier_layers:
                covered.add(tier)
                result.extend(tier_layers)
        for tier in order:
            if tier in covered:
                continue
            result.extend(l for l in self._baseline_layers if l.doctrine_tier == tier)
        return result

    def save(self, path: Path) -> None:
        """Persist the catalog's full layer set as JSON (list[ControlLayer])."""
        save_layers(self.all_layers(), path)

    @staticmethod
    def load(path: Path) -> list[ControlLayer]:
        """Load a persisted layer list (inverse of save/save_layers)."""
        return load_layers(path)
