"""D111: timing signals from free official records. Invented companies; no network, no model."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from northvaine.brain.replay import LEGACY_SETTINGS
from northvaine.core.settings import Settings
from northvaine.radar.brief import apply_fit_order
from northvaine.radar.models import Candidate, RankedEntry, RegisterFacts
from northvaine.radar.register import register_check
from northvaine.radar.timing import timing_signals
from northvaine.sensors.companies_house import (
    CompaniesHouseClient,
    RegisterRecord,
    parse_charges,
    parse_office_moves,
    render_register_text,
)
from tests.radar.test_fit_d108 import named
from tests.radar.test_register_edition import NOW, PROFILES, SETTINGS, register, spec
from tests.radar.test_trade_stream import importer

CHARGES = {
    "items": [
        {
            "created_on": "2026-08-14",
            "status": "outstanding",
            "persons_entitled": [{"name": "A LENDER PLC"}],
        },
        {"created_on": "2019-01-01", "status": "fully-satisfied"},
    ]
}
HISTORY = {
    "items": [
        {"date": "2026-09-01", "type": "AD01", "description": "change-registered-office-address"},
        {"date": "2026-09-20", "type": "AD02"},
    ]
}
RECORD = RegisterRecord(number="00000001", name="NEW IMPORTS LTD", status="active")


def facts(**kw: Any) -> RegisterFacts:
    return RegisterFacts(number="1", status="active", **kw)


def client_for(handler: Any) -> tuple[CompaniesHouseClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CompaniesHouseClient(client=http, settings=SETTINGS), http


async def test_charges_and_history_parsed_without_names() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/charges"):
            return httpx.Response(200, json=CHARGES)
        assert request.url.params["category"] == "address"
        return httpx.Response(200, json=HISTORY)

    client, http = client_for(respond)
    async with http:
        record, notes = await client.timing(RECORD)
    assert record.charge_created_on == date(2026, 8, 14)
    assert record.office_moved_on == date(2026, 9, 1)  # only AD01 counts
    assert notes == []
    assert parse_charges(CHARGES) == [
        (date(2026, 8, 14), "outstanding"),
        (date(2019, 1, 1), "fully-satisfied"),
    ]
    assert "LENDER" not in repr(record) and "LENDER" not in render_register_text(record)
    assert "Charge registered: 2026-08-14" in render_register_text(record)


async def test_404_is_none_and_errors_are_notes() -> None:
    client, http = client_for(lambda r: httpx.Response(404))
    async with http:
        record, notes = await client.timing(RECORD)
    assert record.charge_created_on is None and record.office_moved_on is None and notes == []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/charges"):
            return httpx.Response(500)
        return httpx.Response(200, json=HISTORY)

    client, http = client_for(respond)
    async with http:
        record, notes = await client.timing(RECORD)
    assert record.charge_created_on is None and record.office_moved_on == date(2026, 9, 1)
    assert len(notes) == 1 and "charges not read" in notes[0]
    assert parse_office_moves(None) is None


def timed_register() -> httpx.MockTransport:
    base = register(PROFILES)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/charges"):
            return httpx.Response(200, json=CHARGES)
        if request.url.path.endswith("/filing-history"):
            return httpx.Response(200, json=HISTORY)
        return base.handler(request)  # type: ignore[attr-defined]

    return httpx.MockTransport(respond)


async def run_check(settings: Settings) -> list[Candidate]:
    candidates = [importer("New Imports Ltd", new=True), importer("Old Imports Ltd", new=False)]
    async with httpx.AsyncClient(transport=timed_register()) as http:
        kept, _, _ = await register_check(
            candidates, spec(), http=http, as_of=NOW, settings=settings
        )
    return kept


async def test_register_check_adds_claims_and_signals() -> None:
    kept = await run_check(SETTINGS)
    new = next(c for c in kept if c.name == "New Imports Ltd")
    quotes = [k.source_quote for k in new.claims if k.source_name == "companies_house"]
    assert "Charge registered: 2026-08-14" in quotes
    assert "Registered office changed: 2026-09-01" in quotes
    assert new.company_register is not None
    assert new.company_register.charge_created_on == date(2026, 8, 14)
    assert any("charge" in s.lower() for s in new.timing_signals)
    assert any("started importing" in s for s in new.timing_signals)


async def test_lookups_capped_and_legacy_zero_makes_none() -> None:
    capped = SETTINGS.model_copy(update={"radar_timing_max_lookups": 1})
    kept = await run_check(capped)
    with_charge = [c for c in kept if c.company_register and c.company_register.charge_created_on]
    assert len(with_charge) == 1
    assert LEGACY_SETTINGS["radar_timing_max_lookups"] == 0
    none = await run_check(SETTINGS.model_copy(update={"radar_timing_max_lookups": 0}))
    assert all(c.timing_signals == [] for c in none)
    assert all(c.company_register and c.company_register.charge_created_on is None for c in none)


def test_signals_within_and_outside_the_window() -> None:
    c = importer("Some Imports Ltd", new=False).model_copy(
        update={
            "company_register": facts(
                charge_created_on=date(2026, 8, 14),
                office_moved_on=date(2025, 1, 1),  # too old
                control_changed_on=date(2026, 7, 10),
                renamed_on=date(2026, 12, 1),  # in the future: not a signal
                incorporated=date(2026, 6, 1),
            )
        }
    )
    out = timing_signals(c, date(2026, 10, 16), 180)
    assert out == [
        "A charge (new finance) was registered on 2026-08-14",
        "Control changed on 2026-07-10",
        "It was incorporated on 2026-06-01",
    ]
    assert timing_signals(c, date(2026, 10, 16), 30) == []


def signalled(e: RankedEntry, rank: int, key: str, n: int, like: bool = False) -> RankedEntry:
    c = e.candidate.model_copy(
        update={
            "key": key,
            "timing_signals": [f"signal {i}" for i in range(n)],
            "like_customers": ["like x"] * like,
        }
    )
    return e.model_copy(
        update={"rank": rank, "candidate": c, "evidence_level": "project_requirement"}
    )


def test_two_signals_rank_above_one_after_fit() -> None:
    base = named("k", {"codes": "1"})
    entries = [
        signalled(base, 1, "a", 1),
        signalled(base, 2, "b", 2),
        signalled(base, 3, "c", 0, like=True),
        signalled(base, 4, "d", 3, like=True),
    ]
    out = apply_fit_order(entries, 180)
    assert [e.candidate.key for e in out] == ["d", "b", "c", "a"]
    assert "Timing: 3 signals in the last 180 days" in out[0].rank_reasons
    assert not any(r.startswith("Timing") for r in out[2].rank_reasons)
