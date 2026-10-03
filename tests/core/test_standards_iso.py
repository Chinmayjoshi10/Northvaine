"""ISO 3166-1 table and helpers (T3.0a)."""

from __future__ import annotations

import csv
import re

import pytest

from northvaine.core import standards
from northvaine.core.standards import iso2_to_iso3, iso2_to_name


def rows() -> list[dict[str, str]]:
    with standards._ISO3166_CSV.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_known_codes() -> None:
    assert iso2_to_iso3("DE") == "DEU"
    assert iso2_to_iso3("GB") == "GBR"
    assert iso2_to_iso3("us") == "USA"
    assert iso2_to_name("GB") == "united kingdom"
    assert iso2_to_name("DE") == "germany"


@pytest.mark.parametrize("code", ["ZZ", "", "DEU", "UK"])
def test_unknown_codes_raise_key_error(code: str) -> None:
    with pytest.raises(KeyError):
        iso2_to_iso3(code)
    with pytest.raises(KeyError):
        iso2_to_name(code)


def test_every_row_is_well_formed_and_unique() -> None:
    data = rows()
    assert len(data) >= 249
    assert len({r["alpha2"] for r in data}) == len(data)
    assert len({r["alpha3"] for r in data}) == len(data)
    assert len({r["name"] for r in data}) == len(data)
    for r in data:
        assert re.fullmatch(r"[A-Z]{2}", r["alpha2"]), r
        assert re.fullmatch(r"[A-Z]{3}", r["alpha3"]), r
        assert r["name"] == r["name"].lower() and r["name"].strip(), r


def test_every_eu_member_and_major_market_is_present() -> None:
    wanted = [
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
        "GB",
        "US",
        "CN",
        "IN",
        "JP",
        "AE",
        "SA",
        "TR",
        "CH",
        "NO",
    ]
    for code in wanted:
        iso2_to_iso3(code)
