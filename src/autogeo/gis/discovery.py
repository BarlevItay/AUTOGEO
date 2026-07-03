"""ArcGIS catalog walker: root -> folders -> services -> layers -> LayerInfo.

Discovery is an *assistant*, not an authority: its output feeds
gis.doctrine.classify_layers, whose proposals a human promotes into the
curated registry. Municipal servers are half-broken — every node failure
(folder, service, layer) is caught, logged, and skipped; discovery must never
raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from autogeo.logging import get_logger

if TYPE_CHECKING:
    from autogeo.gis.rest_client import ArcGisClient

log = get_logger("gis.discovery")

_SERVICE_TYPES = ("MapServer", "FeatureServer")
_GEOMETRY_MAP = {
    "esriGeometryPoint": "point",
    "esriGeometryMultipoint": "point",
    "esriGeometryPolyline": "polyline",
    "esriGeometryPolygon": "polygon",
}


class LayerInfo(BaseModel):
    """Raw facts about one discovered layer — no doctrine judgment attached."""

    url: str  # service url (without the layer id)
    layer_id: int
    name: str
    description: str = ""
    geometry_type: str  # normalized: point | polyline | polygon
    fields: list[str] = Field(default_factory=list)
    max_record_count: int | None = None
    supports_pagination: bool = False
    wkid: int | None = None


def _list_services(root_url: str, client: ArcGisClient) -> list[dict]:
    """Root services plus one folder level deep (LA GeoHub nests exactly one)."""
    root_url = root_url.rstrip("/")
    catalog = client.get_json(root_url)
    services = list(catalog.get("services") or [])
    for folder in catalog.get("folders") or []:
        try:
            sub = client.get_json(f"{root_url}/{folder}")
            services.extend(sub.get("services") or [])
        except Exception as exc:
            log.warning("skipping folder %s/%s: %s", root_url, folder, exc)
    return services


def _layer_info(service_url: str, layer_id: int, name: str, client: ArcGisClient) -> LayerInfo | None:
    detail = client.get_json(f"{service_url}/{layer_id}")
    geometry = _GEOMETRY_MAP.get(detail.get("geometryType") or "")
    if geometry is None:
        log.debug("skipping %s/%s (%s): unusable geometry %r",
                  service_url, layer_id, name, detail.get("geometryType"))
        return None
    sr = detail.get("extent", {}).get("spatialReference") or detail.get("sourceSpatialReference") or {}
    return LayerInfo(
        url=service_url,
        layer_id=layer_id,
        name=detail.get("name") or name,
        description=detail.get("description") or "",
        geometry_type=geometry,
        fields=[f["name"] for f in detail.get("fields") or [] if "name" in f],
        max_record_count=detail.get("maxRecordCount"),
        supports_pagination=bool(
            (detail.get("advancedQueryCapabilities") or {}).get("supportsPagination")
        ),
        wkid=sr.get("wkid") or sr.get("latestWkid"),
    )


def discover(root_url: str, client: ArcGisClient, max_services: int) -> list[LayerInfo]:
    """Walk one REST root and return every queryable non-group layer found."""
    root_url = root_url.rstrip("/")
    try:
        services = _list_services(root_url, client)
    except Exception as exc:
        log.warning("discovery root %s unreachable: %s", root_url, exc)
        return []

    infos: list[LayerInfo] = []
    walked = 0
    for svc in services:
        if walked >= max_services:
            log.warning("discovery stopped at max_services=%d for %s", max_services, root_url)
            break
        svc_type = svc.get("type")
        if svc_type not in _SERVICE_TYPES:
            continue
        walked += 1
        # Folder services already carry "Folder/Name" in the name field.
        svc_url = f"{root_url}/{svc.get('name')}/{svc_type}"
        try:
            svc_json = client.get_json(svc_url)
        except Exception as exc:
            log.warning("skipping service %s: %s", svc_url, exc)
            continue
        for layer in svc_json.get("layers") or []:
            if layer.get("subLayerIds"):  # group layer: children are walked directly
                continue
            layer_id, layer_name = layer.get("id"), layer.get("name", "")
            try:
                info = _layer_info(svc_url, layer_id, layer_name, client)
            except Exception as exc:
                log.warning("skipping layer %s/%s: %s", svc_url, layer_id, exc)
                continue
            if info is not None:
                infos.append(info)
    log.info("discovered %d layers under %s (%d services walked)", len(infos), root_url, walked)
    return infos
