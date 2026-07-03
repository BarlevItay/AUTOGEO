"""Two cache levels for GIS traffic.

1. HTTP level: a requests-cache CachedSession (sqlite) injected into
   ArcGisClient — makes discovery walks and catalog reruns cheap and polite.
2. Feature level: query results as plain JSON files with a sidecar meta,
   keyed by (layer, envelope, where, out_sr). JSON, not GPKG, on purpose:
   the cache layer stays free of the geopandas dependency; conversion to
   GeoDataFrames happens downstream in the match stage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import requests_cache

from autogeo.logging import get_logger

if TYPE_CHECKING:
    from autogeo.config.schema import CacheConfig
    from autogeo.gis.rest_client import ArcGisClient
    from autogeo.models.control import ControlLayer

log = get_logger("gis.cache")


def make_cached_session(cache_cfg: CacheConfig) -> requests_cache.CachedSession:
    """Sqlite-backed HTTP cache. POST is allowable because ArcGIS queries go
    over POST — the request body is part of the cache key."""
    cache_cfg.dir.mkdir(parents=True, exist_ok=True)
    return requests_cache.CachedSession(
        cache_name=str(cache_cfg.dir / "http_cache"),
        backend="sqlite",
        expire_after=timedelta(days=cache_cfg.catalog_ttl_days),
        allowable_methods=("GET", "POST"),
    )


def _feature_key(
    layer: ControlLayer,
    envelope_wgs84: tuple[float, float, float, float] | None,
    where: str | None,
    out_sr: str,
) -> str:
    raw = layer.layer_key + repr(envelope_wgs84) + (where or "") + out_sr
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cached_query(
    client: ArcGisClient,
    layer: ControlLayer,
    envelope_wgs84: tuple[float, float, float, float] | None,
    out_sr: str,
    cache_cfg: CacheConfig,
    where: str | None = None,
) -> list[dict]:
    """Query a control layer through the feature cache.

    Cache layout: <cache.dir>/features/<layer_key>/<key>.json plus
    <key>.meta.json (fetched_at ISO, where, envelope) so staleness is
    inspectable and rewritable without touching the payload.
    """
    key = _feature_key(layer, envelope_wgs84, where, out_sr)
    feature_dir = cache_cfg.dir / "features" / layer.layer_key
    data_path = feature_dir / f"{key}.json"
    meta_path = feature_dir / f"{key}.meta.json"

    if data_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(meta["fetched_at"])
            age = datetime.now(timezone.utc) - fetched_at
            if age < timedelta(days=cache_cfg.feature_ttl_days):
                features = json.loads(data_path.read_text(encoding="utf-8"))
                log.info("features from_cache layer=%s key=%s n=%d age_days=%.1f",
                         layer.layer_key, key, len(features), age.total_seconds() / 86400)
                return features
            log.debug("feature cache expired for layer=%s key=%s", layer.layer_key, key)
        except (ValueError, KeyError) as exc:  # corrupt entry -> refetch
            log.warning("unreadable feature cache entry %s: %s", meta_path, exc)

    features = client.query_layer(
        layer.service_url,
        layer.layer_id,
        envelope_wgs84=envelope_wgs84,
        where=where,
        out_sr=out_sr,
    )
    feature_dir.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(features), encoding="utf-8")
    meta_path.write_text(
        json.dumps({
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "where": where,
            "envelope": list(envelope_wgs84) if envelope_wgs84 is not None else None,
            "out_sr": out_sr,
        }),
        encoding="utf-8",
    )
    log.info("features fetched layer=%s key=%s n=%d", layer.layer_key, key, len(features))
    return features
