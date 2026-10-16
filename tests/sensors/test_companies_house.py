"""Companies House lookups (D103): exact-name matching, company-level facts only, rendering.
No network: hand-built responses with invented companies test our own parsing and rules."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from northvaine.core.settings import Settings
from northvaine.sensors.base import ConfigError
from northvaine.sensors.companies_house import (
    CompaniesHouseClient,
    name_key,
    parse_record,
    render_register_text,
    sic_descriptions,
)

SETTINGS = Settings(
    _env_file=None,
    companies_house_api_key=SecretStr("test-key"),
    companies_house_min_interval_seconds=0,
)

PROFILE = {
    "company_number": "00000001",
    "company_name": "EXAMPLE TRADING LIMITED",
    "company_status": "active",
    "date_of_creation": "2025-04-07",
    "sic_codes": ["46730"],
    "previous_company_names": [
        {"name": "OLD EXAMPLE LIMITED", "effective_from": "2025-04-07", "ceased_on": "2026-01-15"}
    ],
}
PSC = {
    "items": [
        {
            "kind": "corporate-entity-person-with-significant-control",
            "name": "EXAMPLE HOLDINGS LIMITED",
            "notified_on": "2025-12-16",
        },
        {
            "kind": "individual-person-with-significant-control",
            "name": "A PERSON",
            "notified_on": "2026-07-10",
            "date_of_birth": {"month": 1, "year": 1970},
        },
        {
            "kind": "corporate-entity-person-with-significant-control",
            "name": "FORMER OWNER LIMITED",
            "notified_on": "2020-01-01",
            "ceased_on": "2025-12-16",
        },
    ]
}


def test_name_key_ignores_legal_form_spacing_and_case() -> None:
    assert name_key("Example Trading Ltd") == name_key("EXAMPLE TRADING LIMITE D")
    assert name_key("Example Trading Ltd") == name_key("example trading limited")
    assert name_key("Example & Sons") == name_key("EXAMPLE AND SONS LTD")
    assert name_key("Example Trading") != name_key("Example Trading Two")


def test_parse_keeps_company_level_facts_only() -> None:
    r = parse_record(PROFILE, PSC)
    assert r.status == "active" and r.incorporated == date(2025, 4, 7)
    assert r.previous_names == [("OLD EXAMPLE LIMITED", date(2026, 1, 15))]
    assert [c.name for c in r.controllers] == ["EXAMPLE HOLDINGS LIMITED"]  # ceased one dropped
    assert r.control_changed_on == date(2026, 7, 10)
    text = render_register_text(r)
    assert "A PERSON" not in text and "1970" not in text
    assert text.splitlines()[:4] == [
        "Company: EXAMPLE TRADING LIMITED (00000001)",
        "Status: active",
        "Incorporated: 2025-04-07",
        f"Activity (SIC 46730): {sic_descriptions()['46730']}",
    ]
    assert "Previous name: OLD EXAMPLE LIMITED (until 2026-01-15)" in text
    assert "Controlled by: EXAMPLE HOLDINGS LIMITED (since 2025-12-16)" in text
    assert "Control last notified: 2026-07-10" in text


def handler(search_items: list[dict[str, Any]]):
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path == "/search/companies":
            return httpx.Response(200, json={"items": search_items})
        if request.url.path.endswith("/persons-with-significant-control"):
            return httpx.Response(200, json=PSC)
        return httpx.Response(200, json=PROFILE)

    return respond, calls


async def test_lookup_takes_only_an_exact_name_match() -> None:
    respond, calls = handler(
        [
            {"company_number": "00000009", "title": "EXAMPLE TRADING GROUP LIMITED"},
            {"company_number": "00000001", "title": "EXAMPLE TRADING LIMITED"},
        ]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        record = await CompaniesHouseClient(client=http, settings=SETTINGS).lookup(
            "EXAMPLE TRADING LIMITE D"
        )
    assert record is not None and record.number == "00000001"
    assert calls[1:] == ["/company/00000001", "/company/00000001/persons-with-significant-control"]


async def test_lookup_returns_none_without_an_exact_match() -> None:
    respond, calls = handler([{"company_number": "00000009", "title": "EXAMPLE TRADING GROUP LTD"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        record = await CompaniesHouseClient(client=http, settings=SETTINGS).lookup(
            "Example Trading"
        )
    assert record is None and calls == ["/search/companies"]


def test_a_key_is_required() -> None:
    with pytest.raises(ConfigError):
        CompaniesHouseClient(settings=Settings(_env_file=None))
