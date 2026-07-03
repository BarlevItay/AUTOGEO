"""Stated-CRS resolution and datum-safe transformers.

Two jobs:
1. Map title-block wording ("CALIFORNIA COORDINATE SYSTEM ZONE V", "N.A.D. 1927")
   onto EPSG codes via a curated SPCS registry.
2. Build pyproj transformers that can NEVER silently fall back to a ballpark
   Helmert when datum grids are missing — the multi-meter trap that reports
   success. All transformers use only_best=True + allow_ballpark=False, and
   `assert_datum_grids()` is the startup guard.
"""

from __future__ import annotations

import re

from pathlib import Path

from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.datadir import append_data_dir
from pyproj.transformer import TransformerGroup

from autogeo.logging import get_logger
from autogeo.models.document import StatedCRS

log = get_logger("context.crs")

Datum = str  # "NAD27" | "NAD83" | "NAD83_HARN" | "NAD83_2011"
Unit = str  # "us_survey_foot" | "meter"

# SPCS California registry: (datum, zone, unit) -> EPSG code.
# NAD27 SPCS is defined in US survey feet; NAD83 has meter and ftUS variants.
# NAD83 merged old zone 7 (LA) into zone 5. Codes cross-checked against the
# PROJ database in tests/test_crs.py.
_SPCS_CA: dict[tuple[Datum, int, Unit], str] = {
    **{("NAD27", z, "us_survey_foot"): f"EPSG:{26740 + z}" for z in range(1, 8)},
    **{("NAD83", z, "meter"): f"EPSG:{26940 + z}" for z in range(1, 7)},
    **{("NAD83", z, "us_survey_foot"): f"EPSG:{2224 + z}" for z in range(1, 7)},
    ("NAD83_HARN", 5, "meter"): "EPSG:2770",
    ("NAD83_HARN", 5, "us_survey_foot"): "EPSG:2874",
    ("NAD83_2011", 5, "meter"): "EPSG:6423",
    ("NAD83_2011", 5, "us_survey_foot"): "EPSG:6424",
}

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}

_ZONE_RE = re.compile(
    r"(?:CALIF(?:ORNIA)?|C\.?C\.?S\.?)[^\n]*?ZONE\s*(VII|VI|V|IV|III|II|I|[1-7])",
    re.IGNORECASE,
)
# "NAD 27", "N.A.D. 1927", "NORTH AMERICAN DATUM OF 1927", etc.
_NAD = r"(?:N\.?\s*A\.?\s*D\.?|NORTH\s+AMERICAN\s+DATUM(?:\s+OF)?)"
_DATUM_RES: list[tuple[re.Pattern, Datum]] = [
    (re.compile(_NAD + r"\s*(?:19)?27", re.IGNORECASE), "NAD27"),
    (re.compile(r"HARN|HPGN", re.IGNORECASE), "NAD83_HARN"),
    (re.compile(_NAD + r"\s*(?:19)?83[^)\n]*2011|\b2011\s*ADJ", re.IGNORECASE), "NAD83_2011"),
    (re.compile(_NAD + r"\s*(?:19)?83", re.IGNORECASE), "NAD83"),
]


def parse_zone_number(text: str) -> int | None:
    m = _ZONE_RE.search(text)
    if not m:
        return None
    token = m.group(1).upper()
    return _ROMAN.get(token) or int(token)


def parse_datum(text: str) -> Datum | None:
    for pattern, datum in _DATUM_RES:
        if pattern.search(text):
            return datum
    return None


def resolve_spcs_ca(datum: Datum, zone: int, unit: Unit) -> str | None:
    """EPSG auth code for a California SPCS zone, or None if not in registry.

    NAD83 dropped zone 7 — old LA-area zone 7 documents map to NAD83 zone 5.
    """
    if datum != "NAD27" and zone == 7:
        zone = 5
    return _SPCS_CA.get((datum, zone, unit))


def resolve_stated_crs(
    titleblock_text: str,
    unit_hint: Unit | None = None,
    layer_prior_crs: str | None = None,
) -> StatedCRS:
    """Best-effort StatedCRS from raw title-block text, with layer-CRS prior fallback."""
    zone = parse_zone_number(titleblock_text)
    datum = parse_datum(titleblock_text)
    if zone is not None and datum is not None:
        # SPCS27 is ftUS by definition; CA practice for SPCS83 is ftUS unless stated
        unit = unit_hint or "us_survey_foot"
        code = resolve_spcs_ca(datum, zone, unit)
        if code:
            return StatedCRS(
                crs_auth_code=code,
                datum=datum,  # type: ignore[arg-type]
                unit=unit,  # type: ignore[arg-type]
                zone_text=titleblock_text.strip()[:200],
                source="titleblock",
                confidence=0.8 if datum == "NAD27" or "83" in datum else 0.7,
            )
    if layer_prior_crs:
        prior = CRS.from_user_input(layer_prior_crs)
        return StatedCRS(
            crs_auth_code=f"EPSG:{prior.to_epsg()}" if prior.to_epsg() else None,
            crs_wkt=None if prior.to_epsg() else prior.to_wkt(),
            zone_text=titleblock_text.strip()[:200] or None,
            source="layer_prior",
            confidence=0.4,
        )
    return StatedCRS(zone_text=titleblock_text.strip()[:200] or None, confidence=0.0)


class DatumGridsMissingError(RuntimeError):
    """Raised when a required datum-shift grid is unavailable and would silently
    degrade to a multi-meter ballpark transform."""


# CONUS: scopes NAD27->NAD83 to the NADCON path (without it, PROJ also
# considers e.g. the Canadian NTv2 grid and downloads the wrong thing)
_CONUS = AreaOfInterest(-125.0, 24.0, -66.0, 50.0)


def make_transformer(
    src: str | CRS,
    dst: str | CRS,
    area: tuple[float, float, float, float] | None = None,
) -> Transformer:
    """Grid-honest transformer: fails loudly rather than degrading silently.

    `area` is an optional WGS84 (west, south, east, north) envelope used to
    pick the correct regional grid path.
    """
    aoi = AreaOfInterest(*area) if area else None
    return Transformer.from_crs(
        CRS.from_user_input(src),
        CRS.from_user_input(dst),
        always_xy=True,
        only_best=True,
        allow_ballpark=False,
        area_of_interest=aoi,
    )


def _nadcon_group() -> TransformerGroup:
    return TransformerGroup(
        "EPSG:4267", "EPSG:4269", always_xy=True, area_of_interest=_CONUS
    )


def assert_datum_grids(download: bool = True, grids_dir: Path | None = None) -> None:
    """Startup guard: require the NAD27->NAD83 NADCON path to be grid-backed.

    With `download=True`, missing grids are fetched from cdn.proj.org into
    `grids_dir` (registered with PROJ for this process) or the PROJ user dir.
    """
    if grids_dir is not None:
        grids_dir.mkdir(parents=True, exist_ok=True)
        append_data_dir(str(grids_dir))
    group = _nadcon_group()
    if not group.best_available:
        if download:
            log.info("datum grids missing; downloading from cdn.proj.org ...")
            group.download_grids(directory=grids_dir, verbose=False)
            group = _nadcon_group()
        if not group.best_available:
            raise DatumGridsMissingError(
                "NAD27->NAD83 grid-based transform unavailable (NADCON grids missing). "
                "Run autogeo with network access once, or `pyproj sync --source-id us_noaa`. "
                "Refusing to continue: fallback would silently introduce multi-meter error."
            )
    # Belt and braces: the best transform must actually be usable end-to-end.
    tx = make_transformer("EPSG:4267", "EPSG:4269", area=(-119.0, 33.5, -117.5, 34.5))
    lon, lat = tx.transform(-118.2437, 34.0522)  # downtown LA
    if not (abs(lon + 118.24) < 0.01 and abs(lat - 34.05) < 0.01):
        raise DatumGridsMissingError(f"NAD27->NAD83 sanity transform produced ({lon}, {lat})")
