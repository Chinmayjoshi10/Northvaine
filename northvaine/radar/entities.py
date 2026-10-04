"""Identify the company (T5.2, D58-D60, D68): one candidate per company, from verified claims only.

Code only: never imports `northvaine.brain.llm` (checked by scripts/check_invariants.py).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from northvaine.core.models import (
    ClaimCheck,
    EvidenceDocument,
    EvidenceKind,
    LedgerResult,
    PendingEvent,
    SubjectMention,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
    CandidateEvent,
    GateDecision,
    RadarStream,
    RejectedAs,
    RejectedEntry,
)
from northvaine.sensors.dates import parse_date

__all__ = ["build_candidates", "company_key", "stream_for", "subject_problem", "window_for"]

NO_COMPANY = "(no company named)"
_NO_COUNTRY = "--"
_PRIMARY_ORDER = (RadarStream.TENDER, RadarStream.ANNOUNCEMENT, RadarStream.AWARD)

# D68: generic words that make a "name" a description rather than a company. Not industry
# words. Overridable from settings (`radar_non_name_pronouns`, `radar_non_name_words`,
# `radar_name_max_words`) when those exist.
_DEFAULT_PRONOUNS = (
    "a an the this that these those our your their its my his her we it they he she you i "
    "one some any each every"
)
_DEFAULT_GENERIC = (
    "organization organisation company companies firm business entity party group client "
    "customer buyer seller supplier vendor provider contractor authority unknown none n a na"
)
_DEFAULT_MAX_WORDS = 14

_URL_LIKE = re.compile(r"^\S*\.[a-z]{2,}(?:[/:?#]\S*)?$", re.IGNORECASE)


def _words(settings: Settings, name: str, default: str) -> frozenset[str]:
    configured = getattr(settings, name, None)
    return frozenset(configured if configured else default.split())


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\W_]+", " ", folded).strip()


def _form_sequences(settings: Settings) -> list[tuple[str, ...]]:
    forms = {tuple(_normalize(f).split()) for f in settings.radar_legal_forms}
    return sorted((f for f in forms if f), key=len, reverse=True)


def company_key(name: str, country: str | None, settings: Settings | None = None) -> str:
    """Match key (D58): NFKC, casefold, punctuation stripped, legal-form tokens removed
    (`settings.radar_legal_forms`), joined with the ISO2 country."""
    settings = settings or get_settings()
    tokens = _normalize(name).split()
    kept: list[str] = []
    forms = _form_sequences(settings)
    i = 0
    while i < len(tokens):
        for form in forms:
            if tuple(tokens[i : i + len(form)]) == form:
                i += len(form)
                break
        else:
            kept.append(tokens[i])
            i += 1
    normalized = " ".join(kept) or " ".join(tokens)
    return f"{country or _NO_COUNTRY}:{normalized}"


def subject_problem(name: str, settings: Settings | None = None) -> str | None:
    """Why `name` cannot be a company (D68), or None when it may be one.

    Rejects URLs, names with no letter, pronoun or description phrases, and sentences.
    """
    settings = settings or get_settings()
    text = unicodedata.normalize("NFKC", name).strip()
    if not any(ch.isalpha() for ch in text):
        return "contains no letter"
    if "://" in text or text.casefold().startswith("www.") or _URL_LIKE.match(text):
        return "is a URL"
    tokens = _normalize(text).split()
    pronouns = _words(settings, "radar_non_name_pronouns", _DEFAULT_PRONOUNS)
    generic = _words(settings, "radar_non_name_words", _DEFAULT_GENERIC)
    max_words = int(getattr(settings, "radar_name_max_words", _DEFAULT_MAX_WORDS))
    if len(tokens) > max_words or re.search(r"[;:!?]", text):
        return "is a sentence"
    if tokens[0] in pronouns - {"the"}:
        return "is a pronoun or description phrase"
    if all(t in pronouns or t in generic for t in tokens):
        return "is a pronoun or description phrase"
    words = text.split()
    if tokens[0] == "the" and all(w.islower() for w in words):
        return "is a pronoun or description phrase"  # lower-case phrase, not a proper name
    return None


def stream_for(source_name: str, event_type: str, settings: Settings | None = None) -> RadarStream:
    """Stream of one event (D60): `radar_stream_by_event` first, else announcement."""
    settings = settings or get_settings()
    if source_name in settings.radar_enumerable_sources:
        mapped = settings.radar_stream_by_event.get(event_type)
        if mapped is not None:
            return RadarStream(mapped)
    return RadarStream.ANNOUNCEMENT


def _type_stream(event_type: str, settings: Settings) -> RadarStream:
    return RadarStream(settings.radar_stream_by_event.get(event_type, "announcement"))


def _earliest_deadline(events: list[CandidateEvent]) -> date | None:
    found: list[date] = []
    for event in events:
        raw = event.slots.get("deadlines")
        if not isinstance(raw, str):
            continue
        for part in raw.split(","):
            parsed = parse_date(part.strip())
            if parsed is not None:
                found.append(parsed)
    return min(found) if found else None


def window_for(
    stream: RadarStream, events: list[CandidateEvent], settings: Settings | None = None
) -> tuple[date | None, date | None, bool, str]:
    """(window_start, window_end, estimated, note) per D60 and D27."""
    settings = settings or get_settings()
    stream = RadarStream(stream)
    if stream == RadarStream.AWARD:
        return None, None, False, "Decided; account for future bids."
    if stream == RadarStream.TENDER:
        tenders = [e for e in events if _type_stream(e.event_type, settings) == stream]
        dates = [e.occurred_on for e in tenders if e.occurred_on is not None]
        start = min(dates) if dates else None
        end = _earliest_deadline(tenders)
        if end is not None:
            return start, end, False, "Open until the stated deadline."
        if start is None:
            return None, None, False, "No publication date or deadline stated."
        end = start + timedelta(days=settings.radar_tender_window_days)
        return start, end, True, "No deadline stated; window estimated from publication."
    dates = [e.occurred_on for e in events if e.occurred_on is not None]
    start = min(dates) if dates else None
    return start, None, False, "Specification window, not enumerable."


class _Mention:
    """One subject on one event, with the verified claims behind it."""

    def __init__(
        self,
        subject: SubjectMention,
        event: PendingEvent,
        stream: RadarStream,
        claims: list[tuple[ClaimCheck, EvidenceDocument]],
    ) -> None:
        self.subject = subject
        self.event = event
        self.stream = stream
        self.claims = claims


def _unidentified(
    event: PendingEvent,
    doc: EvidenceDocument,
    stream: RadarStream,
    claims: list[tuple[ClaimCheck, EvidenceDocument]],
    why: str,
    settings: Settings,
) -> RejectedEntry:
    candidate = _make_candidate(
        key=f"{_NO_COUNTRY}:unidentified:{event.fingerprint}",
        name=NO_COMPANY,
        country=None,
        aliases=[],
        roles=[],
        mentions=[_Mention(SubjectMention(name=NO_COMPANY, role="unknown"), event, stream, claims)],
        settings=settings,
        window=False,
    )
    gate = GateDecision(
        passed=False,
        rejected_as=RejectedAs.UNIDENTIFIED,
        by="code",
        reason=f"{event.event_type} event from {doc.url}: {why}",
        direct_buyer=None,
        buyer_reason=None,
        demand_reason=None,
        suggested_action=None,
        cited_refs=[],
    )
    return RejectedEntry(candidate=candidate, gate=gate)


def _claim_sort_key(item: tuple[int, ClaimCheck, EvidenceDocument]) -> tuple[Any, ...]:
    order, check, doc = item
    when = doc.available_at
    offset = check.quote_offset
    return (
        when is None,
        when.timestamp() if when is not None else 0.0,
        offset is None,
        offset if offset is not None else 0,
        order,
    )


def _kind_of(doc: EvidenceDocument, settings: Settings) -> EvidenceKind:
    rule = settings.evidence_source_rules.get(doc.source_name, "full_text")
    return EvidenceKind.STRUCTURED if rule == "structured" else EvidenceKind.FULL_TEXT


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _make_candidate(
    *,
    key: str,
    name: str,
    country: str | None,
    aliases: list[str],
    roles: list[str],
    mentions: list[_Mention],
    settings: Settings,
    window: bool = True,
) -> Candidate:
    seen: dict[str, tuple[int, ClaimCheck, EvidenceDocument]] = {}
    for mention in mentions:
        for check, doc in mention.claims:
            seen.setdefault(check.fingerprint, (len(seen), check, doc))
    refs: dict[str, str] = {}
    claims: list[CandidateClaim] = []
    for n, (_, check, doc) in enumerate(sorted(seen.values(), key=_claim_sort_key), start=1):
        refs[check.fingerprint] = f"C{n}"
        claims.append(
            CandidateClaim(
                ref=f"C{n}",
                fingerprint=check.fingerprint,
                document_id=doc.id,
                statement=check.draft.statement,
                source_quote=check.draft.source_quote,
                source_name=doc.source_name,
                url=doc.url,
                available_at=doc.available_at,
                evidence_kind=_kind_of(doc, settings),
                verified_by=check.verified_by or check.draft.extracted_by,
                upgraded_from=_str_or_none(doc.meta.get("upgraded_from")),
            )
        )
    events: dict[str, CandidateEvent] = {}
    streams: set[RadarStream] = set()
    for mention in mentions:
        streams.add(mention.stream)
        event = mention.event
        if event.fingerprint in events:
            continue
        events[event.fingerprint] = CandidateEvent(
            event_type=event.event_type,
            description=event.description,
            occurred_on=event.occurred_on,
            available_at=event.available_at,
            claim_refs=sorted(
                {refs[fp] for fp in event.claim_fingerprints if fp in refs},
                key=lambda r: int(r[1:]),
            ),
            slots=dict(event.slots),
            fingerprint=event.fingerprint,
        )
    primary = next(s for s in _PRIMARY_ORDER if s in streams)
    event_list = list(events.values())
    if window:
        start, end, estimated, note = window_for(primary, event_list, settings)
    else:
        start, end, estimated, note = None, None, False, ""
    return Candidate(
        key=key,
        name=name,
        country=country,
        aliases=aliases,
        roles=roles,
        stream=primary,
        streams=[s for s in _PRIMARY_ORDER if s in streams],
        events=event_list,
        claims=claims,
        window_start=start,
        window_end=end,
        window_estimated=estimated,
        window_note=note,
    )


def build_candidates(
    results: list[tuple[EvidenceDocument, LedgerResult]], *, settings: Settings | None = None
) -> tuple[list[Candidate], list[RejectedEntry]]:
    """One candidate per company key; rejected holds UNIDENTIFIED events only (rule #3, D62)."""
    settings = settings or get_settings()
    mentions: list[_Mention] = []
    rejected: list[RejectedEntry] = []
    for doc, result in results:
        verified = {c.fingerprint: c for c in result.checks if c.verified}
        for event in result.events:
            claims = [(verified[fp], doc) for fp in event.claim_fingerprints if fp in verified]
            stream = stream_for(doc.source_name, event.event_type, settings)
            if event.subject is None:
                rejected.append(
                    _unidentified(event, doc, stream, claims, "no company named", settings)
                )
                continue
            problem = subject_problem(event.subject.name, settings)
            if problem is not None:
                why = f"subject {event.subject.name!r} {problem}"
                rejected.append(_unidentified(event, doc, stream, claims, why, settings))
                continue
            mentions.append(_Mention(event.subject, event, stream, claims))

    groups: dict[str, list[_Mention]] = {}
    for m in mentions:
        groups.setdefault(company_key(m.subject.name, m.subject.country, settings), []).append(m)

    # A country-less key joins the single countried key with the same name part (D58).
    by_name: dict[str, list[str]] = {}
    for key in groups:
        country, _, name_part = key.partition(":")
        if country != _NO_COUNTRY:
            by_name.setdefault(name_part, []).append(key)
    for key in [k for k in groups if k.startswith(f"{_NO_COUNTRY}:")]:
        targets = by_name.get(key.partition(":")[2], [])
        if len(targets) == 1:
            groups[targets[0]].extend(groups.pop(key))

    candidates: list[Candidate] = []
    for key, members in groups.items():
        names = list(dict.fromkeys(m.subject.name.strip() for m in members))
        country = key.partition(":")[0]
        candidates.append(
            _make_candidate(
                key=key,
                name=names[0],
                country=None if country == _NO_COUNTRY else country,
                aliases=names[1:],
                roles=list(dict.fromkeys(m.subject.role for m in members)),
                mentions=members,
                settings=settings,
            )
        )
    return candidates, rejected
