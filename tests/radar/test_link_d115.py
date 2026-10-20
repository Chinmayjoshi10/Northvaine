"""D115: the same company linked across sources by registration number. Invented companies; no
network, no model."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from northvaine.brain.replay import LEGACY_SETTINGS
from northvaine.core.settings import Settings
from northvaine.radar.brief import apply_fit_order
from northvaine.radar.models import (
    Candidate,
    CandidateEvent,
    RadarStream,
    RegisterFacts,
)
from northvaine.radar.register import merge_by_register, register_check
from tests.radar.test_fit_d108 import named
from tests.radar.test_register_edition import NOW, PROFILES, SETTINGS, register, spec
from tests.radar.test_trade_stream import claim, importer


def with_number(c: Candidate, number: str | None) -> Candidate:
    facts = RegisterFacts(number=number, status="active") if number else None
    return c.model_copy(update={"company_register": facts})


def award(name: str) -> Candidate:
    k1 = claim("C1", f"Awarded to {name}").model_copy(update={"fingerprint": "aw-1"})
    k2 = claim("C2", "Contract value stated").model_copy(update={"fingerprint": "aw-2"})
    return Candidate(
        key=name.lower(),
        name=name,
        country="GB",
        aliases=[],
        roles=["contractor"],
        stream=RadarStream.AWARD,
        streams=[RadarStream.AWARD],
        events=[
            CandidateEvent(
                event_type="contract_awarded",
                description="won a contract",
                occurred_on=date(2026, 9, 1),
                available_at=None,
                claim_refs=["C2", "C1"],
                slots={},
                fingerprint="ev-award",
            )
        ],
        claims=[k1, k2],
        window_start=date(2026, 9, 1),
        window_end=date(2026, 12, 1),
        window_estimated=False,
        window_note="",
        like_customers=["like a"],
        timing_signals=["sig a"],
    )


def test_same_number_merges_with_renumbered_refs() -> None:
    trade = with_number(importer("Stone Imports Limited", new=False), "00000009")
    won = with_number(award("Stone Imports Ltd"), "00000009")
    out, absorbed = merge_by_register([won, trade])
    assert absorbed == 1 and len(out) == 1
    m = out[0]
    assert m.name == "Stone Imports Limited" and m.stream == RadarStream.TRADE  # trade is primary
    assert m.aliases == ["Stone Imports Ltd"]
    assert m.streams == [RadarStream.TRADE, RadarStream.AWARD]
    assert [k.ref for k in m.claims] == [f"C{i}" for i in range(1, 7)]
    assert m.claims[4].source_quote == "Awarded to Stone Imports Ltd"
    assert m.claims[4].document_id == won.claims[0].document_id
    assert m.claims[5].document_id == won.claims[1].document_id
    ev = next(e for e in m.events if e.event_type == "contract_awarded")
    assert ev.claim_refs == ["C6", "C5"]
    assert len(m.events) == 2
    assert m.window_start == date(2026, 5, 1) and m.window_end == date(2026, 12, 1)
    assert m.like_customers == ["like a"] and m.timing_signals == ["sig a"]


def test_without_trade_most_claims_is_primary_and_shared_lines_not_repeated() -> None:
    a = with_number(award("Alpha Works Ltd"), "5")
    b = with_number(award("Alpha Works Limited"), "5")
    extra = claim("C3", "Status: active").model_copy(update={"fingerprint": "aw-3"})
    b = b.model_copy(update={"claims": [*b.claims, extra]})
    out, _ = merge_by_register([a, b])
    assert out[0].name == "Alpha Works Limited"
    # both share fingerprints aw-1 and aw-2: only the primary's three claims remain
    assert [k.ref for k in out[0].claims] == ["C1", "C2", "C3"]
    assert len(out[0].events) == 1


def test_different_or_missing_numbers_do_not_merge() -> None:
    a = with_number(importer("One Ltd", new=False), "1")
    b = with_number(award("Two Ltd"), "2")
    c = with_number(award("Three Ltd"), None)
    d = with_number(award("Four Ltd"), None)
    out, absorbed = merge_by_register([a, b, c, d])
    assert absorbed == 0 and out == [a, b, c, d]


async def lookups_order(settings: Settings) -> list[str]:
    seen: list[str] = []
    base = register(PROFILES)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/companies":
            seen.append(request.url.params["q"])
        return base.handler(request)  # type: ignore[attr-defined]

    candidates = [
        importer("Aaa Imports Ltd", new=False),
        importer("New Imports Ltd", new=True),
        award("Zzz Works Ltd"),
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        await register_check(candidates, spec(), http=http, as_of=NOW, settings=settings)
    return seen


async def test_non_trade_looked_up_first_under_the_cap() -> None:
    capped = SETTINGS.model_copy(update={"radar_register_max_lookups": 1})
    assert await lookups_order(capped) == ["Zzz Works Ltd"]
    legacy = capped.model_copy(update={"radar_link_by_register": False})
    assert await lookups_order(legacy) == ["Aaa Imports Ltd"]


def streamed(key: str, rank: int, streams: list[RadarStream]) -> Any:
    base = named(key, {"codes": "1"}, rank=rank)
    c = base.candidate.model_copy(update={"streams": streams})
    return base.model_copy(update={"candidate": c, "evidence_level": "project_requirement"})


def test_two_sources_rank_above_one_within_level_and_fit_group() -> None:
    one = [RadarStream.TRADE]
    two = [RadarStream.TRADE, RadarStream.AWARD]
    entries = [streamed("a", 1, one), streamed("b", 2, two)]
    out = apply_fit_order(entries, 180, True)
    assert [e.candidate.key for e in out] == ["b", "a"]
    assert "Sources: seen in import records, contract award" in out[0].rank_reasons
    assert not any(r.startswith("Sources") for r in out[1].rank_reasons)
    off = apply_fit_order(entries, 180, False)
    assert [e.candidate.key for e in off] == ["a", "b"]
    assert not any(r.startswith("Sources") for e in off for r in e.rank_reasons)


async def test_legacy_off_does_not_merge() -> None:
    assert LEGACY_SETTINGS["radar_link_by_register"] is False
    # both resolve to the same register number through an exact-name lookup
    a = importer("New Imports Ltd", new=True)
    b = award("New Imports Ltd").model_copy(update={"key": "new imports ltd award"})
    for on, expected in ((True, 1), (False, 2)):
        settings = SETTINGS.model_copy(update={"radar_link_by_register": on})
        async with httpx.AsyncClient(transport=register(PROFILES)) as http:
            kept, _, notes = await register_check(
                [a, b], spec(), http=http, as_of=NOW, settings=settings
            )
        assert len(kept) == expected
        assert any("linked 1 companies" in n for n in notes) == on
