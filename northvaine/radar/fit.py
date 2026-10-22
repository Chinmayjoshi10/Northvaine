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

import asyncio
import re
import unicodedata
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from northvaine.brain.budget import RunContext
from northvaine.brain.errors import BudgetExceeded, LlmInvalidOutput, LlmTimeout, LlmTransportError
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
from northvaine.radar.linefit import JudgeResult, judge_lines
from northvaine.radar.models import (
    ClientSpec,
    CompanyContact,
    FitEvidence,
    JudgedLine,
    RadarStream,
    RankedEntry,
    RejectedAs,
    RejectedEntry,
    SiteRoleQuote,
)
from northvaine.radar.verify import claim_fingerprint
from northvaine.sensors.base import SensorError, SensorQuery, content_hash
from northvaine.sensors.registry import get_sensor

__all__ = [
    "FitEvidence",
    "company_fit",
    "deep_links",
    "domain_matches",
    "find_company_contact",
    "fit_sentences",
    "guess_hosts",
    "guess_own_site",
    "registrable",
]

_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}
_INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff"
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
    """A real sentence: it starts with a capital or a digit, ends with . ! or ?, has at least 6
    words, and at most 40% of them capitalised. Menus, link lists and web forms ("Your Name Your
    Phone ... Request a Quote") fail; a live run showed both as "proof" before."""
    words = [w for w in sentence.split() if any(ch.isalpha() for ch in w)]
    if len(words) < 6 or not sentence or sentence[-1] not in ".!?":
        return False
    if not (sentence[0].isupper() or sentence[0].isdigit()):
        return False  # a fragment cut from the middle of the page
    caps_run = longest = 0
    for w in words:  # "CONTACT US BE THE FIRST": a shouted header, not a statement
        caps_run = caps_run + 1 if w.isupper() and len(w) > 1 else 0
        longest = max(longest, caps_run)
    if longest >= 3:
        return False
    capitalised = sum(1 for w in words if w[0].isupper())
    return capitalised <= len(words) * 0.4


def named_terms(text: str, terms: set[str]) -> set[str]:
    """The offer terms named by at least one prose sentence of `text` (D118)."""
    named: set[str] = set()
    for match in _SENTENCE.finditer(text):
        sentence = match.group(0).strip().lstrip(_INVISIBLE).strip()
        if _reads_like_prose(sentence):
            named |= {t for t in terms if names_term(sentence, {t}, prefix=True)}
    return named


def fit_sentences(
    text: str,
    terms: set[str],
    related: set[str],
    *,
    limit: int,
    prefer: set[str] | None = None,
) -> list[tuple[str, str, Literal["stated", "related"]]]:
    """(sentence, term, level) for sentences naming an offer term (stated) or a related term.

    With `prefer` (D118: the distinctive terms of the run), sentences naming one of them are kept
    before the others, still at most `limit`."""
    found: list[tuple[str, str, Literal["stated", "related"]]] = []
    for match in _SENTENCE.finditer(text):
        # zero-width characters are invisible padding some sites put before a sentence; the
        # stripped text is still a verbatim part of the page
        sentence = match.group(0).strip().lstrip(_INVISIBLE).strip()
        if not _reads_like_prose(sentence):
            continue  # menus and lists of links are not statements about the company
        for level, pool in (("stated", terms), ("related", related)):
            hits = [t for t in sorted(pool) if names_term(sentence, {t}, prefix=True)]
            if prefer and level == "stated":
                hits.sort(key=lambda t: t not in prefer)  # stable: a preferred term first
            if hits:
                found.append((sentence, hits[0], level))  # type: ignore[arg-type]
                break
        if not prefer and len(found) >= limit:
            break
    if prefer:
        found.sort(key=lambda f: not (f[2] == "stated" and f[1] in prefer))  # stable
    return found[:limit]


_PATH_SPLIT = re.compile(r"[/\-_.]+")


def deep_links(
    links: list[str],
    *,
    read_urls: set[str],
    domain: str,
    spec: ClientSpec,
    cfg: Settings,
) -> list[str]:
    """Product-page links worth reading (D119), best first, at most `radar_fit_deep_pages`.

    Same registrable domain only, not already read. A link's URL path is scored: 0 when a path
    word starts with a word of a catalogue line's terms (the client's first line first), then a
    word of what the client sells, then a generic product-page word. Others are skipped.
    Stable: equal scores keep page order. Pure, no network."""
    if cfg.radar_fit_deep_pages <= 0:
        return []
    floor = cfg.radar_fit_min_token
    line_words = [
        {w for t in line.terms for w in _fold(t).split() if len(w) >= floor}
        for line in spec.catalogue_lines
    ]
    market = {
        w
        for t in [*spec.offer_terms, *spec.related_terms]
        for w in _fold(t).split()
        if len(w) >= floor
    }
    generic = {w.casefold() for w in cfg.radar_fit_deep_path_words}
    seen = {u.rstrip("/") for u in read_urls}
    scored: list[tuple[tuple[int, int], int, str]] = []
    for order, link in enumerate(links[: cfg.radar_fit_link_cap]):
        if registrable(link) != domain or link.rstrip("/") in seen:
            continue
        words = [w for w in _PATH_SPLIT.split(urlsplit(link).path.casefold()) if w]
        score: tuple[int, int] | None = None
        for index, pool in enumerate(line_words):
            if any(w.startswith(t) for w in words for t in pool):
                score = (0, index)
                break
        if score is None and any(w.startswith(t) for w in words for t in market):
            score = (1, 0)
        if score is None and any(w in generic for w in words):
            score = (2, 0)
        if score is not None:
            scored.append((score, order, link))
            seen.add(link.rstrip("/"))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [link for _, _, link in scored[: cfg.radar_fit_deep_pages]]


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


def _distinctive_words(name: str, cfg: Settings) -> list[str]:
    forms = {_fold(f) for f in cfg.radar_legal_forms}
    common = {_fold(w) for w in cfg.radar_fit_common_name_words}
    return [t for t in _fold(name).split() if len(t) >= 3 and t not in forms and t not in common]


def _register_name(c: Any) -> str:
    return (c.company_register.name if c.company_register else None) or c.name


def own_name_rule(
    c: Any, verdict: JudgeResult, market_words: frozenset[str], cfg: Settings
) -> JudgeResult:
    """D121: a company whose pages sell mostly products under its own name is a maker's arm.

    The company's name word is the first distinctive word of its name that is not a word of the
    client's market. A verified brand is own-name when it contains that word. When own-name brands
    are at least half of the verified brands, the role becomes `makes` (unless it already is):
    the evidence is then the brand, which code found on the page. Pure, no network."""
    if not verdict.brands or verdict.role == "makes":
        return verdict
    if cfg.radar_fit_judge_buyer_roles and verdict.role in ("resells", "uses"):
        return verdict  # D123: a distributor's own-label range never overrides the judge
    word = next(
        (w for w in _distinctive_words(_register_name(c), cfg) if w not in market_words), None
    )
    if word is None:
        return verdict
    own = [b for b in verdict.brands if word in _fold(b).split()]
    if not own or 2 * len(own) < len(verdict.brands):
        return verdict
    return verdict.model_copy(
        update={"role": "makes", "role_url": "", "role_quote": "", "own_brand": own[0]}
    )


def guess_hosts(c: Any, cfg: Settings, market_words: frozenset[str] = frozenset()) -> list[str]:
    """Likely web hosts for a company, from its registered name only (D113). Pure, no network.

    Order: all distinctive words joined, the first two joined, the first alone (5+ letters),
    then the hyphenated forms; each with the country's top-level domains. Names made only of
    words of the client's market, or of common business words, give no guess."""
    words = _distinctive_words(_register_name(c), cfg)
    if not words or all(any(w.startswith(m) for m in market_words) for w in words):
        return []
    stems = ["".join(words), "".join(words[:2])]
    if len(words[0]) >= 5:
        stems.append(words[0])
    if len(words) >= 2:
        stems += ["-".join(words), "-".join(words[:2])]
    country = (c.country or "").lower()
    if country == "gb":
        tlds = [".co.uk", ".com", ".uk"]
    elif country:
        tlds = [".com", f".{country}"]
    else:
        tlds = [".com"]
    hosts = [f"{stem}{tld}" for stem in dict.fromkeys(stems) for tld in tlds]
    return list(dict.fromkeys(hosts))[: cfg.radar_site_guess_per_company]


def _page_proof(c: Any, text: str, cfg: Settings) -> str | None:
    """ "registration number" or "registered name" when the page text carries one, else None."""
    reg = c.company_register
    if reg is not None and reg.number:
        for number in dict.fromkeys([reg.number, reg.number.lstrip("0")]):
            if number and re.search(rf"(?<![0-9A-Za-z]){re.escape(number)}(?![0-9A-Za-z])", text):
                return "registration number"
    forms = {_fold(f) for f in cfg.radar_legal_forms}
    phrase = " ".join(t for t in _fold(_register_name(c)).split() if t not in forms)
    if phrase and f" {phrase} " in f" {' '.join(_fold(text).split())} ":
        return "registered name"
    return None


async def guess_own_site(
    c: Any, fetcher: PageFetcher, cfg: Settings, market_words: frozenset[str]
) -> tuple[str, str] | None:
    """(host, proof) for the first guessed host whose page proves it is this company's own."""
    for host in guess_hosts(c, cfg, market_words):
        home = await fetcher.fetch(f"https://{host}/")
        if home.refused is not None or not (home.contact_text or home.text):
            continue  # the host does not answer, or is not allowed
        proof = _page_proof(c, home.contact_text or home.text or "", cfg)
        if proof is None:
            contact = await fetcher.fetch(f"https://{host}/contact")
            if contact.refused is None:
                proof = _page_proof(c, contact.contact_text or contact.text or "", cfg)
        if proof is not None:
            return host, proof
    return None


def _judge_order(read: list[tuple[EvidenceDocument, str]], deep: set[str]) -> list[tuple[str, str]]:
    """(url, text) for the judge: deep product pages, search-hit pages, about, then home."""

    def rank(url: str) -> int:
        path = urlsplit(url).path.rstrip("/").casefold()
        if url in deep:
            return 0
        if path.endswith("/about") or path.endswith("/about-us"):
            return 2
        return 3 if path == "" else 1

    return [(d.url, t) for d, t in sorted(read, key=lambda item: rank(item[0].url))]  # stable


async def _judge_all(
    batch: list[Any],
    deep_urls: dict[int, set[str]],
    spec: ClientSpec,
    cfg: Settings,
    *,
    run: RunContext,
    session: Any,
    market_words: frozenset[str] = frozenset(),
) -> tuple[list[str], dict[int, JudgeResult]]:
    """The fit judge over `batch` (D119), concurrently; never fails the run."""
    gate = asyncio.Semaphore(cfg.radar_gate_concurrency)
    stopped = False
    failed = 0
    results: dict[int, JudgeResult] = {}
    notes: list[str] = []

    async def _one(item: Any) -> None:
        nonlocal stopped, failed
        _, entry, _, read, _ = item
        async with gate:
            if stopped:
                return
            try:
                judged = await judge_lines(
                    entry.candidate.name,
                    _judge_order(read, deep_urls.get(id(entry), set())),
                    spec,
                    run=run,
                    session=session,
                    settings=cfg,
                )
                results[id(entry)] = own_name_rule(entry.candidate, judged, market_words, cfg)
            except BudgetExceeded as exc:
                if not stopped:
                    notes.append(f"line fit stopped: {exc}")
                stopped = True
            except (LlmInvalidOutput, LlmTimeout, LlmTransportError):
                failed += 1

    await asyncio.gather(*(_one(item) for item in batch))
    with_line = sum(1 for v in results.values() if v.lines)
    if cfg.radar_fit_judge_role:  # D120: counts only, no names
        makes = sum(1 for v in results.values() if v.role == "makes")
        resells = sum(
            1 for v in results.values() if v.role == "resells" and spec.channel != "direct"
        )
        own_makers = sum(1 for v in results.values() if v.own_brand)
        extra = f", {own_makers} own-name makers" if cfg.radar_fit_judge_brands else ""
        notes.append(
            f"line fit: {len(results)} judged, {with_line} with a line, {makes} competitors "
            f"removed, {resells} possible distributors, {failed} failed{extra}"
        )
    else:
        notes.append(f"line fit: {len(results)} judged, {with_line} with a line, {failed} failed")
    return notes, results


async def company_fit(
    entries: list[RankedEntry],
    spec: ClientSpec,
    *,
    http: Any,
    fetcher: PageFetcher,
    as_of: datetime,
    settings: Settings | None = None,
    evidence_out: list[tuple[EvidenceDocument, LedgerResult]] | None = None,
    run: RunContext | None = None,
    session: Any = None,
    rejected_out: list[RejectedEntry] | None = None,
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
    # D113: guess the site from the registered name and check it, before spending a search.
    guessed: dict[int, tuple[str, str]] = {}
    guess_pool: list[RankedEntry] = []
    if cfg.radar_fit_single_search and cfg.radar_site_guess_max_companies > 0:
        guess_pool = shortlisted[: cfg.radar_site_guess_max_companies]
        gate = asyncio.Semaphore(cfg.radar_gate_concurrency)

        async def _guess(e: RankedEntry) -> tuple[str, str] | None:
            async with gate:
                return await guess_own_site(e.candidate, fetcher, cfg, market_words)

        for e, found_site in zip(
            guess_pool, await asyncio.gather(*(_guess(e) for e in guess_pool)), strict=True
        ):
            if found_site is not None:
                guessed[id(e)] = found_site
    searched = [e for e in shortlisted if id(e) not in guessed][: cfg.radar_fit_max_accounts]
    chosen = {id(e) for e in searched} | set(guessed)
    pool = {id(e) for e in guess_pool} | {id(e) for e in searched}
    by_search = 0
    deep_urls: dict[int, set[str]] = {}
    proof_for: dict[int, str] = {}
    out: list[RankedEntry] = []
    pending: list[tuple[int, RankedEntry, str, list[tuple[EvidenceDocument, str]], Any]] = []
    for entry in entries:
        if id(entry) not in chosen:
            out.append(entry)
            continue
        c = entry.candidate
        try:
            if id(entry) in guessed:
                host, proof_for[id(entry)] = guessed[id(entry)]
                site = f"https://{host}/"
                domain = registrable(site)
                lead_urls = [site]
            elif cfg.radar_fit_single_search:
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
                    out.append(entry)
                    continue
                by_search += 1
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
        if cfg.radar_fit_about_pages and cfg.radar_fit_single_search:
            # The "about" page says what a company does in sentences; a home page is often only a
            # menu (a hand-found buyer's site was read as naming nothing). Free fetches.
            root = f"https://{urlsplit(site).hostname}"
            lead_urls = list(dict.fromkeys([*lead_urls, f"{root}/about-us", f"{root}/about"]))
        raw_pages: list[tuple[str, str]] = []  # (url, text) before strip_contacts
        read: list[tuple[EvidenceDocument, str]] = []
        fetched: list[Any] = []

        def _read_page(
            page: Any,
            lead_url: str,
            *,
            keep_raw: bool,
            c: Any = c,
            read: Any = read,
            raw: Any = raw_pages,
        ) -> None:
            if keep_raw:
                raw.append((page.final_url or lead_url, page.contact_text or page.text))
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
            read.append((doc, text))

        for lead_url in lead_urls:
            page = await fetcher.fetch(lead_url)
            if page.refused is not None or not page.text:
                continue
            fetched.append(page)
            _read_page(page, lead_url, keep_raw=True)
        deep: set[str] = set()
        if cfg.radar_fit_deep_pages > 0 and cfg.radar_fit_single_search:
            # D119: a few product pages, found from the links of the pages just read. Free.
            picks = deep_links(
                [link for page in fetched for link in page.links],
                read_urls={d.url for d, _ in read} | set(lead_urls),
                domain=domain,
                spec=spec,
                cfg=cfg,
            )
            for lead_url in picks:
                page = await fetcher.fetch(lead_url)
                if page.refused is not None or not page.text:
                    continue
                _read_page(page, lead_url, keep_raw=False)
                deep.add(read[-1][0].url)
        deep_urls[id(entry)] = deep
        contact: CompanyContact | None = None
        if cfg.radar_fit_single_search:
            # One extra fetch, always: the company's own contact page. Fetching it only when the
            # pages read had no contact made a replay diverge, since the unstripped text that
            # decided it is never recorded.
            page = await fetcher.fetch(f"https://{urlsplit(site).hostname}/contact")
            if page.refused is None and page.text:
                raw_pages.append((page.final_url or page.lead_url, page.contact_text or page.text))
            contact = find_company_contact(raw_pages, domain, role_words)
        pending.append((len(out), entry, domain, read, contact))
        out.append(entry)  # replaced below, once the whole run's words are known (D118)

    # D118: which offer terms are common in this run. Only after every site is read.
    prefer: set[str] | None = None
    if cfg.radar_fit_distinctive:
        named = [set().union(*(named_terms(t, terms) for _, t in rd)) for _, _, _, rd, _ in pending]
        with_fit = [n for n in named if n]
        common = {
            t
            for t in terms
            if sum(t in n for n in with_fit) > cfg.radar_fit_common_share * len(with_fit)
        }
        prefer = set().union(*with_fit) - common if with_fit else set()
    judged: dict[int, JudgeResult] = {}  # D119/D120: id(entry) -> verified lines and role
    if (
        cfg.radar_fit_judge_top > 0
        and run is not None
        and (spec.catalogue_lines or cfg.radar_fit_judge_role)
    ):
        judge_notes, judged = await _judge_all(
            [p for p in pending if p[3]][: cfg.radar_fit_judge_top],
            deep_urls,
            spec,
            cfg,
            run=run,
            session=session,
            market_words=market_words,
        )
        notes.extend(judge_notes)
    removed: set[int] = set()
    for index, entry, domain, read, contact in pending:
        c = entry.candidate
        fits: list[FitEvidence] = []
        judged_here: list[JudgedLine] = []
        verdict = judged.get(id(entry)) or JudgeResult()
        role_here: SiteRoleQuote | None = None
        seen_lines: set[str] = set()
        for doc, text in read:
            checks: list[ClaimCheck] = []
            for sentence, term, level in fit_sentences(
                text, terms, related, limit=cfg.radar_fit_quotes, prefer=prefer
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
            for vl in verdict.lines:
                if vl.url != doc.url or vl.quote not in text or vl.line in seen_lines:
                    continue  # two reads of one URL can differ; never index a missing quote
                seen_lines.add(vl.line)
                statement = f"{c.name}'s own website shows it sells your {vl.line} line."
                fingerprint = claim_fingerprint(doc.id, statement, vl.quote)
                checks.append(
                    ClaimCheck(
                        document_id=doc.id,
                        draft=ClaimDraft(
                            statement=statement,
                            source_quote=vl.quote,
                            subject=SubjectMention(name=c.name, country=c.country, role="fit"),
                            extracted_by="llm",
                        ),
                        status=ClaimStatus.VERIFIED,
                        quote_offset=text.index(vl.quote),
                        verified_by="code",
                        fingerprint=fingerprint,
                    )
                )
                judged_here.append(
                    JudgedLine(line=vl.line, url=doc.url, quote=vl.quote, fingerprint=fingerprint)
                )
            if (
                verdict.role in ("makes", "resells", "uses")
                and role_here is None
                and verdict.role_url == doc.url
                and verdict.role_quote in text
            ):
                statement = {
                    "makes": f"{c.name}'s own website says it makes products like yours.",
                    "resells": f"{c.name}'s own website says it sells products like yours.",
                    "uses": f"{c.name}'s own website says it uses products like yours.",
                }[verdict.role]
                fingerprint = claim_fingerprint(doc.id, statement, verdict.role_quote)
                checks.append(
                    ClaimCheck(
                        document_id=doc.id,
                        draft=ClaimDraft(
                            statement=statement,
                            source_quote=verdict.role_quote,
                            subject=SubjectMention(name=c.name, country=c.country, role="fit"),
                            extracted_by="llm",
                        ),
                        status=ClaimStatus.VERIFIED,
                        quote_offset=text.index(verdict.role_quote),
                        verified_by="code",
                        fingerprint=fingerprint,
                    )
                )
                role_here = SiteRoleQuote(
                    url=doc.url, quote=verdict.role_quote, fingerprint=fingerprint
                )
            if verdict.own_brand and role_here is None and verdict.own_brand in text:
                # D121: its own site sells under its own name; the brand is the page's substring
                statement = f"{c.name}'s own website sells products under its own name."
                fingerprint = claim_fingerprint(doc.id, statement, verdict.own_brand)
                checks.append(
                    ClaimCheck(
                        document_id=doc.id,
                        draft=ClaimDraft(
                            statement=statement,
                            source_quote=verdict.own_brand,
                            subject=SubjectMention(name=c.name, country=c.country, role="fit"),
                            extracted_by="llm",
                        ),
                        status=ClaimStatus.VERIFIED,
                        quote_offset=text.index(verdict.own_brand),
                        verified_by="code",
                        fingerprint=fingerprint,
                    )
                )
                role_here = SiteRoleQuote(
                    url=doc.url, quote=verdict.own_brand, fingerprint=fingerprint
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
        if prefer:
            update["fit_distinctive"] = any(
                f.level == "stated" and names_term(f.quote, prefer, prefix=True) for f in fits
            )
        if judged_here:
            update["judged_lines"] = judged_here
        if verdict.role in ("makes", "resells", "uses"):
            update["site_role"] = verdict.role
            if role_here is not None:
                update["site_role_quote"] = role_here
            if verdict.role == "resells" and spec.channel in ("distributors", "both"):
                update["gate"] = entry.gate.model_copy(update={"partner": True})
        if id(entry) in proof_for:
            update["site_proof"] = proof_for[id(entry)]
        if contact is not None:
            update["company_contact"] = contact
        if level == "stated" and entry.evidence_level in ("generic_mention", "no_evidence"):
            update["evidence_level"] = "company_fit"  # it handles the category; no purchase yet
        out[index] = entry.model_copy(update=update)
        if verdict.role == "makes" and rejected_out is not None:
            # D120: its own site says it makes this kind of product: a competitor (rule 3)
            rejected_out.append(
                RejectedEntry(
                    candidate=entry.candidate,
                    gate=entry.gate.model_copy(
                        update={
                            "passed": False,
                            "rejected_as": RejectedAs.COMPETITOR,
                            "by": "llm",
                            "reason": (
                                "Its own site sells mainly its own-name brand: "
                                f'"{verdict.own_brand}"'
                                if verdict.own_brand
                                else "Its own site says it makes this kind of product: "
                                f'"{verdict.role_quote}"'
                            ),
                            "partner": False,
                        }
                    ),
                )
            )
            removed.add(index)
    if removed:
        out = [e for i, e in enumerate(out) if i not in removed]
        new_rank = {id(e): n for n, e in enumerate(sorted(out, key=lambda e: e.rank), start=1)}
        out = [e.model_copy(update={"rank": new_rank[id(e)]}) for e in out]
    if cfg.radar_fit_single_search:
        notes.append(
            f"company fit: {len(guessed)} sites found free, {by_search} by search, "
            f"{len(pool) - len(guessed) - by_search} not found"
        )
    return out, notes
