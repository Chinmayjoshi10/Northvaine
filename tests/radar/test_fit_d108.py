"""D108: one search a company, importers chosen by depth, the company's own contact, fit order."""

from __future__ import annotations

from typing import Any

from northvaine.core.settings import Settings
from northvaine.radar import fit as fit_module
from northvaine.radar.brief import apply_fit_order
from northvaine.radar.fit import company_fit, find_company_contact
from northvaine.radar.models import (
    CandidateEvent,
    CompanyContact,
    FitEvidence,
    RadarStream,
    RankedEntry,
)
from northvaine.sensors.base import SensorResult
from tests.radar.test_fit import NOW, SETTINGS, SPEC, FakeFetcher, FakeSensor, entry

SINGLE = Settings(_env_file=None)
ROLES = set(SINGLE.fit_contact_role_words)


def named(key: str, slots: dict[str, Any] | None = None, rank: int = 1) -> RankedEntry:
    e = entry("importer_of_record", RadarStream.TRADE)
    events = (
        [
            CandidateEvent(
                event_type="imports_recorded",
                description="d",
                occurred_on=None,
                available_at=None,
                claim_refs=[],
                slots=slots,
                fingerprint="f",
            )
        ]
        if slots
        else []
    )
    c = e.candidate.model_copy(update={"key": key, "events": events})
    return e.model_copy(update={"candidate": c, "rank": rank})


class CountingSensor(FakeSensor):
    def __init__(self) -> None:
        super().__init__([])

    async def search(self, query: Any) -> SensorResult:
        self.queries.append(query)
        return SensorResult(documents=[], notes=[], enumerable=False)


async def test_one_search_per_company_and_at_most_fifteen(monkeypatch: Any) -> None:
    sensor = CountingSensor()
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    entries = [named(f"GB:co{i}", rank=i + 1) for i in range(20)]
    await company_fit(entries, SPEC, http=None, fetcher=FakeFetcher({}), as_of=NOW, settings=SINGLE)
    assert len(sensor.queries) == 15
    assert sensor.queries[0].text == "Raffalli TP granite"
    assert sensor.queries[0].max_results == 5


async def test_importers_are_chosen_by_import_depth(monkeypatch: Any) -> None:
    sensor = CountingSensor()
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    cfg = Settings(_env_file=None, radar_fit_max_accounts=1)
    shallow = named("GB:a", {"codes": "6801", "months_active": 9}, rank=1)
    deep = named("GB:b", {"codes": "6801,6802,6803", "months_active": 2}, rank=2)
    # the shallow one is first by rank, but only the deep one is checked
    checked = fit_module._fit_order([shallow, deep])
    assert [e.candidate.key for e in checked] == ["GB:b", "GB:a"]
    await company_fit([shallow, deep], SPEC, http=None, fetcher=FakeFetcher({}), as_of=NOW,
                      settings=cfg)  # fmt: skip
    assert len(sensor.queries) == 1


async def test_single_search_reads_domain_pages_and_the_company_contact(monkeypatch: Any) -> None:
    sensor = FakeSensor([["https://www.raffalli-tp.fr/a", "https://www.raffalli-tp.fr/b"]])
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    pages = {
        "https://www.raffalli-tp.fr/a": "Raffalli TP pose du granite pour les places publiques.",
        "https://www.raffalli-tp.fr/b": "Autre page sans rien de plus a dire ici.",
        "https://www.raffalli-tp.fr/contact": "Write to info@raffalli-tp.fr or +33 4 95 12 34 56.",
    }
    out, _ = await company_fit(
        [entry("awarded_contractor")], SPEC, http=None, fetcher=FakeFetcher(pages),
        as_of=NOW, settings=SINGLE,
    )  # fmt: skip
    assert len(sensor.queries) == 1
    assert out[0].fit_level == "stated"
    assert out[0].company_contact == CompanyContact(
        email="info@raffalli-tp.fr",
        phone="+33 4 95 12 34 56",
        url="https://www.raffalli-tp.fr/contact",
    )


def test_contact_keeps_role_email_on_own_domain_only() -> None:
    text = (
        "Ask j.smith@acme.com, sales@other.com or sales@acme.com. Phone 020 7946 0958 today. "
        "Updated 2026-10-09."
    )
    found = find_company_contact([("https://acme.com/c", text)], "acme.com", ROLES)
    assert found is not None
    assert found.email == "sales@acme.com"
    assert found.phone == "020 7946 0958"


def test_contact_drops_personal_address_and_finds_nothing_without_contacts() -> None:
    assert find_company_contact([("u", "mail j.smith@acme.com")], "acme.com", ROLES) is None
    plain = "We lay paving. Founded 2012-05-01."
    assert find_company_contact([("u", plain)], "acme.com", ROLES) is None


async def test_legacy_flag_keeps_the_two_search_path(monkeypatch: Any) -> None:
    sensor = FakeSensor([["https://www.raffalli-tp.fr/"], ["https://www.raffalli-tp.fr/x"]])
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    page = "Du granite pour les places publiques et les rues."
    out, _ = await company_fit(
        [entry("awarded_contractor")], SPEC, http=None,
        fetcher=FakeFetcher({"https://www.raffalli-tp.fr/x": page}),
        as_of=NOW, settings=SETTINGS,
    )  # fmt: skip
    assert len(sensor.queries) == 2 and out[0].company_contact is None


def _ranked(rank: int, level: str, fit: str | None, site: bool) -> RankedEntry:
    e = entry("awarded_contractor")
    evidence = (
        [FitEvidence(url="u", quote="q", term="granite", level=fit, fingerprint="f")]  # type: ignore[arg-type]
        if fit
        else []
    )
    return e.model_copy(
        update={
            "rank": rank,
            "evidence_level": level,
            "company_site": "x.fr" if site else None,
            "fit_level": fit,
            "company_fit": evidence,
            "candidate": e.candidate.model_copy(update={"key": f"k{rank}"}),
        }
    )


def test_fit_order_works_within_an_evidence_level_and_renumbers() -> None:
    entries = [
        _ranked(1, "project_requirement", None, False),  # not checked
        _ranked(2, "project_requirement", None, True),  # site does not name it
        _ranked(3, "no_evidence", None, False),
        _ranked(4, "project_requirement", "stated", True),
        _ranked(5, "project_requirement", "related", True),
    ]
    out = apply_fit_order(entries)
    # the project_requirement slots (1, 2, 4, 5) are refilled: stated, related, unchecked, no fit
    assert [e.candidate.key for e in out] == ["k4", "k5", "k3", "k1", "k2"]
    assert [e.rank for e in out] == [1, 2, 3, 4, 5]
    assert "Company fit: its own site names granite" in out[0].rank_reasons
    assert "Company fit: its own site does not name what you sell" in out[4].rank_reasons
    assert out[3].rank_reasons == []  # not checked: no reason added


def test_contact_text_never_reaches_a_recording() -> None:
    from northvaine.radar.models import UpgradedPage

    page = UpgradedPage(
        lead_url="https://example.test/",
        final_url=None,
        status=200,
        fetched_at=None,
        title=None,
        text="stripped",
        refused=None,
        contact_text="write to info@example.test",
    )
    assert page.contact_text and "contact_text" not in page.model_dump()
    assert "info@" not in page.model_dump_json()
