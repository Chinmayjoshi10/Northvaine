"""Company fit from the company's own website (D96). Code-first: no model call.

ChatGPT's CEO priority 2: before an account is promoted, check on its own official pages that it
handles what the client sells. A fit is not a purchase, so it is shown separately and never
replaces dated demand evidence.

For each shortlisted account (an awarded contractor, an importer of record, or an unresolved
announcement), in rank order and capped:
1. **Find the official site.** One search for the company's name. A result counts only when its
   registrable domain contains a distinctive token of the company's normalised name (code
   check). Otherwise: "no official site found", and no fit.
2. **Search that site.** A second search restricted to the domain, for what the client sells.
3. **Read the pages.** The first pages are fetched through the run's PageFetcher, so replays
   use the recorded pages and robots rules are respected (D59).
4. **Find the sentences.** Code finds the sentences on those pages that name a client
   `offer_terms` word (stated fit) or a `related_terms` word (related fit). Each sentence is a
   verbatim quote with its offset in the stored page text, so it is a verified claim by
   construction.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

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
from northvaine.radar.brief import names_term
from northvaine.radar.discover import PageFetcher, neutralise_steering, strip_contacts
from northvaine.radar.models import ClientSpec, FitEvidence, RadarStream, RankedEntry
from northvaine.radar.verify import claim_fingerprint
from northvaine.sensors.base import SensorError, SensorQuery, content_hash
from northvaine.sensors.registry import get_sensor

__all__ = ["FitEvidence", "company_fit", "domain_matches", "fit_sentences", "registrable"]

_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}
_SENTENCE = re.compile(r"[^.!?\n]{12,400}[.!?]?")


def registrable(url: str) -> str:
    """The registrable domain of a URL ("www.acme.co.uk/x" -> "acme.co.uk")."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() or ch.isspace())


def domain_matches(name: str, url: str, settings: Settings | None = None) -> bool:
    """True when the URL's registrable domain contains a distinctive token of the company
    name: at least `radar_fit_min_token` letters, not a legal form."""
    cfg = settings or get_settings()
    forms = {_fold(f) for f in cfg.radar_legal_forms}
    label = _fold(registrable(url).split(".")[0])
    tokens = [t for t in _fold(name).split() if len(t) >= cfg.radar_fit_min_token]
    tokens = [t for t in tokens if t not in forms]
    return bool(label) and any(t in label for t in tokens)


def _reads_like_prose(sentence: str) -> bool:
    """At least 6 words, and at most half of them capitalised (a menu or a list of page links
    is mostly capitalised words)."""
    words = [w for w in sentence.split() if any(ch.isalpha() for ch in w)]
    if len(words) < 6:
        return False
    capitalised = sum(1 for w in words if w[0].isupper())
    return capitalised <= len(words) / 2


def fit_sentences(
    text: str, terms: set[str], related: set[str], *, limit: int
) -> list[tuple[str, str, Literal["stated", "related"]]]:
    """(sentence, term, level) for sentences naming an offer term (stated) or a related term."""
    found: list[tuple[str, str, Literal["stated", "related"]]] = []
    for match in _SENTENCE.finditer(text):
        sentence = match.group(0).strip()
        if not _reads_like_prose(sentence):
            continue  # menus and lists of links are not statements about the company
        for level, pool in (("stated", terms), ("related", related)):
            hit = next((t for t in sorted(pool) if names_term(sentence, {t}, prefix=True)), None)
            if hit is not None:
                found.append((sentence, hit, level))  # type: ignore[arg-type]
                break
        if len(found) >= limit:
            break
    return found


def _eligible(entry: RankedEntry) -> bool:
    return entry.candidate.stream != RadarStream.TENDER and entry.account_role in (
        "awarded_contractor",
        "importer_of_record",  # D102: tells a stockist from a haulier clearing goods for others
        "unresolved",
    )


async def company_fit(
    entries: list[RankedEntry],
    spec: ClientSpec,
    *,
    http: Any,
    fetcher: PageFetcher,
    as_of: datetime,
    settings: Settings | None = None,
    evidence_out: list[tuple[EvidenceDocument, LedgerResult]] | None = None,
) -> tuple[list[RankedEntry], list[str]]:
    """Each shortlisted entry with its company-fit evidence; notes for what was skipped."""
    cfg = settings or get_settings()
    terms = {t.casefold() for t in spec.offer_terms}
    related = {t.casefold() for t in spec.related_terms}
    notes: list[str] = []
    if not terms:
        return entries, ["company fit skipped: the client spec lists no offer_terms"]
    try:
        sensor = get_sensor("tavily", client=http, settings=cfg)
    except Exception as exc:
        return entries, [f"company fit skipped: {exc}"]

    shortlisted = [e for e in sorted(entries, key=lambda e: e.rank) if _eligible(e)]
    chosen = {id(e) for e in shortlisted[: cfg.radar_fit_max_accounts]}
    out: list[RankedEntry] = []
    for entry in entries:
        if id(entry) not in chosen:
            out.append(entry)
            continue
        c = entry.candidate
        try:
            found = await sensor.search(
                SensorQuery(text=c.name, countries=[c.country] if c.country else [], max_results=5)
            )
            site = next(
                (d.url for d in found.documents if domain_matches(c.name, d.url, cfg)), None
            )
            if site is None:
                notes.append(f"company fit: no official site found for {c.name}")
                out.append(entry)
                continue
            domain = registrable(site)
            pages = await sensor.search(
                SensorQuery(
                    text=" ".join(sorted(terms)[:4]),
                    domains=[domain],
                    max_results=cfg.radar_fit_pages,
                )
            )
        except SensorError as exc:
            notes.append(f"company fit: search failed for {c.name}: {exc}")
            out.append(entry)
            continue
        fits: list[FitEvidence] = []
        for lead in pages.documents[: cfg.radar_fit_pages]:
            if registrable(lead.url) != domain:
                continue
            page = await fetcher.fetch(lead.url)
            if page.refused is not None or not page.text:
                continue
            text, _ = neutralise_steering(strip_contacts(page.text), cfg)
            doc = EvidenceDocument(
                id=uuid5(NAMESPACE_URL, content_hash(text)),
                source_name="website",
                url=page.final_url or lead.url,
                title=page.title,
                text=text,
                available_at=min(page.fetched_at or as_of, as_of),
                meta={"fit_for": c.key},
            )
            checks: list[ClaimCheck] = []
            for sentence, term, level in fit_sentences(
                text, terms, related, limit=cfg.radar_fit_quotes
            ):
                statement = f"{c.name}'s own website names {term}."
                fingerprint = claim_fingerprint(doc.id, statement, sentence)
                checks.append(
                    ClaimCheck(
                        document_id=doc.id,
                        draft=ClaimDraft(
                            statement=statement,
                            source_quote=sentence,
                            subject=SubjectMention(name=c.name, country=c.country, role="fit"),
                            extracted_by="code",
                        ),
                        status=ClaimStatus.VERIFIED,
                        quote_offset=text.index(sentence),
                        verified_by="code",
                        fingerprint=fingerprint,
                    )
                )
                fits.append(
                    FitEvidence(
                        url=doc.url, quote=sentence, term=term, level=level, fingerprint=fingerprint
                    )
                )
            if checks and evidence_out is not None:
                evidence_out.append(
                    (
                        doc,
                        LedgerResult(
                            document_id=doc.id,
                            eligibility=Eligibility(kind=EvidenceKind.FULL_TEXT),
                            checks=checks,
                        ),
                    )
                )
        if not fits:
            notes.append(f"company fit: {domain} does not name what you sell on the pages read")
        level = (
            "stated" if any(f.level == "stated" for f in fits) else ("related" if fits else None)
        )
        update: dict[str, Any] = {"company_site": domain, "company_fit": fits, "fit_level": level}
        if level == "stated" and entry.evidence_level in ("generic_mention", "no_evidence"):
            update["evidence_level"] = "company_fit"  # it handles the category; no purchase yet
        out.append(entry.model_copy(update=update))
    return out, notes
