"""Load packaged defaults, deep-merge the user YAML, apply env overrides."""

from __future__ import annotations

import hashlib
import json
import os
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from autogeo.config.schema import Settings

ENV_PREFIX = "AUTOGEO_"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursive dict merge; override wins. Lists replace wholesale (a curated
    layer list is a unit — merging entries item-wise would be a trap)."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _env_overrides() -> dict:
    """AUTOGEO_SECTION__KEY=value → {"section": {"key": parsed}} (nested via __)."""
    result: dict[str, Any] = {}
    for name, raw in os.environ.items():
        if not name.startswith(ENV_PREFIX):
            continue
        path = name[len(ENV_PREFIX):].lower().split("__")
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        node = result
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value
    return result


def load_defaults_dict() -> dict:
    text = resources.files("autogeo.config").joinpath("defaults.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def load_settings(config_path: Path | None = None) -> Settings:
    merged = load_defaults_dict()
    if config_path is not None:
        user = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        merged = _deep_merge(merged, user)
    env = _env_overrides()
    if env:
        merged = _deep_merge(merged, env)
    return Settings.model_validate(merged)


def config_hash(settings: Settings) -> str:
    """Stable short hash of the effective config — stamped into every report."""
    canonical = json.dumps(settings.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]
