"""CRS registry cross-checked against the PROJ database (verification tier T2),
plus the datum-grid guard behavior."""

from pathlib import Path

import pytest
from pyproj import CRS

from autogeo.context.crs import (
    _SPCS_CA,
    assert_datum_grids,
    make_transformer,
    parse_datum,
    parse_zone_number,
    resolve_spcs_ca,
    resolve_stated_crs,
)


ROMAN = {1: "i", 2: "ii", 3: "iii", 4: "iv", 5: "v", 6: "vi", 7: "vii"}


def test_spcs_registry_matches_proj_database():
    """Every registry EPSG must exist in PROJ and be the CRS we think it is."""
    for (datum, zone, unit), code in _SPCS_CA.items():
        crs = CRS.from_user_input(code)
        name = crs.name.lower()
        assert "california" in name, f"{code} is {crs.name}, not a California SPCS zone"
        # NAD27 zone names use Roman numerals ("zone V"), NAD83+ use Arabic
        zone_forms = (f"zone {zone}", f"zone {ROMAN[zone]} ", f"zone {ROMAN[zone]}")
        assert any(name.endswith(f) or f in name for f in zone_forms), (
            f"{code} is {crs.name}, expected zone {zone}"
        )
        if datum == "NAD27":
            assert "nad27" in name
        elif datum == "NAD83_HARN":
            assert "harn" in name
        elif datum == "NAD83_2011":
            assert "2011" in name
        else:
            assert "nad83" in name and "harn" not in name and "2011" not in name
        axis_unit = crs.axis_info[0].unit_name.lower()
        if unit == "us_survey_foot":
            assert "foot" in axis_unit, f"{code} axis unit is {axis_unit}"
        else:
            assert axis_unit in ("metre", "meter"), f"{code} axis unit is {axis_unit}"


@pytest.mark.parametrize(
    "text,zone",
    [
        ("CALIFORNIA COORDINATE SYSTEM ZONE V", 5),
        ("Calif. Coordinate System, Zone 5", 5),
        ("C.C.S. ZONE VII", 7),
        ("CALIFORNIA ZONE III", 3),
        ("no zone here", None),
    ],
)
def test_parse_zone_number(text, zone):
    assert parse_zone_number(text) == zone


@pytest.mark.parametrize(
    "text,datum",
    [
        ("N.A.D. 1927", "NAD27"),
        ("BEARINGS BASED ON NAD 27", "NAD27"),
        ("NAD83 (HARN)", "NAD83_HARN"),
        ("NAD 83 (2011) EPOCH 2010.00", "NAD83_2011"),
        ("NORTH AMERICAN DATUM OF 1983", "NAD83"),
        ("no datum wording", None),
    ],
)
def test_parse_datum(text, datum):
    assert parse_datum(text) == datum


def test_zone7_maps_to_zone5_for_nad83():
    """NAD83 dropped LA's old zone 7 — it must resolve to zone 5, not fail."""
    assert resolve_spcs_ca("NAD83", 7, "us_survey_foot") == "EPSG:2229"
    assert resolve_spcs_ca("NAD27", 7, "us_survey_foot") == "EPSG:26747"


def test_resolve_stated_crs_titleblock():
    stated = resolve_stated_crs("CALIFORNIA COORDINATE SYSTEM ZONE V  N.A.D. 1927")
    assert stated.crs_auth_code == "EPSG:26745"
    assert stated.datum == "NAD27"
    assert stated.source == "titleblock"
    assert stated.confidence >= 0.7


def test_resolve_stated_crs_layer_prior_fallback():
    stated = resolve_stated_crs("illegible smudge", layer_prior_crs="EPSG:2229")
    assert stated.crs_auth_code == "EPSG:2229"
    assert stated.source == "layer_prior"
    assert stated.confidence < 0.5


GRIDS_DIR = Path("data/cache/proj")


def test_transformer_refuses_ballpark():
    """The core guard: NAD27->NAD83 must be grid-backed or fail loudly.

    only_best + allow_ballpark=False means a grid-less environment raises or
    returns inf on transform instead of silently applying a Helmert ballpark.
    """
    assert_datum_grids(download=True, grids_dir=GRIDS_DIR)  # fetches NADCON on first run
    tx = make_transformer("EPSG:4267", "EPSG:4269", area=(-119.0, 33.5, -117.5, 34.5))
    lon83, lat83 = tx.transform(-118.2437, 34.0522)
    # NAD27->NAD83 shift in LA is meters-scale, dominated by longitude
    dx_deg = abs(lon83 - (-118.2437))
    dy_deg = abs(lat83 - 34.0522)
    assert 1e-6 < dx_deg < 3e-3, f"implausible lon shift {dx_deg} deg"
    assert dy_deg < 3e-4, f"implausible lat shift {dy_deg} deg"
    # And it must be a grid/NADCON operation, not a ballpark Helmert
    assert "ballpark" not in tx.description.lower()


def test_projected_transform_nad27_zone7_to_nad83_zone5():
    """Cross-check (T2): the compound old-doc path SPCS27 z7 -> SPCS83 z5 must
    agree with directly projecting the same physical point. If the datum shift
    were silently skipped, the two paths diverge by ~90 m in LA."""
    assert_datum_grids(download=True, grids_dir=GRIDS_DIR)
    la_aoi = (-119.0, 33.5, -117.5, 34.5)
    lon83, lat83 = -118.2437, 34.0522  # downtown LA, NAD83 geographic

    # Path A: direct projection NAD83 geographic -> SPCS83 zone 5 ftUS
    direct = make_transformer("EPSG:4269", "EPSG:2229", area=la_aoi)
    e_direct, n_direct = direct.transform(lon83, lat83)

    # Path B: same point expressed in NAD27 z7, then the transform under test
    to_nad27 = make_transformer("EPSG:4269", "EPSG:4267", area=la_aoi)
    lon27, lat27 = to_nad27.transform(lon83, lat83)
    project27 = make_transformer("EPSG:4267", "EPSG:26747", area=la_aoi)
    e27, n27 = project27.transform(lon27, lat27)
    under_test = make_transformer("EPSG:26747", "EPSG:2229", area=la_aoi)
    e_compound, n_compound = under_test.transform(e27, n27)

    ft = 0.3048006096  # US survey foot in meters
    assert abs(e_compound - e_direct) * ft < 0.5, f"easting off {abs(e_compound-e_direct)*ft:.2f} m"
    assert abs(n_compound - n_direct) * ft < 0.5, f"northing off {abs(n_compound-n_direct)*ft:.2f} m"
    # And the datum shift is real: treating NAD83 lon/lat AS IF it were NAD27
    # (the classic unstated-datum mistake) must move the result by tens of meters
    e_wrong, n_wrong = project27.transform(lon83, lat83)  # datum-confused input
    shift_m = ((e_wrong - e27) ** 2 + (n_wrong - n27) ** 2) ** 0.5 * ft
    assert shift_m > 30, f"datum shift only {shift_m:.1f} m — NADCON not applied?"
