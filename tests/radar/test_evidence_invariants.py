"""T4.6: the evidence invariants, checked end to end on the replayed recordings (no network).

Rule #2 (no source, no claim) and D50 (every event field is grounded in a verified quote) are
re-derived here with the REAL `find_quote` and the standards helpers, independent of the pipeline's
own bookkeeping. The replayed results come from `test_ledger_replay.replay_group`.

Facts about the recorded data these tests deliberately do not hide (they are printed or noted, not
fixed): since extractor v3 (T5.1) most extracted events carry a grounded subject, but event types
are still loose on news-index pages (an investment announcement can be typed `contract_awarded`);
the M5 gate and skeptic, not these tests, are where that is judged.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from northvaine.core.models import (
    ClaimCheck,
    ClaimStatus,
    EvidenceKind,
    PendingEvent,
    QuoteMode,
)
from northvaine.core.settings import Settings
from northvaine.core.standards import iso2_to_iso3, iso2_to_name
from northvaine.radar.ledger import describe_event, event_fingerprint
from northvaine.radar.quote_check import find_quote, normalize_text, quote_contains
from northvaine.radar.verify import claim_fingerprint
from tests.radar.test_ledger_replay import (  # noqa: F401  (the autouse fixture must apply here too)
    GROUPS,
    DocRun,
    GroupRun,
    _no_dotenv,
    replay_group,
)

DEFAULTS = Settings(_env_file=None)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def mode_for(run: DocRun) -> QuoteMode:
    if run.result.eligibility.kind == EvidenceKind.STRUCTURED:
        return QuoteMode.STRUCTURED
    return QuoteMode.EXTRACTED


def verified(run: DocRun) -> list[ClaimCheck]:
    return [c for c in run.result.checks if c.verified]


def event_checks(event: PendingEvent, run: DocRun) -> list[ClaimCheck]:
    """The claim checks an event cites, by fingerprint (every fingerprint must resolve)."""
    by_fp = {c.fingerprint: c for c in run.result.checks}
    return [by_fp[fp] for fp in event.claim_fingerprints]


def quotes_of(event: PendingEvent, run: DocRun) -> list[str]:
    return [c.draft.source_quote for c in event_checks(event, run)]


def date_in(day: date, quotes: list[str]) -> bool:
    """The date is written in a quote as ISO text (the form every recorded source uses)."""
    return any(day.isoformat() in normalize_text(q) for q in quotes)


def token_in(token: str, quotes: list[str]) -> bool:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])"
    return any(re.search(pattern, normalize_text(q), re.IGNORECASE) for q in quotes)


def country_in(code: str, quotes: list[str]) -> bool:
    return (
        token_in(code, quotes)
        or token_in(iso2_to_iso3(code), quotes)
        or any(quote_contains(q, iso2_to_name(code)) for q in quotes)
    )


async def all_runs() -> list[tuple[str, DocRun]]:
    out = []
    for group in GROUPS:
        run: GroupRun = await replay_group(group)
        out += [(group, r) for r in run.runs]
    return out


# --- claims ---------------------------------------------------------------------------------


async def test_the_replay_has_real_material_to_check() -> None:
    runs = await all_runs()
    assert sum(len(verified(r)) for _, r in runs) >= 100
    assert sum(len(r.result.events) for _, r in runs) >= 50
    kinds = {r.result.eligibility.kind for _, r in runs}
    assert kinds == {EvidenceKind.STRUCTURED, EvidenceKind.FULL_TEXT, EvidenceKind.LEAD}
    # some extracted claims were rejected, so the reject paths are exercised too
    statuses = {c.status for _, r in runs for c in r.result.checks}
    # Which reject reasons occur depends on the recording; each one has its own unit tests.
    assert ClaimStatus.VERIFIED in statuses
    assert statuses & {
        ClaimStatus.UNSUPPORTED,
        ClaimStatus.QUOTE_NOT_FOUND,
        ClaimStatus.QUOTE_TOO_SHORT,
    }


async def test_every_verified_claim_is_found_in_its_snapshot_at_the_stored_offset() -> None:
    for group, r in await all_runs():
        for c in verified(r):
            match = find_quote(r.doc.text, c.draft.source_quote, mode=mode_for(r))
            where = f"{group} {r.doc.url}: {c.draft.source_quote!r}"
            assert match.found, f"verified claim not found in its document: {where}"
            assert match.offset == c.quote_offset, where
            assert c.quote_offset is not None and c.verified_by, where
            assert c.document_id == r.doc.id


async def test_verified_by_tells_how_a_claim_was_verified() -> None:
    for _, r in await all_runs():
        for c in verified(r):
            structured = r.result.eligibility.kind == EvidenceKind.STRUCTURED
            expected = "code" if structured else "code+llm"
            assert c.verified_by == expected, r.doc.url


async def test_the_code_quote_check_always_runs_before_the_model_is_asked() -> None:
    """A claim the model rejected (`unsupported`) must have passed the code check, and a claim
    that failed the code check carries a code-check reason, never a model verdict."""
    for _, r in await all_runs():
        for c in r.result.checks:
            match = find_quote(r.doc.text, c.draft.source_quote, mode=mode_for(r))
            if c.status == ClaimStatus.UNSUPPORTED:
                assert match.found and c.quote_offset == match.offset, r.doc.url
            elif c.status in (ClaimStatus.QUOTE_NOT_FOUND, ClaimStatus.QUOTE_TOO_SHORT):
                assert not match.found, f"{r.doc.url}: {c.draft.source_quote!r}"
                assert c.quote_offset is None and c.verified_by is None
                assert match.reason == c.status
            else:
                assert c.status == ClaimStatus.VERIFIED


async def test_a_claim_is_verified_only_with_a_complete_row() -> None:
    for _, r in await all_runs():
        for c in r.result.checks:
            assert c.verified == (c.status == ClaimStatus.VERIFIED)
            if c.verified:
                assert c.quote_offset is not None and c.verified_by
            else:
                assert c.verified_by is None
            assert c.fingerprint == claim_fingerprint(
                r.doc.id, c.draft.statement, c.draft.source_quote
            )


async def test_claim_fingerprints_are_unique_within_a_document() -> None:
    for _, r in await all_runs():
        fingerprints = [c.fingerprint for c in r.result.checks]
        assert len(fingerprints) == len(set(fingerprints)), r.doc.url


async def test_leads_produce_nothing() -> None:
    for _, r in await all_runs():
        if r.result.eligibility.kind == EvidenceKind.LEAD:
            assert r.result.checks == [] and r.result.events == []


# --- events ---------------------------------------------------------------------------------


async def test_every_event_cites_only_verified_claims() -> None:
    for group, r in await all_runs():
        verified_fps = {c.fingerprint for c in verified(r)}
        for e in r.result.events:
            assert e.claim_fingerprints, f"{group} {r.doc.url}: an event with no claim"
            assert set(e.claim_fingerprints) <= verified_fps, f"{group} {r.doc.url}"
            assert len(set(e.claim_fingerprints)) == len(e.claim_fingerprints)


async def test_every_event_date_is_written_in_one_of_its_verified_quotes() -> None:
    dated = 0
    for group, r in await all_runs():
        for e in r.result.events:
            if e.occurred_on is None:
                continue
            dated += 1
            assert date_in(e.occurred_on, quotes_of(e, r)), (
                f"{group} {r.doc.url}: {e.occurred_on} is in no verified quote of the event"
            )
    assert dated > 0


async def test_every_event_subject_and_country_are_grounded_in_its_quotes() -> None:
    subjects = 0
    for group, r in await all_runs():
        for e in r.result.events:
            if e.subject is None:
                continue
            subjects += 1
            quotes = quotes_of(e, r)
            where = f"{group} {r.doc.url}: {e.subject}"
            assert any(quote_contains(q, e.subject.name) for q in quotes), where
            if e.subject.country is not None:
                assert country_in(e.subject.country, quotes), where
    assert subjects > 0


async def test_every_event_string_slot_is_grounded_in_its_quotes() -> None:
    """Slot values must sit in a verified quote of the event. The two keys the pipeline derives
    itself (`subject_key` from the grounded subject, `group_key` from the document or a quoted
    hint) are checked against their source instead."""
    checked = 0
    for group, r in await all_runs():
        structured = r.result.eligibility.kind == EvidenceKind.STRUCTURED
        for e in r.result.events:
            quotes = quotes_of(e, r)
            where = f"{group} {r.doc.url} ({e.event_type})"
            for name, value in e.slots.items():
                if not isinstance(value, str):
                    continue
                checked += 1
                if name == "subject_key":
                    assert e.subject is not None, where
                    assert value == normalize_text(e.subject.name).casefold().strip(), where
                elif name == "group_key" and structured:
                    assert value == r.doc.group_key, where  # an identifier from the record itself
                else:
                    assert any(quote_contains(q, value) for q in quotes), (
                        f"{where}: slot {name}={value!r} is in no verified quote"
                    )
    assert checked > 0


async def test_event_descriptions_are_composed_by_code_from_verified_statements() -> None:
    for group, r in await all_runs():
        unverified = {c.draft.statement for c in r.result.checks if not c.verified}
        verified_statements = {c.draft.statement for c in verified(r)}
        for e in r.result.events:
            statements = [c.draft.statement for c in event_checks(e, r)]
            assert e.description == describe_event(e.event_type, e.subject, statements), (
                f"{group} {r.doc.url}"
            )
            for statement in unverified - verified_statements:
                assert statement not in e.description, f"{group}: unverified text in a description"


async def test_event_fingerprints_follow_the_rule_and_are_unique() -> None:
    seen: dict[str, str] = {}
    for group, r in await all_runs():
        for e in r.result.events:
            subject_key = e.slots.get("subject_key")
            assert e.fingerprint == event_fingerprint(
                e.event_type, e.claim_fingerprints, e.occurred_on, subject_key
            ), f"{group} {r.doc.url}"
            assert e.fingerprint not in seen, (
                f"{group} {r.doc.url}: duplicate event fingerprint (first at {seen[e.fingerprint]})"
            )
            seen[e.fingerprint] = f"{group} {r.doc.url}"


async def test_event_availability_is_the_document_availability() -> None:
    for _, r in await all_runs():
        for e in r.result.events:
            assert e.available_at == r.doc.available_at
            assert e.details.get("document_id") == str(r.doc.id)
            if r.result.eligibility.kind == EvidenceKind.STRUCTURED:
                assert e.available_at is not None


async def test_event_types_and_concepts_come_from_the_seeded_data() -> None:
    settings = DEFAULTS
    for group, r in await all_runs():
        run: GroupRun = await replay_group(group)
        level0 = {c.label: c for c in run.concepts if c.level == 0}
        for e in r.result.events:
            assert e.event_type in level0, f"{group}: {e.event_type} is not a seeded type"
            if r.result.eligibility.kind == EvidenceKind.FULL_TEXT:
                assert e.event_type not in settings.extract_excluded_event_types
            parent = level0[e.event_type]
            if e.concept.level == 0:
                assert e.concept.concept_id == parent.id and not e.concept.is_new
            else:
                assert e.concept.level == 1 and e.concept.parent_id == parent.id
                assert e.concept.status == "proposed" or not e.concept.is_new
            assert e.cluster_id is not None


async def test_structured_events_of_one_record_share_a_cluster() -> None:
    """Records without an embedding cluster deterministically on (type, group key)."""
    for _, r in await all_runs():
        if r.result.eligibility.kind != EvidenceKind.STRUCTURED:
            continue
        by_type: dict[str, set[Any]] = {}
        for e in r.result.events:
            assert e.embedding is None
            by_type.setdefault(e.event_type, set()).add(e.cluster_id)
        for event_type, clusters in by_type.items():
            assert len(clusters) == 1, f"{r.doc.url}: {event_type} split into {len(clusters)}"


# --- TED: by code, no model -----------------------------------------------------------------


def ted_runs(runs: list[tuple[str, DocRun]]) -> list[tuple[str, DocRun]]:
    return [(g, r) for g, r in runs if r.doc.source_name == "ted"]


def names_a_winner(run: DocRun) -> bool:
    return bool(run.doc.meta.get("winners"))


async def test_every_ted_notice_yields_verified_claims_by_code_without_a_model() -> None:
    runs = ted_runs(await all_runs())
    assert len(runs) >= 50
    for group, r in runs:
        assert r.result.eligibility.kind == EvidenceKind.STRUCTURED
        assert len(verified(r)) >= 1, f"{group} {r.doc.url}: no verified claim"
        assert all(c.verified_by == "code" for c in verified(r))
        assert r.calls == [] and r.result.llm_calls == 0


async def test_every_ted_notice_with_a_named_party_yields_an_event_by_code() -> None:
    """A tender yields an event from its buyer, a contract award from each named winner."""
    missing = []
    for group, r in ted_runs(await all_runs()):
        if r.doc.meta.get("notice_kind") == "contract_awarded" and not names_a_winner(r):
            continue
        if not r.result.events:
            missing.append(f"{group} {r.doc.url}")
    assert missing == []


async def test_the_only_ted_notices_without_an_event_are_awards_that_name_no_winner() -> None:
    silent = [(g, r) for g, r in ted_runs(await all_runs()) if not r.result.events]
    assert silent, "the recordings are expected to include award notices without a winner"
    for group, r in silent:
        assert r.doc.meta.get("notice_kind") == "contract_awarded", f"{group} {r.doc.url}"
        assert not names_a_winner(r), f"{group} {r.doc.url}"
