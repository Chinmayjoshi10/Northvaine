"""The register check and the daily edition (D103). Invented companies; no network, no model."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx
from pydantic import SecretStr

from northvaine.core.settings import Settings
from northvaine.radar import brief
from northvaine.radar.edition import daily_edition, label_entries
from northvaine.radar.models import ClientSpec, SkepticFinding
from northvaine.radar.register import register_check
from tests.radar.test_trade_stream import gate, importer

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
SETTINGS = Settings(
    _env_file=None,
    companies_house_api_key=SecretStr("test-key"),
    companies_house_min_interval_seconds=0,
)
UNKNOWN = SkepticFinding(stance="unknown", against=[], open_questions=["Who supplies it now?"])


def spec(**kw: Any) -> ClientSpec:
    base: dict[str, Any] = dict(
        id="t",
        offer="test goods",
        markets=["GB"],
        sensors={},
        buyer_roles=["importer"],
        not_buyer_codes=["sic:49410"],
    )
    base.update(kw)
    return ClientSpec(**base)


def register(profiles: dict[str, dict[str, Any]]):
    """A fake register: search returns the exact title; profiles by number."""

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/companies":
            q = request.url.params["q"]
            items = [
                {"company_number": n, "title": p["company_name"]}
                for n, p in profiles.items()
                if p["company_name"].upper().startswith(q.upper().split(" LTD")[0])
            ]
            return httpx.Response(200, json={"items": items})
        number = path.split("/")[2]
        if path.endswith("/persons-with-significant-control"):
            return httpx.Response(200, json={"items": profiles[number].get("_psc", [])})
        return httpx.Response(200, json={k: v for k, v in profiles[number].items() if k != "_psc"})

    return httpx.MockTransport(respond)


PROFILES = {
    "00000001": {
        "company_number": "00000001",
        "company_name": "NEW IMPORTS LTD",
        "company_status": "active",
        "date_of_creation": "2025-06-01",
        "sic_codes": ["46900"],
    },
    "00000002": {
        "company_number": "00000002",
        "company_name": "ROAD HAULAGE LTD",
        "company_status": "active",
        "date_of_creation": "1990-01-01",
        "sic_codes": ["49410"],
    },
    "00000003": {
        "company_number": "00000003",
        "company_name": "CLOSED IMPORTS LTD",
        "company_status": "dissolved",
        "date_of_creation": "2001-01-01",
        "sic_codes": ["46900"],
    },
    "00000004": {
        "company_number": "00000004",
        "company_name": "OLD IMPORTS LTD",
        "company_status": "active",
        "date_of_creation": "1999-01-01",
        "sic_codes": ["46900"],
        "_psc": [
            {
                "kind": "corporate-entity-person-with-significant-control",
                "name": "NEW OWNER GROUP LIMITED",
                "notified_on": "2026-07-10",
            }
        ],
    },
}


async def test_register_check_adds_claims_and_rejects_by_code() -> None:
    names = ["New Imports Ltd", "Road Haulage Ltd", "Closed Imports Ltd", "Old Imports Ltd"]
    candidates = [importer(n, new=False) for n in names]
    async with httpx.AsyncClient(transport=register(PROFILES)) as http:
        kept, rejected, notes = await register_check(
            candidates, spec(), http=http, as_of=NOW, settings=SETTINGS
        )
    assert sorted(c.name for c in kept) == ["New Imports Ltd", "Old Imports Ltd"]
    reasons = {r.candidate.name: r.gate for r in rejected}
    assert reasons["Road Haulage Ltd"].by == "code"
    assert "49410" in reasons["Road Haulage Ltd"].reason
    assert "dissolved" in reasons["Closed Imports Ltd"].reason
    new = next(c for c in kept if c.name == "New Imports Ltd")
    quotes = [k.source_quote for k in new.claims if k.source_name == "companies_house"]
    assert quotes[0] == "Company: NEW IMPORTS LTD (00000001)"
    assert all(k.ref == f"C{i}" for i, k in enumerate(new.claims, 1))
    assert new.company_register is not None
    assert new.company_register.incorporated == date(2025, 6, 1)
    assert "4 UK companies found" in notes[-1]


async def test_register_check_is_off_without_a_buyer_model_or_key() -> None:
    candidates = [importer("New Imports Ltd", new=False)]

    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
        kept, _, notes = await register_check(
            candidates, spec(buyer_roles=[]), http=http, as_of=NOW, settings=SETTINGS
        )
        assert kept == candidates and notes == []
        kept, _, notes = await register_check(
            candidates, spec(), http=http, as_of=NOW, settings=Settings(_env_file=None)
        )
        assert kept == candidates and notes == []


async def test_labels_and_daily_edition() -> None:
    async with httpx.AsyncClient(transport=register(PROFILES)) as http:
        kept, _, _ = await register_check(
            [importer("New Imports Ltd", new=False), importer("Old Imports Ltd", new=False)],
            spec(),
            http=http,
            as_of=NOW,
            settings=SETTINGS,
        )
    plain = importer("Plain Imports Ltd", new=False)
    entries = brief.rank(
        [(c, gate(), UNKNOWN) for c in [*kept, plain]], as_of=NOW, settings=SETTINGS
    )
    labelled = {e.candidate.name: e for e in label_entries(entries, NOW.date(), SETTINGS)}
    assert labelled["New Imports Ltd"].label == "just_changed"
    assert labelled["New Imports Ltd"].label_reason == "set up on 2025-06-01"
    assert labelled["Old Imports Ltd"].label == "just_changed"
    assert "NEW OWNER GROUP LIMITED" in (labelled["Old Imports Ltd"].label_reason or "")
    assert labelled["Old Imports Ltd"].label_strength == 1
    assert labelled["Plain Imports Ltd"].label == "account_to_work"

    edition = daily_edition(list(labelled.values()), SETTINGS)
    # mix: at most 2 just_changed and 2 account_to_work; never padded
    assert [e.label for e in edition].count("just_changed") == 2
    assert len(edition) == 3


def test_daily_edition_never_pads() -> None:
    assert daily_edition([], SETTINGS) == []
