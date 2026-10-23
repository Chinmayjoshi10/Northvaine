"""D126: registered-office postcode and district-level coordinates. Invented companies; the
postcodes.io reply is faked after its documented shape (POST /postcodes, result[].query/result)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from northvaine.core.settings import Settings
from northvaine.radar.register import register_check
from northvaine.sensors.companies_house import parse_record
from tests.radar.test_register_edition import NOW, SETTINGS, spec
from tests.radar.test_trade_stream import importer

PROFILE = {
    "company_number": "00000001",
    "company_name": "NEW IMPORTS LTD",
    "company_status": "active",
    "date_of_creation": "2025-06-01",
    "sic_codes": ["46900"],
    "registered_office_address": {
        "address_line_1": "1 Test Street",
        "locality": "Stoke-on-Trent",
        "postal_code": "st1 1aa",
    },
}


def transport(geocode: Any) -> tuple[httpx.MockTransport, list[dict[str, Any]]]:
    posted: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "api.postcodes.io":
            posted.append(json.loads(request.content))
            return geocode(request)
        if path == "/search/companies":
            return httpx.Response(
                200, json={"items": [{"company_number": "00000001", "title": "NEW IMPORTS LTD"}]}
            )
        if path.endswith("/persons-with-significant-control"):
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json=PROFILE)

    return httpx.MockTransport(respond), posted


def found(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": 200,
            "result": [
                {
                    "query": "ST1 1AA",
                    "result": {"postcode": "ST1 1AA", "latitude": 53.02512, "longitude": -2.17794},
                }
            ],
        },
    )


def test_profile_address_is_parsed() -> None:
    record = parse_record(PROFILE, None)
    assert record.postcode == "ST1 1AA" and record.locality == "Stoke-on-Trent"
    plain = {k: v for k, v in PROFILE.items() if k != "registered_office_address"}
    bare = parse_record(plain, None)
    assert bare.postcode is None and bare.locality is None


async def run(geocode: Any, settings: Settings = SETTINGS):
    mock, posted = transport(geocode)
    async with httpx.AsyncClient(transport=mock) as http:
        kept, _, notes = await register_check(
            [importer("New Imports Ltd", new=False)],
            spec(),
            http=http,
            as_of=NOW,
            settings=settings,
        )
    return kept[0].company_register, notes, posted


async def test_geocode_fills_rounded_coordinates_in_one_bulk_request() -> None:
    facts, notes, posted = await run(found)
    assert facts is not None
    assert (facts.postcode, facts.locality) == ("ST1 1AA", "Stoke-on-Trent")
    assert (facts.lat, facts.lon) == (53.03, -2.18)
    assert posted == [{"postcodes": ["ST1 1AA"]}]
    assert any("1 of 1 postcodes placed" in n for n in notes)


async def test_geocode_failure_is_a_note_not_a_failed_run() -> None:
    facts, notes, _ = await run(lambda r: httpx.Response(503))
    assert facts is not None and facts.lat is None and facts.lon is None
    assert facts.postcode == "ST1 1AA"
    assert any("postcodes not placed" in n for n in notes)
    facts, notes, _ = await run(lambda r: httpx.Response(200, text="<html>"))
    assert facts is not None and facts.lat is None
    assert any("postcodes not placed" in n for n in notes)


async def test_geocode_off_makes_no_request() -> None:
    settings = SETTINGS.model_copy(update={"radar_register_geocode": False})
    facts, notes, posted = await run(found, settings)
    assert facts is not None and facts.lat is None and posted == []
    assert not any("postcodes" in n for n in notes)


def test_legacy_replays_pin_geocoding_off() -> None:
    from northvaine.brain.replay import LEGACY_SETTINGS

    assert LEGACY_SETTINGS["radar_register_geocode"] is False


def test_api_row_place_present_only_when_coordinates_exist() -> None:
    from types import SimpleNamespace

    from northvaine.api.views import _place
    from northvaine.radar.models import RegisterFacts

    def entry(**kw: Any) -> Any:
        facts = RegisterFacts(number="1", status="active", **kw)
        c = importer("New Imports Ltd", new=False).model_copy(update={"company_register": facts})
        return SimpleNamespace(candidate=c)

    place = _place(entry(postcode="ST1 1AA", locality="Stoke-on-Trent", lat=53.03, lon=-2.18))
    assert place is not None and (place.lat, place.lon) == (53.03, -2.18)
    assert place.label == "Stoke-on-Trent"
    district = _place(entry(postcode="ST1 1AA", lat=53.03, lon=-2.18))
    assert district is not None and district.label == "ST1"
    assert _place(entry(postcode="ST1 1AA")) is None
    bare = SimpleNamespace(candidate=importer("X Ltd", new=False))
    assert _place(bare) is None
