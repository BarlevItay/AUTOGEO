"""GIS layer: REST client behavior, discovery resilience, doctrine scoring,
catalog ordering, and the feature cache. HTTP is mocked with `responses`
except the single `live`-marked smoke test (deselected by default)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import pytest
import requests_cache
import responses

from autogeo.config.loader import load_settings
from autogeo.config.schema import ArcgisConfig, CacheConfig, CuratedLayer, JurisdictionConfig
from autogeo.gis.baselines import baseline_layers
from autogeo.gis.cache import cached_query, make_cached_session
from autogeo.gis.catalog import Catalog, curated_to_control, layer_key, load_layers, save_layers
from autogeo.gis.discovery import LayerInfo, discover
from autogeo.gis.doctrine import classify_layers
from autogeo.gis.rest_client import ArcGisClient, ArcGisError, esri_feature_to_geojson

SVC = "https://gis.example.test/arcgis/rest/services/Test/MapServer"


def _client(**overrides) -> ArcGisClient:
    cfg = ArcgisConfig(politeness_delay_s=0.0, timeout_s=5.0, **overrides)
    return ArcGisClient(cfg)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr("autogeo.gis.rest_client._BACKOFF_BASE_S", 0.0)


# ---------------------------------------------------------------- rest_client


@responses.activate
def test_get_json_retries_then_succeeds():
    responses.add(responses.GET, SVC, status=500)
    responses.add(responses.GET, SVC, json={"currentVersion": 10.91})
    payload = _client(retries=2).get_json(SVC)
    assert payload == {"currentVersion": 10.91}
    assert len(responses.calls) == 2
    assert "f=json" in responses.calls[0].request.url


@responses.activate
def test_error_payload_raises_without_retry():
    responses.add(responses.GET, SVC, json={"error": {"code": 400, "message": "Invalid URL"}})
    with pytest.raises(ArcGisError, match="Invalid URL"):
        _client(retries=3).get_json(SVC)
    assert len(responses.calls) == 1  # definitive server answer: no retry


@responses.activate
def test_exhausted_retries_raise():
    responses.add(responses.GET, SVC, status=503)
    with pytest.raises(ArcGisError, match="failed after 2 attempts"):
        _client(retries=1).get_json(SVC)
    assert len(responses.calls) == 2


@responses.activate
def test_query_pagination_stitches_pages():
    def feat(i):
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [i, i]},
            "properties": {"OBJECTID": i},
        }

    responses.add(responses.POST, f"{SVC}/9/query", json={
        "type": "FeatureCollection",
        "features": [feat(1), feat(2)],
        "properties": {"exceededTransferLimit": True},
    })
    responses.add(responses.POST, f"{SVC}/9/query", json={
        "type": "FeatureCollection",
        "features": [feat(3), feat(4)],
    })

    features = _client(retries=0).query_layer(
        SVC, 9, envelope_wgs84=(-118.5, 33.9, -118.3, 34.1), out_sr="EPSG:2229"
    )
    assert [f["properties"]["OBJECTID"] for f in features] == [1, 2, 3, 4]

    body1 = parse_qs(responses.calls[0].request.body)
    assert body1["f"] == ["geojson"]
    assert body1["outSR"] == ["2229"]  # "EPSG:2229" -> wkid
    assert body1["geometryType"] == ["esriGeometryEnvelope"]
    assert body1["inSR"] == ["4326"]
    body2 = parse_qs(responses.calls[1].request.body)
    assert body2["resultOffset"] == ["2"]


@responses.activate
def test_esri_json_fallback_converts_point_and_polyline():
    # Server rejects f=geojson with an error payload -> client retries as f=json.
    responses.add(responses.POST, f"{SVC}/0/query",
                  json={"error": {"code": 400, "message": "Invalid format"}})
    responses.add(responses.POST, f"{SVC}/0/query", json={
        "features": [
            {"attributes": {"NAME": "PT-1"}, "geometry": {"x": 1.5, "y": 2.5}},
            {"attributes": {"NAME": "CL-1"},
             "geometry": {"paths": [[[0.0, 0.0], [1.0, 1.0]]]}},
        ],
    })

    features = _client(retries=0).query_layer(SVC, 0, out_sr="2229")
    assert parse_qs(responses.calls[1].request.body)["f"] == ["json"]
    assert features[0]["geometry"] == {"type": "Point", "coordinates": [1.5, 2.5]}
    assert features[0]["properties"] == {"NAME": "PT-1"}
    assert features[1]["geometry"] == {
        "type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]],
    }


def test_esri_feature_to_geojson_multipath_and_polygon():
    multi = esri_feature_to_geojson(
        {"attributes": {}, "geometry": {"paths": [[[0, 0], [1, 1]], [[2, 2], [3, 3]]]}}
    )
    assert multi["geometry"]["type"] == "MultiLineString"
    poly = esri_feature_to_geojson(
        {"attributes": {"APN": "123"},
         "geometry": {"rings": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}}
    )
    assert poly["geometry"] == {
        "type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]],
    }
    assert poly["properties"] == {"APN": "123"}


@responses.activate
def test_query_count_only():
    responses.add(responses.POST, f"{SVC}/9/query", json={"count": 61623})
    count = _client(retries=0).query_layer(SVC, 9, out_sr="EPSG:2229", count_only=True)
    assert count == 61623
    body = parse_qs(responses.calls[0].request.body)
    assert body["returnCountOnly"] == ["true"]


# ------------------------------------------------------------------ discovery

ROOT = "https://gis.example.test/arcgis/rest/services"


@responses.activate
def test_discovery_skips_broken_nodes_and_groups():
    responses.add(responses.GET, ROOT, json={
        "folders": ["Public"],
        "services": [{"name": "Broken", "type": "MapServer"}],
    })
    responses.add(responses.GET, f"{ROOT}/Public", json={
        "services": [
            {"name": "Public/Healthy", "type": "MapServer"},
            {"name": "Public/NotSpatial", "type": "GPServer"},  # ignored type
        ],
    })
    responses.add(responses.GET, f"{ROOT}/Broken/MapServer", status=500)
    responses.add(responses.GET, f"{ROOT}/Public/Healthy/MapServer", json={
        "layers": [
            {"id": 0, "name": "Monuments"},
            {"id": 1, "name": "Streets"},
            {"id": 2, "name": "Grouped", "subLayerIds": [0, 1]},  # group: skipped
        ],
    })
    responses.add(responses.GET, f"{ROOT}/Public/Healthy/MapServer/0", json={
        "name": "Monuments",
        "description": "Survey monuments",
        "geometryType": "esriGeometryPoint",
        "fields": [{"name": "OBJECTID"}, {"name": "MON_ID"}],
        "maxRecordCount": 1000,
        "advancedQueryCapabilities": {"supportsPagination": True},
        "extent": {"spatialReference": {"wkid": 2229}},
    })
    responses.add(responses.GET, f"{ROOT}/Public/Healthy/MapServer/1", json={
        "name": "Streets",
        "geometryType": "esriGeometryPolyline",
        "fields": [{"name": "FULLNAME"}],
        "maxRecordCount": 2000,
        "extent": {"spatialReference": {"wkid": 102100, "latestWkid": 3857}},
    })

    infos = discover(ROOT, _client(retries=0), max_services=10)

    assert [(i.name, i.geometry_type) for i in infos] == [
        ("Monuments", "point"), ("Streets", "polyline"),
    ]
    mon = infos[0]
    assert mon.url == f"{ROOT}/Public/Healthy/MapServer"
    assert mon.fields == ["OBJECTID", "MON_ID"]
    assert mon.supports_pagination is True
    assert mon.max_record_count == 1000
    assert mon.wkid == 2229
    assert infos[1].supports_pagination is False
    assert infos[1].wkid == 102100


@responses.activate
def test_discovery_unreachable_root_returns_empty():
    responses.add(responses.GET, ROOT, status=500)
    assert discover(ROOT, _client(retries=0), max_services=10) == []


# ------------------------------------------------------------------- doctrine


def _info(name, geometry, fields=(), description=""):
    return LayerInfo(
        url=f"{ROOT}/Public/Healthy/MapServer",
        layer_id=0,
        name=name,
        description=description,
        geometry_type=geometry,
        fields=list(fields),
    )


@pytest.fixture(scope="module")
def doctrine_cfg():
    return load_settings().doctrine


def test_doctrine_tier1_monuments_with_label_field(doctrine_cfg):
    result = classify_layers(
        [_info("Survey Monuments", "point", ["OBJECTID", "BM_DESIG"])], doctrine_cfg
    )
    assert len(result) == 1
    layer = result[0]
    assert layer.doctrine_tier == 1
    assert layer.label_fields == ["BM_DESIG"]
    assert layer.matched_keywords == ["survey.?monument"]
    assert layer.score >= doctrine_cfg.min_score
    assert layer.source == "jurisdiction"
    assert layer.positional_accuracy_m is None
    assert layer.layer_key == layer_key(layer.service_url, layer.layer_id)


def test_doctrine_tier2_centerline(doctrine_cfg):
    result = classify_layers([_info("Street Centerline", "polyline", ["FULLNAME"])], doctrine_cfg)
    assert len(result) == 1
    assert result[0].doctrine_tier == 2
    assert "FULLNAME" in result[0].label_fields


def test_doctrine_below_min_score_excluded(doctrine_cfg):
    assert classify_layers([_info("Zoning Districts", "polygon")], doctrine_cfg) == []


def test_doctrine_geometry_gate_blocks_polygon_monuments(doctrine_cfg):
    # Keyword-wise this scores 2.0 for tier 1 ("survey monument" + "bench mark"),
    # but the polygon geometry gate (-3) must stop an index grid winning tier 1.
    info = _info("Survey Monuments Index Grid", "polygon",
                 description="benchmark sheet index")
    result = classify_layers([info], doctrine_cfg)
    assert not any(l.doctrine_tier == 1 for l in result)


# -------------------------------------------------------------------- catalog


@pytest.fixture(scope="module")
def settings():
    return load_settings()


def test_catalog_la_pre1980_starts_with_tier1_city(settings):
    layers = Catalog(settings, "los_angeles_city").layers_for(1965, "CA")
    assert layers[0].doctrine_tier == 1
    assert layers[0].jurisdiction_level == "city"
    assert layers[0].name == "BOE Survey Control Points"
    # LA covers every tier -> no baseline fallbacks in the list
    assert all(l.source == "jurisdiction" for l in layers)


def test_catalog_la_modern_starts_with_tier2_city_before_county(settings):
    layers = Catalog(settings, "los_angeles_city").layers_for(2020, "CA")
    assert layers[0].doctrine_tier == 2
    tier2_levels = [l.jurisdiction_level for l in layers if l.doctrine_tier == 2]
    assert tier2_levels == ["city", "city", "county"]


def test_catalog_baselines_fill_missing_tiers(settings):
    fake = JurisdictionConfig(
        display_name="Fakeville",
        state="CA",
        layers=[CuratedLayer(
            service_url=f"{ROOT}/Fake/MapServer", layer_id=3, name="Fake Streets",
            geometry_type="polyline", doctrine_tier=2, jurisdiction_level="city",
        )],
    )
    patched = settings.model_copy(
        update={"jurisdictions": {**settings.jurisdictions, "fakeville": fake}}
    )
    layers = Catalog(patched, "fakeville").layers_for(None, "CA")

    assert layers[0].name == "Fake Streets" and layers[0].source == "jurisdiction"
    tier1 = [l for l in layers if l.doctrine_tier == 1]
    assert tier1 and all(l.source == "baseline" for l in tier1)
    names = " ".join(l.name for l in tier1)
    assert "PLSS" in names and "NGS" in names
    # tier 2 is covered by the jurisdiction -> no TIGERweb fallback
    assert not any("TIGERweb" in l.name for l in layers)


def test_catalog_ny_availability_excludes_jurisdiction_tier1(settings):
    ny = JurisdictionConfig(
        display_name="Test NY City",
        state="NY",
        layers=[
            CuratedLayer(service_url=f"{ROOT}/NY/MapServer", layer_id=0,
                         name="NY Monuments", geometry_type="point",
                         doctrine_tier=1, jurisdiction_level="city"),
            CuratedLayer(service_url=f"{ROOT}/NY/MapServer", layer_id=1,
                         name="NY Centerlines", geometry_type="polyline",
                         doctrine_tier=2, jurisdiction_level="city"),
        ],
    )
    patched = settings.model_copy(
        update={"jurisdictions": {**settings.jurisdictions, "test_ny": ny}}
    )
    layers = Catalog(patched, "test_ny").layers_for(1950, "NY")

    assert not any(l.source == "jurisdiction" and l.doctrine_tier == 1 for l in layers)
    assert any(l.name == "NY Centerlines" for l in layers)
    # tier 1 still reachable, but only through national baseline marks
    assert any(l.source == "baseline" and l.doctrine_tier == 1 for l in layers)


def test_catalog_unknown_jurisdiction_raises(settings):
    with pytest.raises(ValueError, match="unknown jurisdiction"):
        Catalog(settings, "atlantis")


def test_catalog_save_load_roundtrip(settings, tmp_path):
    catalog = Catalog(settings, "los_angeles_city")
    path = tmp_path / "catalog.json"
    catalog.save(path)
    loaded = Catalog.load(path)
    assert loaded == catalog.all_layers()


def test_baseline_layers_conversion(settings):
    layers = baseline_layers(settings.baselines)
    assert layers and all(l.source == "baseline" for l in layers)
    assert all(l.score == 1.0 for l in layers)
    disabled = settings.baselines.model_copy(update={"enabled": False})
    assert baseline_layers(disabled) == []


def test_curated_to_control_stable_key(settings):
    entry = settings.jurisdictions["los_angeles_city"].layers[0]
    a = curated_to_control(entry, "jurisdiction")
    b = curated_to_control(entry, "manual")
    assert a.layer_key == b.layer_key == layer_key(entry.service_url, entry.layer_id)
    assert a.score == 1.0 and b.source == "manual"


# ---------------------------------------------------------------------- cache


class _FakeClient:
    def __init__(self):
        self.calls = 0

    def query_layer(self, service_url, layer_id, *, envelope_wgs84=None, where=None,
                    out_fields="*", out_sr, count_only=False):
        self.calls += 1
        return [{"type": "Feature",
                 "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                 "properties": {"fetch": self.calls}}]


def _control_layer():
    return curated_to_control(
        CuratedLayer(service_url=SVC, layer_id=9, name="Intersections",
                     geometry_type="point", doctrine_tier=2, jurisdiction_level="city"),
        "manual",
    )


def test_feature_cache_hit_miss_and_expiry(tmp_path):
    cfg = CacheConfig(dir=tmp_path, feature_ttl_days=30)
    client = _FakeClient()
    layer = _control_layer()
    envelope = (-118.5, 33.9, -118.3, 34.1)

    first = cached_query(client, layer, envelope, "EPSG:2229", cfg)
    second = cached_query(client, layer, envelope, "EPSG:2229", cfg)
    assert client.calls == 1  # hit within TTL
    assert second == first

    cached_query(client, layer, envelope, "EPSG:2229", cfg, where="X=1")
    assert client.calls == 2  # different where -> different key

    # Age the entry past the TTL by rewriting its sidecar meta.
    for meta_path in (tmp_path / "features" / layer.layer_key).glob("*.meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        stale = datetime.now(timezone.utc) - timedelta(days=31)
        meta["fetched_at"] = stale.isoformat()
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    refreshed = cached_query(client, layer, envelope, "EPSG:2229", cfg)
    assert client.calls == 3  # expired -> refetched
    assert refreshed[0]["properties"]["fetch"] == 3


def test_make_cached_session(tmp_path):
    cfg = CacheConfig(dir=tmp_path / "cache")
    session = make_cached_session(cfg)
    try:
        assert isinstance(session, requests_cache.CachedSession)
        assert "POST" in session.settings.allowable_methods
        assert (tmp_path / "cache" / "http_cache.sqlite").exists()
    finally:
        session.close()


def test_save_load_layers_helpers(tmp_path):
    layers = [_control_layer()]
    path = tmp_path / "nested" / "proposals.json"
    save_layers(layers, path)
    assert load_layers(path) == layers


# ----------------------------------------------------------------------- live


@pytest.mark.live
def test_live_la_intersections_count():
    """Reality check against the verified LA BOE intersections layer (~61k pts)."""
    client = ArcGisClient(ArcgisConfig())
    count = client.query_layer(
        "https://maps.lacity.org/lahub/rest/services/Street_Information/MapServer",
        9,
        out_sr="EPSG:2229",
        count_only=True,
    )
    assert isinstance(count, int)
    assert count > 50000
