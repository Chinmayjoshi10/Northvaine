"""A distributor's own website becomes a candidate (D136), and so does a target account's (D138).

Outside the UK there are no import records. A partner-discovery search (`intent.partner_queries`)
returns companies' own websites, which carry no dated event, so `build_candidates` drops them.
Here, by code, a page that is a company's own site (D133) and has a sentence naming what the client
sells becomes a candidate with an undated "company_profile" event and verified claims quoting the
page. They then go through the same off-target filter, gate, skeptic, fit and review as any lead.
Nothing is read by a model here; the text is the fetched page's cleaned text (rule 10).

A target account (D138) is a company the client already wants to win. Its own website is read
directly and the same rule applies: only a stated sentence naming what the client sells makes it a
lead, marked as on the client's list. Being on the list never makes it a buyer.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from northvaine.core.models import (
    ClaimCheck,
    ClaimDraft,
    ClaimStatus,
    Eligibility,
    EvidenceDocument,
    EvidenceKind,
    LedgerResult,
    SubjectMention,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.entities import company_key, site_owner
from northvaine.radar.fit import fit_sentences
from northvaine.radar.ledger import event_fingerprint
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
    CandidateEvent,
    RadarStream,
    TargetAccount,
)
from northvaine.radar.verify import claim_fingerprint

__all__ = ["partner_candidates", "target_candidates"]

_MAX_CLAIMS = 3
EVENT_TYPE = "company_profile"

Made = tuple[Candidate, tuple[EvidenceDocument, LedgerResult]]


def _name_part(key: str) -> str:
    return key.partition(":")[2]


def _terms(spec: Any) -> set[str]:
    return {t.casefold() for t in spec.offer_terms if t.strip()}


def _site_candidate(
    doc: EvidenceDocument, name: str, country: str | None, key: str, terms: set[str]
) -> Made | None:
    """`name`'s own page as a candidate with verified claims, or None when no sentence on it
    states what the client sells."""
    found = fit_sentences(doc.text, terms, set(), limit=_MAX_CLAIMS)
    found = [f for f in found if f[2] == "stated" and f[0] in doc.text]
    if not found:
        return None
    checks: list[ClaimCheck] = []
    claims: list[CandidateClaim] = []
    for sentence, term, _level in found:
        statement = f"{name}'s own website says it sells {term}."
        fingerprint = claim_fingerprint(doc.id, statement, sentence)
        checks.append(
            ClaimCheck(
                document_id=doc.id,
                draft=ClaimDraft(
                    statement=statement,
                    source_quote=sentence,
                    subject=SubjectMention(name=name, country=country, role="supplier"),
                    extracted_by="code",
                ),
                status=ClaimStatus.VERIFIED,
                quote_offset=doc.text.index(sentence),
                verified_by="code",
                fingerprint=fingerprint,
            )
        )
        claims.append(
            CandidateClaim(
                ref=f"C{len(claims) + 1}",
                fingerprint=fingerprint,
                document_id=doc.id,
                statement=statement,
                source_quote=sentence,
                source_name=doc.source_name,
                url=doc.url,
                available_at=doc.available_at,
                evidence_kind=EvidenceKind.FULL_TEXT,
                verified_by="code",
                upgraded_from=None,
            )
        )
    event = CandidateEvent(
        event_type=EVENT_TYPE,
        description=f"{name}'s own website: a company that sells what you sell.",
        occurred_on=None,
        available_at=doc.available_at,
        claim_refs=[c.ref for c in claims],
        slots={},
        fingerprint=event_fingerprint(EVENT_TYPE, [c.fingerprint for c in claims], None, key),
    )
    candidate = Candidate(
        key=key,
        name=name,
        country=country,
        aliases=[],
        roles=["distributor"],
        stream=RadarStream.ANNOUNCEMENT,
        streams=[RadarStream.ANNOUNCEMENT],
        events=[event],
        claims=claims,
        window_start=None,
        window_end=None,
        window_estimated=False,
        window_note="Specification window, not enumerable.",
    )
    result = LedgerResult(
        document_id=doc.id,
        eligibility=Eligibility(kind=EvidenceKind.FULL_TEXT),
        checks=checks,
    )
    return candidate, (doc, result)


def partner_candidates(
    documents: Iterable[tuple[EvidenceDocument, str]],
    spec: Any,
    existing: Iterable[Candidate],
    *,
    settings: Settings | None = None,
) -> tuple[list[Candidate], list[tuple[EvidenceDocument, LedgerResult]]]:
    """`documents` are (page, country of the query that found it). Returns the new candidates and
    the (document, ledger result) pairs that store their claims with their source."""
    cfg = settings or get_settings()
    terms = _terms(spec)
    if not terms:
        return [], []
    taken_keys = {c.key for c in existing}
    taken_names = {_name_part(c.key) for c in existing}
    out: list[Candidate] = []
    evidence: list[tuple[EvidenceDocument, LedgerResult]] = []
    for doc, country in documents:
        owner = site_owner(doc, cfg)
        if owner is None:
            continue
        key = company_key(owner.name, country, cfg)
        if key in taken_keys or _name_part(key) in taken_names:
            continue
        made = _site_candidate(doc, owner.name, country, key, terms)
        if made is None:
            continue
        out.append(made[0])
        evidence.append(made[1])
        taken_keys.add(key)
        taken_names.add(_name_part(key))
    return out, evidence


def target_candidates(
    pages: Iterable[tuple[EvidenceDocument, TargetAccount]],
    spec: Any,
    existing: Iterable[Candidate],
    *,
    accounts: Iterable[TargetAccount] = (),
    settings: Settings | None = None,
) -> tuple[list[Candidate], list[tuple[EvidenceDocument, LedgerResult]], set[str], list[str]]:
    """`pages` are (page read from the account's own site, the account). Returns the new
    candidates (marked `from_list`), their evidence, the keys of accounts the run had already
    found (the caller marks those), and plain notes for accounts whose site names nothing the
    client sells, or (`accounts`: the whole list) whose site gave no page: those are never made
    leads."""
    cfg = settings or get_settings()
    terms = _terms(spec)
    pages = list(pages)
    by_name = {_name_part(c.key): c.key for c in existing}
    out: list[Candidate] = []
    evidence: list[tuple[EvidenceDocument, LedgerResult]] = []
    already: set[str] = set()
    done: set[str] = set()
    for doc, account in pages:
        key = company_key(account.name, account.country, cfg)
        if key in done:
            continue
        if _name_part(key) in by_name:
            already.add(by_name[_name_part(key)])
            done.add(key)
            continue
        made = _site_candidate(doc, account.name, account.country, key, terms) if terms else None
        if made is None:
            continue
        out.append(made[0].model_copy(update={"from_list": True}))
        evidence.append(made[1])
        done.add(key)
    notes = []
    for account in {a.name: a for a in [*accounts, *(a for _, a in pages)]}.values():
        if company_key(account.name, account.country, cfg) not in done:
            notes.append(
                f"your list: {account.name}: not a lead (its site could not be read or names "
                "nothing you sell)"
            )
    return out, evidence, already, notes
