"""Checkpoint A (D57): the extractor names the company, proved on the real recordings.

Replays `tests/fixtures/llm/ledger/` (re-recorded by the orchestrator with prompt v2; until then
every test here fails with `LlmReplayMismatch`, which is expected). Nothing here edits a recording.

Thresholds (PLAN.md, Checkpoint A):
- at least 2/3 of events from extracted (non-structured) documents carry a grounded subject;
- every full-text document with a verified claim whose subject name is inside its own quote
  yields at least one event with a grounded subject.

A subject kept on an event is grounded by construction (`ground_event`, D50); the first test also
re-derives that from the verified quotes so the proof does not rest on the pipeline's own word.
"""

from __future__ import annotations

from northvaine.core.models import EvidenceKind
from northvaine.radar.quote_check import quote_contains
from tests.radar.test_ledger_replay import (  # noqa: F401  (the autouse fixture must apply here too)
    GROUPS,
    DocRun,
    _no_dotenv,
    replay_group,
)

MIN_FILL = 2 / 3


async def extracted_runs() -> list[tuple[str, DocRun]]:
    out = []
    for group in GROUPS:
        run = await replay_group(group)
        out += [
            (group, r)
            for r in run.runs
            if r.result.eligibility.kind not in (EvidenceKind.STRUCTURED, EvidenceKind.LEAD)
        ]
    return out


def verified_quotes(run: DocRun, fingerprints: list[str]) -> list[str]:
    by_fp = {c.fingerprint: c for c in run.result.checks if c.verified}
    return [by_fp[fp].draft.source_quote for fp in fingerprints if fp in by_fp]


async def test_most_extracted_events_carry_a_grounded_subject() -> None:
    runs = await extracted_runs()
    events = [(g, r, e) for g, r in runs for e in r.result.events]
    assert events, "no extracted events in the recordings"
    named = 0
    for group, r, e in events:
        if e.subject is None:
            continue
        quotes = verified_quotes(r, e.claim_fingerprints)
        assert any(quote_contains(q, e.subject.name) for q in quotes), (group, r.doc.url, e.subject)
        named += 1
    fill = named / len(events)
    print(f"\nsubject fill: {named}/{len(events)} = {fill:.0%} of extracted events")
    assert fill >= MIN_FILL


async def test_a_named_organisation_in_a_verified_quote_yields_a_grounded_subject() -> None:
    misses = []
    checked = 0
    for group, r in await extracted_runs():
        if r.result.eligibility.kind != EvidenceKind.FULL_TEXT or not r.result.events:
            continue
        named = [
            c.draft.subject.name
            for c in r.result.checks
            if c.verified
            and c.draft.subject is not None
            and quote_contains(c.draft.source_quote, c.draft.subject.name)
        ]
        if not named:
            continue
        checked += 1
        if not any(e.subject is not None for e in r.result.events):
            misses.append((group, r.doc.url, named))
    print(f"\nfull-text documents with a grounded organisation: {checked}, misses: {len(misses)}")
    assert checked >= 1, "no full-text document named an organisation in a verified quote"
    assert not misses, misses
