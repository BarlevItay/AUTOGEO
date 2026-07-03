"""Low-level ArcGIS REST client over `requests`.

This module speaks only HTTP + the ArcGIS REST protocol: retries, backoff,
per-host politeness, pagination, and esri-JSON -> GeoJSON conversion. It knows
NOTHING about doctrine tiers, documents, or jurisdictions — callers pass fully
formed service URLs and layer ids (see gis.catalog for how those are chosen).

Municipal servers are half-broken by default: expect transient 5xx, HTML error
pages where JSON was promised, and `{"error": ...}` payloads with HTTP 200.
Transient transport/HTTP/JSON failures are retried with exponential backoff;
a well-formed `{"error": ...}` payload is a definitive server answer and
raises immediately.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import requests

from autogeo.logging import get_logger

if TYPE_CHECKING:
    from autogeo.config.schema import ArcgisConfig

log = get_logger("gis.rest_client")

# Page size requested per query; servers clamp to their own maxRecordCount and
# report exceededTransferLimit, which drives the pagination loop.
_PAGE_SIZE = 1000
_BACKOFF_BASE_S = 0.5


class ArcGisError(RuntimeError):
    """Raised when an ArcGIS endpoint fails: HTTP error after retries,
    non-JSON body, or an `{"error": ...}` payload."""


def _sr_wkid(sr: str | int) -> str:
    """Normalize an SR spec to a bare wkid string ("EPSG:2229" -> "2229")."""
    text = str(sr).strip()
    if ":" in text:
        text = text.rsplit(":", 1)[1]
    return text


def esri_feature_to_geojson(feature: dict) -> dict:
    """Convert one esri-JSON feature to a GeoJSON-like Feature dict.

    Handles the three geometry families we consume: points (x/y), polylines
    (paths), polygons (rings). Ring winding/hole semantics are passed through
    untouched — shapely downstream normalizes orientation.
    """
    geom = feature.get("geometry") or {}
    geometry: dict | None
    if "x" in geom:
        geometry = {"type": "Point", "coordinates": [geom["x"], geom["y"]]}
    elif "paths" in geom:
        paths = geom["paths"]
        if len(paths) == 1:
            geometry = {"type": "LineString", "coordinates": paths[0]}
        else:
            geometry = {"type": "MultiLineString", "coordinates": paths}
    elif "rings" in geom:
        geometry = {"type": "Polygon", "coordinates": geom["rings"]}
    else:
        geometry = None
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": dict(feature.get("attributes") or {}),
    }


class ArcGisClient:
    """Thin ArcGIS REST client. The injected `session` is the test seam and the
    hook for gis.cache.make_cached_session."""

    def __init__(self, arcgis_cfg: ArcgisConfig, session: requests.Session | None = None) -> None:
        self._cfg = arcgis_cfg
        self._session = session if session is not None else requests.Session()
        self._last_request_at: dict[str, float] = {}  # per-host politeness clock

    # ---- transport ------------------------------------------------------

    def _politeness_wait(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request_at.get(host)
        if last is not None:
            wait = self._cfg.politeness_delay_s - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request_at[host] = time.monotonic()

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict:
        """One logical request: politeness + retries + JSON + error-payload check."""
        last_exc: Exception | None = None
        for attempt in range(self._cfg.retries + 1):
            self._politeness_wait(url)
            try:
                resp = self._session.request(
                    method, url, params=params, data=data, timeout=self._cfg.timeout_s
                )
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if attempt < self._cfg.retries:
                    backoff = _BACKOFF_BASE_S * (2**attempt)
                    log.warning("retry %d/%d for %s in %.1fs: %s",
                                attempt + 1, self._cfg.retries, url, backoff, exc)
                    time.sleep(backoff)
                    continue
                raise ArcGisError(f"{method} {url} failed after "
                                  f"{self._cfg.retries + 1} attempts: {exc}") from exc
            if isinstance(payload, dict) and "error" in payload:
                # Definitive server answer — retrying an invalid request is noise.
                raise ArcGisError(f"{method} {url} returned error payload: {payload['error']}")
            return payload
        raise ArcGisError(f"{method} {url} failed: {last_exc}")  # pragma: no cover

    # ---- public API ------------------------------------------------------

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict:
        """GET a JSON resource (`f=json` unless the caller overrides it)."""
        merged = {"f": "json", **(params or {})}
        return self._request_json("GET", url, params=merged)

    def query_layer(
        self,
        service_url: str,
        layer_id: int,
        *,
        envelope_wgs84: tuple[float, float, float, float] | None = None,
        where: str | None = None,
        out_fields: str = "*",
        out_sr: str,
        count_only: bool = False,
    ) -> list[dict] | int:
        """POST a layer query, paginating until done or the feature cap.

        Requests `f=geojson` first; on server error (or an esri-JSON body from
        servers that silently ignore unsupported formats) falls back to
        `f=json` and converts features. Returns GeoJSON-like Feature dicts,
        or an int when `count_only`.
        """
        url = f"{service_url.rstrip('/')}/{layer_id}/query"
        base: dict[str, Any] = {
            "where": where or "1=1",
            "outFields": out_fields,
            "outSR": _sr_wkid(out_sr),
        }
        if envelope_wgs84 is not None:
            xmin, ymin, xmax, ymax = envelope_wgs84
            base.update({
                "geometry": json.dumps({
                    "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
                    "spatialReference": {"wkid": 4326},
                }),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            })

        if count_only:
            payload = self._request_json(
                "POST", url, data={**base, "returnCountOnly": "true", "f": "json"}
            )
            return int(payload["count"])

        features: list[dict] = []
        offset = 0
        fmt = "geojson"
        while True:
            page_size = min(_PAGE_SIZE, self._cfg.max_features_per_query - len(features))
            if page_size <= 0:
                log.warning("query %s hit max_features_per_query=%d cap",
                            url, self._cfg.max_features_per_query)
                break
            data = {**base, "f": fmt, "resultOffset": offset, "resultRecordCount": page_size}
            try:
                payload = self._request_json("POST", url, data=data)
            except ArcGisError:
                if fmt == "geojson":
                    log.info("geojson unsupported at %s; falling back to f=json", url)
                    fmt = "json"
                    continue
                raise
            page, exceeded = self._extract_features(payload)
            features.extend(page)
            if not exceeded or not page:
                break
            offset += len(page)
        return features

    @staticmethod
    def _extract_features(payload: dict) -> tuple[list[dict], bool]:
        """Pull (features, exceededTransferLimit) from either response dialect.

        Dispatch is structural, not on the requested format: some servers
        answer `f=geojson` with esri-JSON instead of an error.
        """
        if payload.get("type") == "FeatureCollection":
            exceeded = bool(
                payload.get("exceededTransferLimit")
                or (payload.get("properties") or {}).get("exceededTransferLimit")
            )
            return list(payload.get("features") or []), exceeded
        raw = payload.get("features") or []
        exceeded = bool(payload.get("exceededTransferLimit"))
        return [esri_feature_to_geojson(f) for f in raw], exceeded
