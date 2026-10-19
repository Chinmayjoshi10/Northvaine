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
from northvaine.radar.brief import _trade_slots, import_codes, names_term
from northvaine.radar.discover import PageFetcher, neutralise_steering, strip_contacts
from northvaine.radar.models import (
    ClientSpec,
    CompanyContact,
    FitEvidence,
    RadarStream,
    RankedEntry,
)
from northvaine.radar.verify import claim_fingerprint
from northvaine.sensors.base import SensorError, SensorQuery, content_hash
from northvaine.sensors.registry import get_sensor

__all__ = [
    "FitEvidence",
    "company_fit",
    "domain_matches",
    "find_company_contact",
    "fit_sentences",
    "registrable",
]

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


def domain_matches(
    name: str,
    url: str,
    settings: Settings | None = None,
    generic: frozenset[str] | None = None,
) -> bool:
    """True when the URL's registrable domain contains a distinctive token of the company
    name: at least `radar_fit_min_token` letters, not a legal form."""
    cfg = settings or get_settings()
    forms = {_fold(f) for f in cfg.radar_legal_forms}
    label = _fold(registrable(url).split(".")[0])
    tokens = [t for t in _fold(name).split() if len(t) >= cfg.radar_fit_min_token]
    tokens = [t for t in tokens if t not in forms]
    if generic is None:
        return bool(label) and any(t in label for t in tokens)
    # Stricter (D108 review): words of what the client sells are shared by most companies in
    # its market ("<word> direct" is someone else's shop), so they never identify a company,
    # plural or not. The site must carry the name's first distinctive word.
    # Short initials count here ("MSI"), and words any business name may carry do not.
    common = {_fold(w) for w in cfg.radar_fit_common_name_words}
    words = [t for t in _fold(name).split() if len(t) >= 3 and t not in forms and t not in common]
    own = [t for t in words if not any(t.startswith(g) for g in generic)]
    return bool(label) and bool(own) and own[0] in label


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


_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_PHONE = re.compile(r"(?<![\w+])\+?\(?\d[\d\s().\-]{7,22}\d(?![\w])")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def find_company_contact(
    pages: list[tuple[str, str]], domain: str, role_words: set[str]
) -> CompanyContact | None:
    """The company's own role address and phone, verbatim from the first page that has one.

    `pages` are (url, text) as fetched, before `strip_contacts`. An email counts only on the
    company's own registrable domain and only when its local part is a role word (a person's
    address is never kept). A phone is the first number with 9 to 15 digits. Company only."""
    for url, text in pages:
        email = next(
            (
                m.group(0)
                for m in _EMAIL.finditer(text)
                if registrable(f"https://{m.group(0).rsplit('@', 1)[1]}") == domain
                and m.group(0).split("@", 1)[0].casefold() in role_words
            ),
            None,
        )
        phone = next(
            (
                m.group(0).strip()
                for m in _PHONE.finditer(text)
                if 9 <= sum(ch.isdigit() for ch in m.group(0)) <= 15
                and not _DATE_LIKE.match(m.group(0))
            ),
            None,
        )
        if email or phone:
            return CompanyContact(email=email, phone=phone, url=url)
    return None


def _import_depth(entry: RankedEntry) -> tuple[int, int]:
    """(product-code families, months imported) from the import record; (0, 0) when none."""
    slots = _trade_slots(entry.candidate)
    # The import event carries no code list; each code is a "commodity <digits>" line of the
    # record text that our own sensor writes, so the distinct ones are counted there.
    codes = len(import_codes(entry.candidate))
    months = slots.get("months_active")
    return codes, months if isinstance(months, int) else 0


def _fit_order(entries: list[RankedEntry]) -> list[RankedEntry]:
    """Which eligible entries are checked first: trade importers by import depth (a free
    signal), then the other eligible entries by rank (D108). Entries that look like the
    client's customers come first (D109)."""
    eligible = [e for e in sorted(entries, key=lambda e: e.rank) if _eligible(e)]
    liked = [e for e in eligible if e.candidate.like_customers]  # D109
    eligible = [e for e in eligible if not e.candidate.like_customers]
    importers = [e for e in eligible if e.account_role == "importer_of_record"]
    importers.sort(key=lambda e: tuple(-n for n in _import_depth(e)))  # stable: ties keep rank
    others = [e for e in eligible if e.account_role != "importer_of_record"]
    return liked + importers + others


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
    # the words of what the client sells: shared by its whole market, never a company's own name
    market_words = frozenset(
        w
        for t in [*spec.offer_terms, *spec.related_terms]
        for w in _fold(t).split()
        if len(w) >= cfg.radar_fit_min_token
    )
    notes: list[str] = []
    if not terms:
        return entries, ["company fit skipped: the client spec lists no offer_terms"]
    try:
        sensor = get_sensor("tavily", client=http, settings=cfg)
    except Exception as exc:
        return entries, [f"company fit skipped: {exc}"]

    if cfg.radar_fit_single_search:
        shortlisted = _fit_order(entries)
    else:  # recordings made before D108: rank order
        shortlisted = [e for e in sorted(entries, key=lambda e: e.rank) if _eligible(e)]
    role_words = {w.casefold() for w in cfg.fit_contact_role_words}
    chosen = {id(e) for e in shortlisted[: cfg.radar_fit_max_accounts]}
    out: list[RankedEntry] = []
    for entry in entries:
        if id(entry) not in chosen:
            out.append(entry)
            continue
        c = entry.candidate
        try:
            if cfg.radar_fit_single_search:
                # D108: one search (name + what the client sells); the site is the first result
                # on a domain that carries the name, its pages are the results on that domain.
                # The register's spelling when known: trade records split names ("LIMIT ED").
                name = (c.company_register.name if c.company_register else None) or c.name
                found = await sensor.search(
                    SensorQuery(
                        text=" ".join([name, *spec.offer_terms[:3]]),
                        countries=[c.country] if c.country else [],
                        max_results=5,
                    )
                )
                site = next(
                    (
                        d.url
                        for d in found.documents
                        if domain_matches(name, d.url, cfg, generic=market_words)
                    ),
                    None,
                )
                if site is None:
                    notes.append(f"company fit: no official site found for {c.name}")
                    out.append(entry)
                    continue
                domain = registrable(site)
                lead_urls = [d.url for d in found.documents if registrable(d.url) == domain]
                if len(lead_urls) < 2:
                    lead_urls.append(f"https://{urlsplit(site).hostname}/")  # read the home page
                lead_urls = list(dict.fromkeys(lead_urls))[: cfg.radar_fit_pages]
            else:
                found = await sensor.search(
                    SensorQuery(
                        text=c.name, countries=[c.country] if c.country else [], max_results=5
                    )
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
                lead_urls = [
                    d.url
                    for d in pages.documents[: cfg.radar_fit_pages]
                    if registrable(d.url) == domain
                ]
        except SensorError as exc:
            notes.append(f"company fit: search failed for {c.name}: {exc}")
            out.append(entry)
            continue
        raw_pages: list[tuple[str, str]] = []  # (url, text) before strip_contacts
        fits: list[FitEvidence] = []
        for lead_url in lead_urls:
            page = await fetcher.fetch(lead_url)
            if page.refused is not None or not page.text:
                continue
            raw_pages.append((page.final_url or lead_url, page.contact_text or page.text))
            text, _ = neutralise_steering(strip_contacts(page.text), cfg)
            doc = EvidenceDocument(
                id=uuid5(NAMESPACE_URL, content_hash(text)),
                source_name="website",
                url=page.final_url or lead_url,
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
        contact: CompanyContact | None = None
        if cfg.radar_fit_single_search:
            # One extra fetch, always: the company's own contact page. Fetching it only when the
            # pages read had no contact made a replay diverge, since the unstripped text that
            # decided it is never recorded.
            page = await fetcher.fetch(f"https://{urlsplit(site).hostname}/contact")
            if page.refused is None and page.text:
                raw_pages.append((page.final_url or page.lead_url, page.contact_text or page.text))
            contact = find_company_contact(raw_pages, domain, role_words)
        if not fits:
            notes.append(f"company fit: {domain} does not name what you sell on the pages read")
        level = (
            "stated" if any(f.level == "stated" for f in fits) else ("related" if fits else None)
        )
        update: dict[str, Any] = {"company_site": domain, "company_fit": fits, "fit_level": level}
        if contact is not None:
            update["company_contact"] = contact
        if level == "stated" and entry.evidence_level in ("generic_mention", "no_evidence"):
            update["evidence_level"] = "company_fit"  # it handles the category; no purchase yet
        out.append(entry.model_copy(update=update))
    return out, notes
