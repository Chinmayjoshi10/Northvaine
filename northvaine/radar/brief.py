"""Rank and render (T5.5, D64): ranking, the brief and the scorecard are code.

Never imports `northvaine.brain.llm` (checked by scripts/check_invariants.py).

Facts appear only as verified statements with their verbatim quotes. Model-written sentences
(demand reason, buyer reason, suggested action, skeptic points) are labelled, must cite claim
refs that exist on the entry, and are shown as "not stated" otherwise (D63).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from northvaine.core.models import EventType, EvidenceKind
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import iso2_to_name
from northvaine.radar.account import (
    LEVEL_ORDER,
    account_role,
    contract_nature,
    evidence_level,
    size_rank,
)
from northvaine.radar.learning import Posteriors, learned_score
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
    CatalogueLine,
    GateDecision,
    RadarRun,
    RadarStream,
    RankedEntry,
    RejectedAs,
    SkepticFinding,
)

__all__ = ["rank", "render_brief", "render_scorecard", "write_reports"]

NOT_STATED = "not stated"
PERSON_NAME = "(a person, name withheld)"
NO_NAME = "(no company named)"
DECISION_LINE = "A person decides and makes contact."

_STRENGTH_ORDER = {"strong": 0, "medium": 1, "weak": 2}
_TIER_OPEN, _TIER_RECENT, _TIER_UNDATED, _TIER_TOO_LATE, _TIER_CLOSED = 0, 1, 2, 3, 4
_WORD = re.compile(r"[^\W\d_]+")
_TITLE_PREFIX = re.compile(r"^Title \[[a-z]{2,3}\]:\s*")

_QUESTIONS = [
    "Who",
    "What happened",
    "When",
    "Why it creates demand",
    "Evidence",
    "Sources",
    "Why a buyer, not a competitor or publisher",
    "What is uncertain",
    "Suggested action",
]

_STREAM_NOTE = {
    RadarStream.TENDER: (
        "tender (a public notice asking for bids; every matching notice is listed)"
    ),
    RadarStream.AWARD: "award (a public notice of who won; every matching notice is listed)",
    RadarStream.ANNOUNCEMENT: (
        "announcement (a company or press statement; some are found, never all)"
    ),
    RadarStream.TRADE: (
        "trade record (official import records of your product codes; every named importer is "
        "listed)"
    ),
}

_FAILURE_CHIPS = [
    "wrong company",
    "not a buyer",
    "competitor/publisher let through",
    "stale/closed window",
    "wrong fact",
    "not actionable",
]


# ----------------------------------------------------------------------------- ranking


def _strength(candidate: Candidate) -> tuple[str, int, int]:
    """(strength, verified claims, documents). Strength comes from independent documents, not
    from how many fields one record has (review of D80): one official record is medium."""
    claims = candidate.claims
    documents = len({c.document_id for c in claims})
    if documents >= 2:
        return "strong", len(claims), documents
    if len(claims) >= 2:
        return "medium", len(claims), documents
    return "weak", len(claims), documents


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _evidence_reason(candidate: Candidate, claims: int, documents: int) -> str:
    if not claims:
        return "Evidence: no verified claims"
    kinds = {c.evidence_kind for c in candidate.claims}
    if kinds == {EvidenceKind.STRUCTURED}:
        source = "official record"
    elif EvidenceKind.STRUCTURED not in kinds:
        source = "page"
    else:
        source = "document"
    return f"Evidence: {_plural(claims, 'verified claim')} from {_plural(documents, source)}"


def _last_dated(candidate: Candidate) -> date | None:
    """The latest event date a verified claim states. Never the fetch time: a page we fetched
    today was not "announced today" (review of D80, rule #2)."""
    dates = [e.occurred_on for e in candidate.events if e.occurred_on is not None]
    return max(dates) if dates else None


_MARKET_SPLIT = re.compile(r"\b(?:for|to|into|across|selling|serving|in)\b", re.IGNORECASE)


def offer_terms(offer: str, settings: Settings | None = None) -> set[str]:
    """Words of what the client SELLS, derived from the offer text when no explicit
    `offer_terms` exist (D80, D82). Only the part before a market word ("for", "into"...) counts:
    "widgets for hotel brands" sells widgets, not hotels. Generic stopwords come from
    settings, never industry words."""
    cfg = settings or get_settings()
    stop = {w.casefold() for w in cfg.radar_offer_stopwords}
    product = _MARKET_SPLIT.split(offer, maxsplit=1)[0]
    return {
        w.casefold()
        for w in _WORD.findall(product)
        if len(w) >= cfg.radar_offer_term_min_chars and w.casefold() not in stop
    }


def _term_pattern(term: str, prefix: bool) -> re.Pattern[str]:
    """A term as whole words (plural allowed), or as a word prefix for explicit data terms, so
    a data term matches the start of a compound word, but a derived term never matches
    inside another word ("mile" is not in "milestone")."""
    body = r"\s+".join(re.escape(part) for part in term.casefold().split())
    tail = r"" if prefix else r"(?:s|es)?(?![^\W\d_])"
    return re.compile(r"(?<![^\W\d_])" + body + tail, re.IGNORECASE)


def names_term(quote: str, terms: set[str], prefix: bool = False) -> bool:
    """Whether `quote` names one of `terms` (the same rule as the requirement check)."""
    return _names_term(quote, terms, prefix)


def _names_term(quote: str, terms: set[str], prefix: bool = False) -> bool:
    text = quote.casefold()
    for term in terms:
        stem = term[:-1] if not prefix and term.endswith("s") and len(term) > 4 else term
        if _term_pattern(stem, prefix).search(text):
            return True
    return False


# Lines that name a party rather than what is bought never count as stating the requirement.
_PARTY_LINE = re.compile(r"^(?:Buyer|Winner)[ \[]")


def _stating_claims(candidate: Candidate) -> list[CandidateClaim]:
    """Claims that may state the candidate's requirement: an official record's title, or an
    extracted quote that names the candidate itself (review of D80: another brand's launch on
    the same page is not this candidate's need)."""
    name = candidate.name.casefold()
    out: list[CandidateClaim] = []
    for claim in candidate.claims:
        quote = claim.source_quote
        if _PARTY_LINE.match(quote) or "[natural person" in quote:
            continue
        if claim.evidence_kind == EvidenceKind.STRUCTURED:
            if _TITLE_PREFIX.match(quote):
                out.append(claim)
        elif name and name in quote.casefold():
            out.append(claim)
    return out


def requirement_of(
    candidate: Candidate, terms: set[str], *, prefix: bool = False
) -> tuple[str, str | None]:
    """('stated', ref) when one of the candidate's own stating quotes names what the client
    sells, found by code; ('inferred', None) otherwise. The model plays no part (D80, D82)."""
    if terms:
        for claim in _stating_claims(candidate):
            if _names_term(claim.source_quote, terms, prefix):
                return "stated", claim.ref
    return "inferred", None


def _urgency(
    candidate: Candidate, today: date, recent_days: int, min_days_left: int = 0
) -> tuple[int, int, str]:
    """(tier, position inside the tier, reason line). Lower sorts first."""
    end = candidate.window_end
    if candidate.stream == RadarStream.TENDER and end is not None:
        how = "estimated deadline" if candidate.window_estimated else "stated deadline"
        left = (end - today).days
        if 0 <= left < min_days_left:
            when = "today" if left == 0 else f"in {_plural(left, 'day')}"
            return (
                _TIER_TOO_LATE,
                left,
                f"Window: tender closes {when} ({how}): likely too late to prepare a bid",
            )
        if left >= 0:
            when = "today" if left == 0 else f"in {_plural(left, 'day')}"
            return _TIER_OPEN, left, f"Window: tender closes {when} ({how})"
        return (
            _TIER_CLOSED,
            -left,
            f"Window: tender closed on {end.isoformat()} ({how}); the window is closed",
        )
    if candidate.stream == RadarStream.TRADE:
        return _trade_urgency(candidate)
    last = _last_dated(candidate)
    if last is not None:
        age = (today - last).days
        if age < 0:
            return _TIER_RECENT, 0, f"Timing: planned for {last.isoformat()}"
        if age <= recent_days:
            return (
                _TIER_RECENT,
                age,
                f"Timing: dated {last.isoformat()} ({_plural(age, 'day')} ago)",
            )
        return _TIER_UNDATED, 0, f"Timing: dated {last.isoformat()}, not recent"
    return _TIER_UNDATED, 0, "Timing: no date stated"


def _trade_slots(candidate: Candidate) -> dict[str, Any]:
    """The slots of the candidate's latest `imports_recorded` event, or {}."""
    events = [e for e in candidate.events if e.event_type == EventType.IMPORTS_RECORDED.value]
    events.sort(key=lambda e: str(e.slots.get("last_month") or ""))
    return dict(events[-1].slots) if events else {}


def _trade_urgency(candidate: Candidate) -> tuple[int, int, str]:
    """Import records are a standing proof of buying, not a window. New importers lead: they are
    still building their supplier list (BUYER_INTENT_PLAN, lesson 5)."""
    slots = _trade_slots(candidate)
    last, first = slots.get("last_month"), slots.get("first_month")
    months = slots.get("months_active")
    span = f"imported in {months} month(s) from {first} to {last}" if last else "imports recorded"
    # D112: breadth first (how many of the client's own product codes it imports), then months
    # active, and being new this year is worth as much as two more codes: a new importer is still
    # choosing suppliers, but it no longer outranks one that buys five of the client's products
    # every month (a live run put such hand-found buyers at 117th and 144th).
    active = months if isinstance(months, int) else 0
    codes = import_codes(candidate)
    new = bool(slots.get("new_this_year"))
    position = -((len(codes) + (2 if new else 0)) * 100 + active)
    if new:
        return _TIER_RECENT, position, f"Timing: started importing this year; {span}"
    return _TIER_RECENT, position, f"Timing: a regular importer; {span}"


# the commodity lines our own import sensor writes into the record text
_COMMODITY = re.compile(r"commodity (\d{6,10})")


def import_codes(candidate: Candidate) -> set[str]:
    """The distinct product codes in the candidate's import records (the event carries no code
    list; each code is a commodity line of the record text)."""
    return {
        code
        for e in candidate.events
        if e.event_type == EventType.IMPORTS_RECORDED.value
        for code in _COMMODITY.findall(e.description or "")
    }


def _trade_requirement(candidate: Candidate) -> CandidateClaim | None:
    """The record line naming a product code: the sensor only lists the client's own codes, so
    this line states the requirement (D102)."""
    if candidate.stream != RadarStream.TRADE:
        return None
    return next(
        (
            k
            for k in candidate.claims
            if k.evidence_kind == EvidenceKind.STRUCTURED
            and k.source_quote.startswith("Commodity ")
        ),
        None,
    )


def _buyer_reason(gate: GateDecision) -> str:
    if gate.direct_buyer is True:
        return "Buyer: buys directly"
    if gate.direct_buyer is False:
        return "Buyer: does not buy directly (reached through others)"
    return "Buyer: not stated whether it buys directly"


def rank(
    passed: list[tuple[Candidate, GateDecision, SkepticFinding]],
    *,
    as_of: datetime,
    settings: Settings | None = None,
    offer: str = "",
    terms: list[str] | None = None,
    related_terms: list[str] | None = None,
    learned: Posteriors | None = None,
) -> list[RankedEntry]:
    """Lexicographic order by (requirement stated before inferred, window urgency or recency,
    evidence strength, direct buyer), each component explained in `rank_reasons`; no numeric
    score (D64, D80). Uncertainty lowers rank. A learned strategy (D89) only breaks the
    remaining ties, by the learned good-rate of the lead's sources and country."""
    cfg = settings or get_settings()
    today = as_of.date()
    # Explicit "what we sell" terms from the client spec (data, any language) match as word
    # prefixes; without them, whole words of the offer's product part are used (D82).
    prefix = bool(terms)
    term_set = {t.casefold() for t in terms} if terms else offer_terms(offer, cfg)
    related_set = {t.casefold() for t in related_terms or []}
    scored = []
    for candidate, gate, skeptic in passed:
        strength, claims, documents = _strength(candidate)
        tier, position, urgency_line = _urgency(
            candidate, today, cfg.radar_recent_days, cfg.radar_min_days_left
        )
        requirement, requirement_ref = requirement_of(candidate, term_set, prefix=prefix)
        trade_line = _trade_requirement(candidate)
        if trade_line is not None:
            requirement, requirement_ref = "stated", trade_line.ref
        if requirement != "stated" and related_set:
            related, related_ref = requirement_of(candidate, related_set, prefix=True)
            if related == "stated":
                requirement, requirement_ref = "related", related_ref
        requirement_line = {
            "stated": (
                f"Requirement: stated (official import records under your product codes) "
                f"[{requirement_ref}]"
                if trade_line is not None
                else f"Requirement: stated (a verified quote names what you sell) "
                f"[{requirement_ref}]"
            ),
            "related": f"Requirement: related (a verified quote names a related product, not "
            f"exactly what you sell; check the specification) [{requirement_ref}]",
            "inferred": "Requirement: inferred (no verified quote names what you sell)",
        }[requirement]
        reasons = [
            requirement_line,
            urgency_line,
            _evidence_reason(candidate, claims, documents),
            _buyer_reason(gate),
        ]
        nature, nature_derived = contract_nature(candidate, cfg)
        role = account_role(candidate, nature)
        level = evidence_level(requirement, role, gate.direct_buyer)
        reasons.append(
            f"Account: {role.replace('_', ' ')}"
            + (
                f" ({nature} contract{', derived from CPV' if nature_derived else ''})"
                if nature
                else ""
            )
            + f"; evidence level: {level.replace('_', ' ')}"
        )
        score = learned_score(learned, [c.source_name for c in candidate.claims], candidate.country)
        if learned is not None:
            reasons.append(
                f"Learned: leads from these sources and this country were rated good "
                f"{score:.0%} of the time (breaks ties only)"
            )
        key = (
            LEVEL_ORDER[level],
            {"stated": 0, "related": 1, "inferred": 2}[requirement],
            tier,
            _STRENGTH_ORDER[strength],
            position,
            0 if gate.direct_buyer is True else 1,
            -round(score, 6),
            candidate.name,
        )
        scored.append(
            (
                key,
                candidate,
                gate,
                skeptic,
                strength,
                reasons,
                requirement,
                requirement_ref,
                {
                    "contract_nature": nature,
                    "nature_derived": nature_derived,
                    "account_role": role,
                    "evidence_level": level,
                },
            )
        )
    scored.sort(key=lambda item: item[0])
    return [
        RankedEntry(
            rank=i,
            candidate=candidate,
            gate=gate,
            skeptic=skeptic,
            strength=strength,
            rank_reasons=reasons,
            requirement=requirement,
            requirement_ref=requirement_ref,
            **account,
        )
        for i, (
            _,
            candidate,
            gate,
            skeptic,
            strength,
            reasons,
            requirement,
            requirement_ref,
            account,
        ) in enumerate(scored, start=1)
    ]


def _fit_group(entry: RankedEntry) -> int:
    """0 stated fit, 1 related fit, 2 anything else. A site whose few pages read do not name what
    the client sells is not evidence against the company (a live run sank a hand-found buyer to
    the bottom that way), so it ranks with the entries not checked."""
    if entry.fit_level == "stated":
        return 0
    if entry.fit_level == "related":
        return 1
    return 2


STREAM_WORDS = {
    RadarStream.TRADE: "import records",
    RadarStream.AWARD: "contract award",
    RadarStream.TENDER: "tender",
    RadarStream.ANNOUNCEMENT: "news",
}


def stream_words(candidate: Candidate) -> list[str]:
    """Plain words for the kinds of source a company was seen in (D115)."""
    return [STREAM_WORDS[s] for s in candidate.streams if s in STREAM_WORDS]


def _partner_size(entry: RankedEntry) -> int:
    facts = entry.candidate.company_register
    return size_rank(facts.accounts_type if facts else None) if entry.gate.partner else 0


def match_lines(entry: RankedEntry, lines: list[CatalogueLine]) -> list[str]:
    """Names of the catalogue lines this entry matches, in the client's priority order (D118).

    A line matches when a company-fit quote from the company's own site names one of its terms,
    or the fit judge found it on the site with a verified quote (D119).
    Product codes are not used: a live run matched half the importers to the premium line through
    codes that firms of every catalogue line both import, so a code cannot tell lines apart."""
    out: list[str] = []
    for line in lines:
        terms = {t.casefold() for t in line.terms if t.strip()}
        by_terms = bool(terms) and any(
            names_term(f.quote, terms, prefix=True) for f in entry.company_fit
        )
        if by_terms or any(j.line == line.name for j in entry.judged_lines):
            out.append(line.name)
    return out


def apply_fit_order(
    entries: list[RankedEntry],
    timing_days: int | None = None,
    link_sources: bool | None = None,
    lines: list[CatalogueLine] | None = None,
) -> list[RankedEntry]:
    """Company fit moves the ranking (D108), but only within an evidence level.

    Each evidence level keeps the positions it already holds; inside those positions the entries
    are put in a stable order: stated fit, related fit, then the rest in their earlier order.
    Then `rank` is renumbered 1..n and the reason is added to `rank_reasons`."""
    settings = get_settings()
    days = timing_days if timing_days is not None else settings.radar_timing_days
    link = link_sources if link_sources is not None else settings.radar_link_by_register
    lines = lines or []
    ordered = sorted(entries, key=lambda e: e.rank)
    if lines:  # D118
        ordered = [e.model_copy(update={"matched_lines": match_lines(e, lines)}) for e in ordered]
    names = [ln.name for ln in lines]

    def line_priority(e: RankedEntry) -> int:
        return min((names.index(n) for n in e.matched_lines if n in names), default=len(names))

    slots: dict[str | None, list[int]] = {}
    for i, e in enumerate(ordered):
        slots.setdefault(e.evidence_level, []).append(i)
    result = list(ordered)
    for positions in slots.values():
        members = sorted(  # stable; D109: looking like the client's customers breaks ties
            (ordered[i] for i in positions),
            key=lambda e: (
                _fit_group(e) * 2 + (0 if e.fit_distinctive else 1),  # D118
                line_priority(e) if lines else 0,  # D118: the client's own line order
                link and len(e.candidate.streams) < 2,  # D115: seen in 2+ kinds of source first
                len(e.candidate.timing_signals) < 2,  # D111: two or more signals first
                not e.candidate.like_customers,
                -_partner_size(e),  # D116: possible distributors, larger first
            ),
        )
        for i, e in zip(positions, members, strict=True):
            result[i] = e
    out: list[RankedEntry] = []
    for n, e in enumerate(result, start=1):
        reasons = list(e.rank_reasons)
        if e.fit_level is not None and e.company_fit:
            reasons.append(f"Company fit: its own site names {e.company_fit[0].term}")
        elif e.company_site is not None and not e.judged_lines:  # D119: a judged line says it does
            reasons.append("Company fit: its own site does not name what you sell")
        if e.matched_lines:
            reasons.append(f"Matches your catalogue line: {e.matched_lines[0]}")
        if link and len(e.candidate.streams) >= 2:
            reasons.append(f"Sources: seen in {', '.join(stream_words(e.candidate))}")
        reasons.extend(e.candidate.like_customers)
        if e.gate.partner:
            facts = e.candidate.company_register
            size = facts.accounts_type if facts and facts.accounts_type else "not stated"
            reasons.append(f"Possible distributor: sells your kind of product; size: {size}")
        if e.candidate.timing_signals:
            reasons.append(
                f"Timing: {len(e.candidate.timing_signals)} signals in the last {days} days"
            )
        out.append(e.model_copy(update={"rank": n, "rank_reasons": reasons}))
    return out


# ----------------------------------------------------------------------------- helpers


def _inline(text: str) -> str:
    """One line, so text cannot start a heading, list or quote. For our own wording."""
    return re.sub(r"\s+", " ", text).strip()


_MD_SPECIAL = re.compile(r"([\\`*_\[\]()<>!#|~])")


def _safe(text: str) -> str:
    """Untrusted or model text: one line, every Markdown control character escaped, so a page
    cannot plant links, images, HTML or fake labels in a brief (review of D80)."""
    return _MD_SPECIAL.sub(r"\\\1", _inline(text))


def _cell(text: str) -> str:
    return _safe(text)


def _link(url: str) -> str:
    """A source link only when it is http(s); shown as an autolink, never as raw Markdown."""
    clean = url.strip()
    if re.match(r"^https?://[^\s<>]+$", clean):
        return f"<{clean}>"
    return "(link withheld: not an http address)"


def _day(value: date | datetime | None) -> str:
    if value is None:
        return NOT_STATED
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()


def _country(code: str | None) -> str:
    if code is None:
        return "country not stated"
    try:
        return iso2_to_name(code).title()
    except KeyError:
        return code


def _refs(refs: list[str]) -> str:
    return " ".join(f"[{r}]" for r in refs)


def _valid_refs(refs: list[str], candidate: Candidate) -> list[str]:
    known = {c.ref for c in candidate.claims}
    seen: list[str] = []
    for ref in refs:
        if ref in known and ref not in seen:
            seen.append(ref)
    return seen


def _cited(text: str | None, cited: list[str], candidate: Candidate) -> str:
    """A model-written sentence with its citations, or 'not stated' (D63)."""
    if text is None or not _inline(text):
        return NOT_STATED
    refs = _valid_refs(cited, candidate)
    if not refs:
        return NOT_STATED
    return f"{_safe(text)} {_refs(refs)}"


def _source_kind(claim: CandidateClaim) -> str:
    if claim.upgraded_from is not None:
        return "page fetched from a search lead"
    if claim.evidence_kind == EvidenceKind.STRUCTURED:
        return "official record"
    return "full page"


def _window_line(candidate: Candidate) -> str:
    start, end = candidate.window_start, candidate.window_end
    parts = []
    if start is not None or end is not None:
        how = "estimated" if candidate.window_estimated else "stated"
        parts.append(f"{_day(start)} to {_day(end)} ({how})")
    note = _inline(candidate.window_note)
    if note:
        parts.append(note)
    return "; ".join(parts) if parts else "no window stated"


def _name(candidate: Candidate) -> str:
    return _safe(candidate.name) or NO_NAME


def _labelled(label: str, sentence: str) -> str:
    return NOT_STATED if sentence == NOT_STATED else f"{label}: {sentence}"


def _claim_starting(candidate: Candidate, prefix: str) -> CandidateClaim | None:
    return next((c for c in candidate.claims if c.source_quote.startswith(prefix)), None)


def _title(candidate: Candidate) -> CandidateClaim | None:
    return next((c for c in candidate.claims if _TITLE_PREFIX.match(c.source_quote)), None)


def _quoted_value(claim: CandidateClaim, prefix_re: re.Pattern[str] | str) -> str:
    text = claim.source_quote
    if isinstance(prefix_re, str):
        value = text[len(prefix_re) :]
    else:
        value = prefix_re.sub("", text, count=1)
    value = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        value = value[:10]  # a readable date; the full stamp stays in the quote below
    return _safe(value)


def _what(candidate: Candidate, limit: int = 90) -> str:
    """What the opportunity is about: the record's title when there is one, else the first
    verified statement. Code-composed from verified claims only."""
    title = _title(candidate)
    text = _quoted_value(title, _TITLE_PREFIX) if title else ""
    if not text and candidate.stream == RadarStream.TRADE:
        text = _imports_what(candidate)
    if not text and candidate.claims:
        text = _safe(candidate.claims[0].statement)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or NOT_STATED


def _imports_what(candidate: Candidate) -> str:
    """ "imports <code> (<description>); ..." from the record's commodity lines (D102)."""
    parts: list[str] = []
    for claim in candidate.claims:
        quote = claim.source_quote
        if quote.startswith("Commodity "):
            parts.append(_safe(quote.removeprefix("Commodity ").split(": imported")[0]))
    return "imports " + "; ".join(parts) if parts else ""


def _plain_happened(candidate: Candidate) -> str | None:
    """One readable sentence for an official record, each part with its claim ref, built from
    the record's own lines (D80). None when the candidate has no such record."""
    if candidate.stream == RadarStream.TRADE:
        return _plain_imported(candidate)
    title = _title(candidate)
    published = _claim_starting(candidate, "Published: ")
    deadline = _claim_starting(candidate, "Deadline: ")
    if title is None and published is None:
        return None
    name = _name(candidate)
    if candidate.stream == RadarStream.AWARD:
        head = f"{name} won a contract"
    elif candidate.stream == RadarStream.TENDER:
        head = f"{name} is buying through a public tender"
    else:
        head = f"{name} published a notice"
    parts = [head]
    if title is not None:
        parts.append(f": “{_quoted_value(title, _TITLE_PREFIX)}” [{title.ref}]")
    if published is not None:
        parts.append(f"; published {_quoted_value(published, 'Published: ')} [{published.ref}]")
    if deadline is not None:
        parts.append(f"; bids due {_quoted_value(deadline, 'Deadline: ')} [{deadline.ref}]")
    return "".join(parts) + "."


def _plain_imported(candidate: Candidate) -> str | None:
    """<name> imported goods under your product codes: <record line> [ref]; ..."""
    lines = [k for k in candidate.claims if k.source_quote.startswith("Commodity ")]
    if not lines:
        return None
    parts = [f"{_name(candidate)} imported goods under your product codes"]
    parts.append(": " + "; ".join(f"{_safe(k.source_quote)} [{k.ref}]" for k in lines[:3]))
    new = _claim_starting(candidate, "New importer: ")
    if new is not None:
        parts.append(f". {_safe(new.source_quote)} [{new.ref}]")
    return "".join(parts) + "."


def action_status(entry: RankedEntry) -> str:
    """contact now / bid now / qualify first / watch only (D80, D94).

    Before an award, a works or services authority is a demand source, not the material buyer,
    so its tender is a watch item. A supplies tender whose verified record names what the client
    sells is a direct purchase: "bid now". "Contact now" needs explicit-purchase evidence and no
    doubt the brief itself shows (review of D80, CEO acceptance criteria)."""
    explicit = (
        entry.evidence_level == "explicit_purchase"
        or (entry.evidence_level is None and entry.requirement == "stated")
        # an awarded contractor whose own site names what the client sells (D96)
        or (
            entry.account_role == "awarded_contractor"
            and entry.evidence_level == "project_requirement"
            and entry.fit_level == "stated"
        )
    )
    if entry.candidate.stream == RadarStream.TENDER:
        clean = explicit and not entry.steered and not entry.skeptic.against
        return "bid now" if clean and entry.account_role == "direct_purchaser" else "watch only"
    if entry.candidate.stream == RadarStream.TRADE:
        # Proof it buys the product, not a live order. Half the raw new importers in the field
        # test were not buyers, so contact waits for a check of what the company itself sells.
        clean = (
            entry.evidence_level == "proven_buyer"
            and not entry.steered
            and not entry.skeptic.against
            and entry.gate.direct_buyer is not False
        )
        return "contact now" if clean and entry.company_fit else "qualify first"
    doubts = (
        not explicit
        or entry.steered
        or entry.requirement != "stated"
        or bool(entry.skeptic.against)
        or entry.gate.direct_buyer is False
        or entry.strength == "weak"
    )
    return "qualify first" if doubts else "contact now"


_ROLE_LABEL = {
    "direct_purchaser": "the authority buys this itself",
    "demand_source": "the authority runs the project; the material buyer is the future winner",
    "awarded_contractor": "won the contract; the account to approach",
    "supplier": "won a supplies contract for this kind of product (a competitor or a channel)",
    "importer_of_record": "official import records show it buys your product codes",
    "unresolved": "role not established by an official record",
}


def _after_colon(quote: str) -> str:
    return quote.split(": ", 1)[1].strip() if ": " in quote else quote.strip()


def _chain(entry: RankedEntry) -> str | None:
    """For an awarded contractor: who ran the project, what it was, and that this company won
    it, each part cited to its verified record line (D94; the winner-to-account chain, D23)."""
    if entry.account_role != "awarded_contractor":
        return None
    claims = entry.candidate.claims
    buyer = next((k for k in claims if k.source_quote.startswith("Buyer [")), None)
    title = next((k for k in claims if k.source_quote.startswith("Title [")), None)
    winner = next((k for k in claims if k.source_quote.startswith("Winner [")), None)
    if winner is None or (buyer is None and title is None):
        return None
    parts = []
    if buyer is not None:
        parts.append(f"{_safe(_after_colon(buyer.source_quote))} [{buyer.ref}]")
    if title is not None:
        parts.append(f"ran {_safe(_after_colon(title.source_quote))} [{title.ref}]")
    parts.append(f"awarded to {_name(entry.candidate)} [{winner.ref}]")
    return " → ".join(parts)


def caution(entry: RankedEntry) -> str:
    """The most important thing not yet known, composed by code."""
    c = entry.candidate
    if entry.steered:
        return "a source page contained text aimed at AI systems (removed); check it by hand"
    nature_note = " (contract nature derived from its codes)" if entry.nature_derived else ""
    if c.stream == RadarStream.TENDER and action_status(entry) == "bid now":
        estimated = "; deadline estimated" if c.window_estimated else ""
        return f"a supplies tender: the authority buys directly; bid before the deadline{estimated}"
    if c.stream == RadarStream.TENDER:
        estimated = "; deadline estimated" if c.window_estimated else ""
        if entry.likely_bidders:
            names = ", ".join(b.name for b in entry.likely_bidders[:2])
            return f"the buyer is the future winner; likely bidders: {names}{estimated}"
        return (
            "the authority runs the tender; the material buyer is unknown until the award"
            + estimated
        )
    if entry.account_role == "supplier":
        return "it won a supplies contract for this kind of product: a competitor or a channel"
    if c.stream == RadarStream.TRADE:
        if entry.skeptic.against:
            return "the brief lists evidence against; read section 8"
        return (
            "import records prove it buys these codes, not from whom or whether it wants a new "
            "supplier; check what it sells before contact"
        )
    if entry.skeptic.against:
        return "the brief lists evidence against; read section 8"
    if entry.account_role == "awarded_contractor" and entry.fit_level != "stated":
        return "won the contract; confirm it buys what you sell for this work" + nature_note
    if entry.account_role == "awarded_contractor":
        return "won the contract and its own site names what you sell; ask what it needs here"
    if entry.requirement == "related":
        return "names a related product, not exactly yours: ask about the specification"
    if entry.requirement != "stated":
        return "the evidence does not name what you sell"
    if c.window_estimated:
        return "the deadline is estimated"
    if len({k.document_id for k in c.claims}) <= 1:
        return "all evidence comes from one document"
    return "no major gap flagged; check the source before contact"


def _is_value(claim: CandidateClaim) -> bool:
    return claim.source_quote.startswith(("Total value:", "Estimated value"))


def _why_now(entry: RankedEntry, today: date) -> str:
    """A code-composed reason to act now, from the window or the latest date."""
    c = entry.candidate
    if c.stream == RadarStream.TENDER and c.window_end is not None:
        left = (c.window_end - today).days
        estimated = " (estimated)" if c.window_estimated else ""
        if left < 0:
            return f"tender closed {c.window_end.isoformat()}{estimated}"
        late = " (likely too late)" if left < get_settings().radar_min_days_left else ""
        return f"tender closes in {_plural(left, 'day')}{estimated}{late}"
    if c.stream == RadarStream.TRADE:
        slots = _trade_slots(c)
        if slots.get("new_this_year"):
            return f"started importing in {slots.get('first_month')}"
        return f"imports regularly; latest recorded month {slots.get('last_month')}"
    last = _last_dated(c)
    if last is None:
        return "date not stated"
    if last > today:
        return f"planned for {_day(last)}"
    if c.stream == RadarStream.AWARD:
        decided = _claim_starting(c, "Winner decision date: ") is not None
        return f"{'awarded' if decided else 'award published'} {_day(last)}"
    return f"announced {_day(last)}"


# ----------------------------------------------------------------------------- brief


def _entry_block(entry: RankedEntry) -> list[str]:
    c, gate, skeptic = entry.candidate, entry.gate, entry.skeptic
    out = [
        f"### {entry.rank}. {_name(c)}",
        "",
        f"- Stream: {_STREAM_NOTE[c.stream]}",
        f"- Window: {_window_line(c)}",
        f"- Evidence strength: {entry.strength}",
        "- Why it is ranked here:",
    ]
    out += [f"  - {_inline(r)}" for r in entry.rank_reasons]
    out.append("")

    def heading(n: int) -> str:
        return f"#### {n}. {_QUESTIONS[n - 1]}"

    # 1 Who
    roles = ", ".join(_safe(r) for r in c.roles) or NOT_STATED
    out += [heading(1), "", f"{_name(c)}, {_country(c.country)}. Roles: {roles}.", ""]

    # 2 What happened
    out += [heading(2), ""]
    plain = _plain_happened(c)
    if plain is not None:
        out.append(plain)
    elif c.events:
        for ev in c.events:
            refs = _refs(_valid_refs(ev.claim_refs, c))
            out.append(f"- {_safe(ev.description)} {refs}".rstrip())
    else:
        out.append(NOT_STATED)
    out.append("")

    # 3 When
    out += [heading(3), ""]
    for ev in c.events:
        refs = _refs(_valid_refs(ev.claim_refs, c))
        out.append(f"- Event date: {_day(ev.occurred_on)} {refs}".rstrip())
    out.append(f"- Stream: {c.stream.value}")
    out.append(f"- Window: {_window_line(c)}")
    out.append("")

    # 4 Why it creates demand
    out += [heading(4), ""]
    out.append(
        _labelled("Assessment (model-written)", _cited(gate.demand_reason, gate.cited_refs, c))
    )
    out.append("")

    # 5 Evidence
    out += [heading(5), ""]
    for claim in c.claims:
        out.append(f"**[{claim.ref}]** {_safe(claim.statement)}")
        out.append("")
        out += [f"> {_safe(line)}" for line in claim.source_quote.split("\n")]
        out.append("")
        if _is_value(claim):
            out += [
                "(Total value of the notice, across all its lots and winners, in the currency "
                "the source states. It is not the share for what you sell.)",
                "",
            ]

    # 6 Sources
    out += [heading(6), ""]
    seen: dict[tuple[str, str, str], list[str]] = {}
    for claim in c.claims:
        key = (claim.url, claim.source_name, _day(claim.available_at))
        labels = seen.setdefault(key, [])
        label = _source_kind(claim)
        if label not in labels:
            labels.append(label)
    for (url, source, available), labels in seen.items():
        out.append(f"- {_link(url)} ({_safe(source)}); available {available}; {', '.join(labels)}")
    if not seen:
        out.append(NOT_STATED)
    out.append("")

    # 7 Why a buyer
    out += [heading(7), ""]
    cfg = get_settings()
    out.append(
        f"Requirement: {entry.requirement}"
        + (f" [{entry.requirement_ref}]" if entry.requirement_ref else "")
        + {
            "stated": "",
            "related": " (a verified quote names a related product, not exactly what you sell; "
            "ask about the specification before quoting)",
            "inferred": " (no verified quote names what you sell; treat this as a possibility)",
        }[entry.requirement]
        + "."
    )
    if entry.account_role:
        nature = ""
        if entry.contract_nature:
            derived = ", derived from its codes" if entry.nature_derived else ""
            nature = f" ({entry.contract_nature} contract{derived})"
        level = (entry.evidence_level or "").replace("_", " ")
        out.append(
            f"Account: {_ROLE_LABEL.get(entry.account_role, entry.account_role)}{nature}; "
            f"evidence level: {level}."
        )
    chain = _chain(entry)
    if chain:
        out.append(f"Chain: {chain}")
    if entry.company_site:
        out.append(
            f"Company fit (not a purchase): its own site {_safe(entry.company_site)} "
            + (
                f"names {'what you sell' if entry.fit_level == 'stated' else 'related products'}:"
                if entry.company_fit
                else "does not name what you sell on the pages read."
            )
        )
        for fit in entry.company_fit:  # verified by code on the stored page (D96)
            out.append(f'- "{_safe(fit.quote)}" ({_link(fit.url)})')
    who_buys = cfg.radar_buyer_note_by_stream.get(c.stream.value)
    if who_buys:
        out.append(f"Who buys: {_inline(who_buys)}")
    if entry.likely_bidders:
        out.append(
            f"Likely bidders (won similar contracts in {_country(c.country)} in the last "
            f"{cfg.radar_bidder_lookback_days} days, from official award notices):"
        )
        for b in entry.likely_bidders:
            wins = _plural(b.wins, "win")
            out.append(f"- {_safe(b.name)}: {wins}, last {_day(b.last_won)}; {_link(b.source_url)}")
    direct = {True: "yes, buys directly", False: "no, reached through others"}.get(
        gate.direct_buyer, NOT_STATED
    )
    out.append(f"Direct buyer: {direct}.")
    out.append(
        _labelled("Assessment (model-written)", _cited(gate.buyer_reason, gate.cited_refs, c))
    )
    out.append("")

    # 8 What is uncertain
    out += [heading(8), ""]
    for point in skeptic.against:
        refs = _valid_refs([point.claim_ref], c)
        if refs:
            out.append(f"- Against (model-written): {_safe(point.why)} {_refs(refs)}")
    if skeptic.stance == "unknown":
        out.append("- Unknown: no evidence against was found; that does not mean none exists.")
    for question in skeptic.open_questions:
        out.append(f"- Open question (model-written): {_safe(question)}")
    if c.window_estimated:
        out.append("- The deadline is estimated, not stated in the notice.")
    if len({k.document_id for k in c.claims}) <= 1:
        out.append("- All evidence comes from a single document.")
    if any(k.upgraded_from is not None for k in c.claims):
        out.append(
            "- The page was found through a search lead; its date is when we fetched it, "
            "not a date the publisher stated."
        )
    out.append("")

    # 9 Suggested action
    out += [heading(9), ""]
    out.append(f"Status: {action_status(entry)}. Caution: {caution(entry)}.")
    if entry.exploration:
        out.append(
            "Exploration pick: chosen at random from the leads below the cut, so the system "
            "learns what the cut misses. Rate it like any other lead (D89)."
        )
    stage_action = cfg.radar_action_by_stream.get(c.stream.value)
    if stage_action:
        out.append(f"Next step for this stage: {_inline(stage_action)}")
    opener = cfg.radar_opening_question_by_stream.get(c.stream.value)
    if opener:
        out.append(f"Opening question: {_inline(opener)}")
    out.append(
        _labelled("Suggestion (model-written)", _cited(gate.suggested_action, gate.cited_refs, c))
    )
    out.append("")
    out.append(DECISION_LINE)
    out.append("")
    return out


def main_selection(
    entries: list[RankedEntry], cap: int
) -> tuple[list[RankedEntry], list[RankedEntry]]:
    """(the `cap` entries that earn a full write-up, the rest). A full write-up needs a stated
    or related requirement or at least medium evidence. Accounts a person can approach come
    before tenders to watch (review of D80); short lists beat padded ones."""
    ordered = sorted(entries, key=lambda e: e.rank)

    def eligible(e: RankedEntry) -> bool:
        return e.requirement in ("stated", "related") or e.strength in ("strong", "medium")

    accounts = [e for e in ordered if eligible(e) and e.candidate.stream != RadarStream.TENDER]
    tenders = [e for e in ordered if eligible(e) and e.candidate.stream == RadarStream.TENDER]
    main = (accounts + tenders)[: max(cap, 0)]
    chosen = {id(e) for e in main}
    return main, [e for e in ordered if id(e) not in chosen]


def _briefed(run: RadarRun) -> tuple[list[RankedEntry], list[RankedEntry]]:
    """(full entries, weaker entries): the main selection, plus the exploration pick (D89),
    which takes one of the slots."""
    cap = get_settings().radar_brief_main_entries
    picked = [e for e in run.entries if e.exploration]
    others = [e for e in run.entries if not e.exploration]
    main, rest = main_selection(others, cap - len(picked))
    return main + picked, rest


def _approachable(entries: list[RankedEntry]) -> int:
    """Entries a person can approach; the random exploration pick never counts (D89)."""
    return sum(1 for e in entries if action_status(e) != "watch only" and not e.exploration)


_THIN_BELOW = 3


def _summary_table(entries: list[RankedEntry], today: date) -> list[str]:
    """One table row per entry, all code-composed from verified claims and settings."""
    out = [
        "| # | Status | Company | What | Evidence | Why now | Caution |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        level = (e.evidence_level or e.requirement).replace("_", " ")
        req = f"{level} [{e.requirement_ref}]" if e.requirement_ref else level
        status = action_status(e) + (" (exploration pick)" if e.exploration else "")
        out.append(
            f"| {e.rank} | {status} | {_name(e.candidate)} | "
            f"{_what(e.candidate)} | {req} | {_cell(_why_now(e, today))} | "
            f"{_cell(caution(e))} |"
        )
    return out


def _summary(run: RadarRun, today: date) -> list[str]:
    """The one screen a salesperson reads first: accounts to approach, then tenders to watch,
    kept apart so project intelligence is never mistaken for a material buyer (D80)."""
    cap = get_settings().radar_brief_main_entries
    ordered = sorted(run.entries, key=lambda e: e.rank)
    accounts = [e for e in ordered if e.candidate.stream != RadarStream.TENDER][:cap]
    tenders = [e for e in ordered if e.candidate.stream == RadarStream.TENDER][:cap]
    for e in ordered:  # the exploration pick always shows, in its own table (D89)
        if e.exploration:
            table = tenders if e.candidate.stream == RadarStream.TENDER else accounts
            if e not in table:
                table.append(e)
    out = ["### Accounts to approach", ""]
    out += _summary_table(accounts, today) if accounts else ["None this time."]
    out += ["", "### Tenders to watch", ""]
    out += _summary_table(tenders, today) if tenders else ["None this time."]
    return out


def render_brief(run: RadarRun) -> str:
    """The Markdown brief: a one-screen summary, then nine questions per full entry with
    verified claims and verbatim quotes, then the weaker entries and the rejections."""
    shown, rest = _briefed(run)
    today = run.as_of.date()
    kinds = ", ".join(f"{k} {v}" for k, v in sorted(run.documents_by_kind.items())) or "none"
    refused = sum(1 for u in run.upgraded if u.refused is not None)
    out = [f"# Opportunity brief: {_inline(run.client_id)}", "", "## Summary", ""]
    out += _summary(run, today)
    out += [
        "",
        "Evidence: *explicit purchase* means a verified quote names what you sell and the "
        "account buys it itself; *project requirement* means the project needs it but the "
        "material buyer still has to be traced; *generic mention* means the words match without "
        "a supported buying relationship; *no evidence* means a possibility only. Status: "
        "*contact now*, *bid now* (a supplies tender the authority buys itself), *qualify "
        "first*, or *watch only* (a works or services tender: the material buyer is the future "
        "winner). Every fact in the full write-ups below links to its source.",
        "",
    ]
    approachable = _approachable(shown)
    if approachable < _THIN_BELOW:
        out += [
            "## Thin sources",
            "",
            f"Only {approachable} {'account is' if approachable == 1 else 'accounts are'} "
            "strong enough to approach this time. Nothing was added to fill the space.",
            "",
        ]
    out += [
        "## Run",
        "",
        f"- Client: {_inline(run.client_id)}",
        f"- Offer: {_safe(run.offer)}",
        f"- As of: {_day(run.as_of)}",
        f"- Documents read, by kind: {kinds}",
        f"- Leads from search: {run.leads}",
        f"- Leads upgraded to full pages: {len(run.upgraded) - refused} succeeded, "
        f"{refused} refused",
        f"- Model calls: {run.llm_calls}; cost: ${run.cost_usd:.4f}",
    ]
    out += [f"- Run note: {_safe(note)}" for note in run.notes]
    out += [
        "",
        "## Streams",
        "",
        "Tenders and awards are listed in official registers. For those, every matching "
        "notice in the query window was read. Announcements are not listed anywhere. For "
        "those we find some, never all.",
        "",
        "## Entries",
        "",
    ]
    if not shown:
        out += ["No entry passed.", ""]
    for entry in shown:
        out += _entry_block(entry)
    if rest:
        out += [
            "## Also found, weaker",
            "",
            "| # | Company | Stream | Requirement | Evidence | Why now |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        out += [
            f"| {e.rank} | {_name(e.candidate)} | {e.candidate.stream.value} | "
            f"{e.requirement} | {e.strength} | {_cell(_why_now(e, today))} |"
            for e in rest
        ]
        out.append("")
    out += ["## Rejected", ""]
    if run.rejected:
        out += ["| Name | Rejected as | By | Reason |", "| --- | --- | --- | --- |"]
        for rej in run.rejected:
            person = rej.gate.rejected_as == RejectedAs.NOT_AN_ORGANISATION
            name = PERSON_NAME if person else (_cell(rej.candidate.name) or NO_NAME)
            reason = "(withheld)" if person else _cell(rej.gate.reason)
            rejected_as = rej.gate.rejected_as.value if rej.gate.rejected_as else NOT_STATED
            out.append(f"| {name} | {rejected_as} | {rej.gate.by} | {reason} |")
    else:
        out.append("Nothing was rejected.")
    out.append("")
    return "\n".join(out)


# ----------------------------------------------------------------------------- scorecard


def render_scorecard(run: RadarRun) -> str:
    """The founder's scorecard: one row per entry, four yes/no columns, failure chips."""
    shown, _ = _briefed(run)
    out = [
        f"# Scorecard: {_inline(run.client_id)} ({_day(run.as_of)})",
        "",
        "Rate each entry in `brief.md`. Write yes or no in each of the four columns. "
        "If a row is no, add one failure chip.",
        "",
        "- Correct: every fact matches its source.",
        "- Relevant: a plausible buyer of this offer.",
        "- New or worth acting on: for the client whose business you know, previously "
        "unknown to you; for other clients, would a salesperson in that industry act on this?",
        "- Actionable: a person knows who to approach and why now.",
        "",
        "Failure chips: " + " / ".join(_FAILURE_CHIPS) + ".",
        "",
        "Also skim the Rejected table. Mark any rejection that was actually a good buyer "
        "as a wrong rejection.",
        "",
        "| # | Company | Stream | Correct | Relevant | New (your own business: previously "
        "unknown) or worth acting on (others: would a salesperson act on this?) | Actionable | "
        "Failure chip |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in shown:
        out.append(
            f"| {entry.rank} | {_name(entry.candidate)} | "
            f"{entry.candidate.stream.value} |  |  |  |  |  |"
        )
    if not shown:
        out.append("|  | (no entries passed) |  |  |  |  |  |  |")
    out += [
        "",
        "Rule for the third column: your own business: previously unknown; other clients: would "
        "a salesperson in that industry act on this?",
        "",
        "Wrong rejections: ____ of ____ rejected rows checked.",
        "",
        "## After contact (the salesperson fills this in)",
        "",
        "Known already? yes or no. New intelligence? (a new date, project, signal, route or reason "
        "to act, even on a known account). Contacted? yes or no. Outcome: none, redirect, info "
        "request, requirement, sample, quote or meeting.",
        "",
        "| # | Company | Known already? | New intelligence? | Contacted? | Outcome |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in sorted(run.entries, key=lambda e: e.rank):
        if action_status(entry) != "watch only":
            out.append(f"| {entry.rank} | {_name(entry.candidate)} |  |  |  |  |")
    out += [
        "",
    ]
    return "\n".join(out)


# ----------------------------------------------------------------------------- files


def write_reports(run: RadarRun, out_dir: Path) -> list[Path]:
    """Write brief.md, scorecard.md and run.json under `out_dir`; return the paths."""
    target = Path(out_dir) / run.client_id / _day(run.as_of)
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "brief.md": render_brief(run),
        "scorecard.md": render_scorecard(run),
        "run.json": run.model_dump_json(indent=2) + "\n",
    }
    paths = []
    for name, text in files.items():
        path = target / name
        path.write_bytes(text.encode("utf-8"))
        paths.append(path)
    return paths
