"""Spike 5/R6: sample real reliability metadata from PLSS corners and NGS marks.

Discovers the actual field names, samples features, and histograms the values —
the numbers that set default `reliability_filter` entries in defaults.yaml.

Run: .venv/Scripts/python.exe scripts/spike_reliability.py
"""

from __future__ import annotations

import re
from collections import Counter

import requests

TIMEOUT = 60
RURAL_CA = (-119.5, 35.2, -118.8, 35.7)  # Kern County foothills
URBAN_LA = (-118.45, 33.95, -118.15, 34.15)

session = requests.Session()
session.headers["User-Agent"] = "autogeo-spike/0.1"


def get_json(url: str, **params) -> dict:
    params.setdefault("f", "json")
    r = session.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{url}: {data['error']}")
    return data


def query(layer_url: str, envelope, out_fields: str, n: int) -> list[dict]:
    data = get_json(
        layer_url + "/query",
        geometry=",".join(str(v) for v in envelope),
        geometryType="esriGeometryEnvelope",
        inSR=4326,
        outFields=out_fields,
        returnGeometry="false",
        resultRecordCount=n,
        where="1=1",
    )
    return [f["attributes"] for f in data.get("features", [])]


def interesting_fields(layer_json: dict, pattern: str) -> list[str]:
    rx = re.compile(pattern, re.IGNORECASE)
    return [f["name"] for f in layer_json.get("fields", []) if rx.search(f["name"])]


def main() -> None:
    print("=== BLM CA CADNSDI: find corner-point layer ===")
    svc = "https://gis.blm.gov/caarcgis/rest/services/lands/BLM_CA_CADNSDI/FeatureServer"
    layers = get_json(svc)["layers"]
    for lyr in layers:
        print(f"  layer {lyr['id']}: {lyr['name']}")
    corner = next((l for l in layers if re.search(r"corner|point", l["name"], re.I)), None)
    if corner:
        url = f"{svc}/{corner['id']}"
        meta = get_json(url)
        fields = interesting_fields(meta, r"RELY|RELIAB|ERROR|ACCUR|SOURCE|METHOD|COORD")
        print(f"\n  corner layer {corner['id']} '{corner['name']}', candidate fields: {fields}")
        sample = query(url, RURAL_CA, ",".join(fields) or "*", 200)
        print(f"  sampled {len(sample)} rural-CA corners:")
        for fld in fields:
            vals = Counter(str(row.get(fld)) for row in sample)
            if len(vals) > 1 or fld.upper().startswith("RELY"):
                print(f"    {fld}: {dict(vals.most_common(12))}")
    else:
        print("  NO corner/point layer found — inspect service manually")

    print("\n=== NGS Datasheets: position-source distribution (urban LA) ===")
    # layer 1 = ALL_DATASHEETS (there is no layer 0 — verified 2026-07-03)
    ngs = ("https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/"
           "NGS_Datasheets_Feature_Service/FeatureServer/1")
    meta = get_json(ngs)
    fields = interesting_fields(meta, r"POS|SOURCE|HORIZ|ORDER|COND|DATE|LAST")
    print(f"  candidate fields: {fields}")
    sample = query(ngs, URBAN_LA, ",".join(fields) or "*", 200)
    print(f"  sampled {len(sample)} urban-LA marks:")
    for fld in fields:
        vals = Counter(str(row.get(fld)) for row in sample)
        if 1 < len(vals) <= 25:
            print(f"    {fld}: {dict(vals.most_common(12))}")


if __name__ == "__main__":
    main()
