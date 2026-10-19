"""D109: customers like yours. Invented companies; no network, no model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from northvaine.api.store import approved_leads
from northvaine.brain.replay import LEGACY_SETTINGS
from northvaine.radar import fit as fit_module
from northvaine.radar.brief import apply_fit_order
from northvaine.radar.entities import company_key
from northvaine.radar.models import Candidate, RankedEntry, RegisterFacts
from northvaine.radar.register import (
    SeedProfile,
    mark_likeness,
    note_import_profile,
    product_families,
    seed_register_profiles,
)
from tests.radar.test_fit_d108 import named
from tests.radar.test_register_edition import PROFILES, SETTINGS, register, spec
from tests.radar.test_trade_stream import importer


def key_of(name: str) -> str:
    return company_key(name, None, SETTINGS)


def profiles(*seeds: tuple[str, bool]) -> dict[str, SeedProfile]:
    return {key_of(n): SeedProfile(name=n, key=key_of(n), private=p) for n, p in seeds}


def with_register(c: Candidate, sics: list[str]) -> Candidate:
    facts = RegisterFacts(
        number="1",
        status="active",
        incorporated=None,
        sic_codes=sics,
        renamed_on=None,
        controlled_by=[],
        control_changed_on=None,
    )
    return c.model_copy(update={"company_register": facts})


def test_families_keep_scheme_and_four_digits() -> None:
    assert product_families("hs:690721, hs:690722, cpv:44112, 6907") == {
        "hs:6907",
        "cpv:4411",
        "6907",
    }
    assert product_families("") == set()


def test_sic_match_never_names_an_existing_customer() -> None:
    seeds = profiles(("Secret Customer Ltd", True))
    seeds[key_of("Secret Customer Ltd")].sics = {"46900"}
    out = mark_likeness([with_register(importer("Newco Ltd", new=False), ["46900"])], seeds, key_of)
    assert out[0].like_customers == [
        "Same registered business activity (SIC 46900) as one of your customers"
    ]
    assert "Secret" not in " ".join(out[0].like_customers)


def test_an_approved_lead_may_be_named() -> None:
    seeds = profiles(("Good Lead Ltd", False))
    seeds[key_of("Good Lead Ltd")].sics = {"46900"}
    out = mark_likeness([with_register(importer("Newco Ltd", new=False), ["46900"])], seeds, key_of)
    assert "Good Lead Ltd" in out[0].like_customers[0]


def test_import_family_match_and_seed_is_read_before_it_is_filtered() -> None:
    # the customer appears in this run's import records: its families are noted
    seeds = profiles(("Secret Customer Ltd", True))
    note_import_profile(seeds, [importer("Secret Customer Ltd", new=False)], key_of)
    assert seeds[key_of("Secret Customer Ltd")].families == {"1234"}
    out = mark_likeness([importer("Other Importer Ltd", new=True)], seeds, key_of)
    assert out[0].like_customers == ["Imports the same product families as one of your customers"]


def test_a_candidate_is_not_like_itself_and_no_seeds_changes_nothing() -> None:
    cand = importer("Good Lead Ltd", new=False)
    seeds = profiles(("Good Lead Ltd", False))
    note_import_profile(seeds, [cand], key_of)
    assert mark_likeness([cand], seeds, key_of) == [cand]
    assert mark_likeness([cand], {}, key_of) == [cand]


async def test_seed_lookups_keep_sic_codes_and_are_capped() -> None:
    seeds = profiles(
        ("New Imports Ltd", True), ("Old Imports Ltd", True), ("Closed Imports Ltd", True)
    )
    cfg = SETTINGS.model_copy(update={"radar_seed_max_lookups": 2})
    async with httpx.AsyncClient(transport=register(PROFILES)) as http:
        notes = await seed_register_profiles(
            seeds, [], spec(), http=http, key_of=key_of, settings=cfg
        )
    looked = [p for p in seeds.values() if p.sics]
    assert len(looked) == 2 and looked[0].sics == {"46900"}
    assert notes == ["customers like yours: 2 of 2 seed(s) found at Companies House"]


async def test_legacy_setting_zero_makes_no_lookups() -> None:
    assert LEGACY_SETTINGS["radar_seed_max_lookups"] == 0
    seeds = profiles(("New Imports Ltd", True))
    cfg = SETTINGS.model_copy(update={"radar_seed_max_lookups": 0})

    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
        notes = await seed_register_profiles(
            seeds, [], spec(), http=http, key_of=key_of, settings=cfg
        )
    assert notes == []


async def test_a_failed_seed_lookup_is_a_note_never_an_error() -> None:
    seeds = profiles(("New Imports Ltd", True))

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
        notes = await seed_register_profiles(
            seeds, [], spec(), http=http, key_of=key_of, settings=SETTINGS
        )
    assert len(notes) == 1 and notes[0].startswith("customers like yours: 0 of 1")


def liked(e: RankedEntry, rank: int, key: str, like: bool) -> RankedEntry:
    c = e.candidate.model_copy(
        update={"key": key, "like_customers": ["Imports the same product families as x"] * like}
    )
    return e.model_copy(
        update={"rank": rank, "candidate": c, "evidence_level": "project_requirement"}
    )


def test_likeness_breaks_ties_after_fit_and_renumbers() -> None:
    base = named("k", {"codes": "1"})
    entries = [
        liked(base, 1, "a", False),
        liked(base, 2, "b", True),
        liked(base, 3, "c", False),
        liked(base, 4, "d", True),
    ]
    out = apply_fit_order(entries)
    assert [e.candidate.key for e in out] == ["b", "d", "a", "c"]
    assert [e.rank for e in out] == [1, 2, 3, 4]
    assert "Imports the same product families as x" in out[0].rank_reasons
    assert out[2].rank_reasons == []


def test_no_likeness_keeps_the_order() -> None:
    base = named("k", {"codes": "1"})
    entries = [liked(base, i, f"k{i}", False) for i in range(1, 4)]
    assert [e.candidate.key for e in apply_fit_order(entries)] == ["k1", "k2", "k3"]


def test_fit_checks_like_customers_before_import_depth() -> None:
    shallow = liked(named("a", {"codes": "6801", "months_active": 1}, rank=2), 2, "a", True)
    deep = named("b", {"codes": "6801,6802,6803", "months_active": 9}, rank=1)
    shallow = shallow.model_copy(update={"account_role": "importer_of_record"})
    order = fit_module._fit_order([deep, shallow])
    assert [e.candidate.key for e in order] == ["a", "b"]


def test_approved_leads_use_accepted_for_contact_latest_answer(tmp_path: Path) -> None:
    rows: list[dict[str, Any]] = [
        {"company": "Yes Ltd", "accepted_for_contact": True},
        {"company": "Changed Ltd", "accepted_for_contact": True},
        {"company": "Changed Ltd", "accepted_for_contact": False},
        {"company": "Later Ltd", "accepted_for_contact": None, "actionable": False},
        {"company": "Yes Ltd", "accepted_for_contact": None, "note": "wrong step"},
    ]
    folder = tmp_path / "c1"
    folder.mkdir()
    path = next(iter(_feedback_paths(tmp_path, "c1")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert approved_leads(tmp_path, "c1") == ["Yes Ltd"]


def _feedback_paths(base: Path, client: str) -> list[Path]:
    from northvaine.api.store import feedback_path

    return [feedback_path(base, client)]
