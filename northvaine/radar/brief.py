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

from northvaine.core.models import EvidenceKind
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import iso2_to_name
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
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
    """(strength, verified claims, documents)."""
    claims = candidate.claims
    documents = len({c.document_id for c in claims})
    structured = [c for c in claims if c.evidence_kind == EvidenceKind.STRUCTURED]
    if documents >= 2 or len(structured) >= 3:
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
    dates: list[date] = []
    for event in candidate.events:
        if event.occurred_on is not None:
            dates.append(event.occurred_on)
        elif event.available_at is not None:
            dates.append(event.available_at.date())
    return max(dates) if dates else None


def offer_terms(offer: str, settings: Settings | None = None) -> set[str]:
    """The content words of the client's own offer text (D80): what a quote must name for the
    requirement to count as stated. Generic stopwords come from settings, never industry words."""
    cfg = settings or get_settings()
    stop = {w.casefold() for w in cfg.radar_offer_stopwords}
    return {
        w.casefold()
        for w in _WORD.findall(offer)
        if len(w) >= cfg.radar_offer_term_min_chars and w.casefold() not in stop
    }


def _names_term(quote: str, terms: set[str]) -> bool:
    """A whole word, its singular or plural, or (for longer terms) part of a compound word."""
    text = quote.casefold()
    words = {w.casefold() for w in _WORD.findall(quote)}
    for term in terms:
        stem = term[:-1] if term.endswith("s") and len(term) > 4 else term
        if term in words or stem in words or f"{stem}s" in words or f"{stem}es" in words:
            return True
        if len(stem) >= 5 and stem in text:
            return True
    return False


def requirement_of(candidate: Candidate, terms: set[str]) -> tuple[str, str | None]:
    """('stated', ref) when a verified quote of the candidate names an offer term, found by
    code; ('inferred', None) otherwise. The model's opinion plays no part (D80)."""
    if terms:
        for claim in candidate.claims:
            if _names_term(claim.source_quote, terms):
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
    last = _last_dated(candidate)
    if last is not None:
        age = (today - last).days
        if 0 <= age <= recent_days:
            return (
                _TIER_RECENT,
                age,
                f"Timing: dated {last.isoformat()} ({_plural(age, 'day')} ago)",
            )
        return _TIER_UNDATED, 0, f"Timing: dated {last.isoformat()}, not recent"
    return _TIER_UNDATED, 0, "Timing: no date stated"


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
) -> list[RankedEntry]:
    """Lexicographic order by (requirement stated before inferred, window urgency or recency,
    evidence strength, direct buyer), each component explained in `rank_reasons`; no numeric
    score (D64, D80). Uncertainty lowers rank."""
    cfg = settings or get_settings()
    today = as_of.date()
    terms = offer_terms(offer, cfg)
    scored = []
    for candidate, gate, skeptic in passed:
        strength, claims, documents = _strength(candidate)
        tier, position, urgency_line = _urgency(
            candidate, today, cfg.radar_recent_days, cfg.radar_min_days_left
        )
        requirement, requirement_ref = requirement_of(candidate, terms)
        requirement_line = (
            f"Requirement: stated (a verified quote names what you sell) [{requirement_ref}]"
            if requirement == "stated"
            else "Requirement: inferred (no verified quote names what you sell)"
        )
        reasons = [
            requirement_line,
            urgency_line,
            _evidence_reason(candidate, claims, documents),
            _buyer_reason(gate),
        ]
        key = (
            0 if requirement == "stated" else 1,
            tier,
            _STRENGTH_ORDER[strength],
            position,
            0 if gate.direct_buyer is True else 1,
            candidate.name,
        )
        scored.append(
            (key, candidate, gate, skeptic, strength, reasons, requirement, requirement_ref)
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
        )
        for i, (_, candidate, gate, skeptic, strength, reasons, requirement, requirement_ref) in (
            enumerate(scored, start=1)
        )
    ]


# ----------------------------------------------------------------------------- helpers


def _inline(text: str) -> str:
    """One line, so untrusted or model text cannot start a heading, list or quote."""
    return re.sub(r"\s+", " ", text).strip()


def _cell(text: str) -> str:
    return _inline(text).replace("|", "\\|")


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
    return f"{_inline(text)} {_refs(refs)}"


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
    return _inline(candidate.name) or NO_NAME


def _labelled(label: str, sentence: str) -> str:
    return NOT_STATED if sentence == NOT_STATED else f"{label}: {sentence}"


def _claim_starting(candidate: Candidate, prefix: str) -> CandidateClaim | None:
    return next((c for c in candidate.claims if c.source_quote.startswith(prefix)), None)


def _title(candidate: Candidate) -> CandidateClaim | None:
    return next((c for c in candidate.claims if _TITLE_PREFIX.match(c.source_quote)), None)


def _quoted_value(claim: CandidateClaim, prefix_re: re.Pattern[str] | str) -> str:
    text = claim.source_quote
    if isinstance(prefix_re, str):
        return _inline(text[len(prefix_re) :])
    return _inline(prefix_re.sub("", text, count=1))


def _what(candidate: Candidate, limit: int = 90) -> str:
    """What the opportunity is about: the record's title when there is one, else the first
    verified statement. Code-composed from verified claims only."""
    title = _title(candidate)
    text = _quoted_value(title, _TITLE_PREFIX) if title else ""
    if not text and candidate.claims:
        text = _inline(candidate.claims[0].statement)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or NOT_STATED


def _plain_happened(candidate: Candidate) -> str | None:
    """One readable sentence for an official record, each part with its claim ref, built from
    the record's own lines (D80). None when the candidate has no such record."""
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


def action_status(entry: RankedEntry) -> str:
    """contact now / qualify first / watch only (WOS field test, D80). Before an award the named
    authority is a demand source, not the material buyer, so a tender is a watch item."""
    if entry.candidate.stream == RadarStream.TENDER:
        return "watch only"
    return "contact now" if entry.requirement == "stated" else "qualify first"


def caution(entry: RankedEntry) -> str:
    """The most important thing not yet known, composed by code."""
    c = entry.candidate
    if c.stream == RadarStream.TENDER:
        return "the authority runs the tender; the material buyer is unknown until the award"
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
        if left < 0:
            return f"tender closed {c.window_end.isoformat()}"
        return f"tender closes in {_plural(left, 'day')}"
    last = _last_dated(c)
    if c.stream == RadarStream.AWARD:
        return f"contract awarded {_day(last)}" if last else "contract awarded"
    return f"announced {_day(last)}" if last else "date not stated"


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
    roles = ", ".join(_inline(r) for r in c.roles) or NOT_STATED
    out += [heading(1), "", f"{_name(c)}, {_country(c.country)}. Roles: {roles}.", ""]

    # 2 What happened
    out += [heading(2), ""]
    plain = _plain_happened(c)
    if plain is not None:
        out.append(plain)
    elif c.events:
        for ev in c.events:
            refs = _refs(_valid_refs(ev.claim_refs, c))
            out.append(f"- {_inline(ev.description)} {refs}".rstrip())
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
        out.append(f"**[{claim.ref}]** {_inline(claim.statement)}")
        out.append("")
        out += [f"> {line}" for line in claim.source_quote.split("\n")]
        out.append("")
        if _is_value(claim):
            out += ["(Value of the whole contract, not the share for what you sell.)", ""]

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
        out.append(f"- {url} ({_inline(source)}); available {available}; {', '.join(labels)}")
    if not seen:
        out.append(NOT_STATED)
    out.append("")

    # 7 Why a buyer
    out += [heading(7), ""]
    cfg = get_settings()
    out.append(
        f"Requirement: {entry.requirement}"
        + (f" [{entry.requirement_ref}]" if entry.requirement_ref else "")
        + (
            ""
            if entry.requirement == "stated"
            else " (no verified quote names what you sell; treat this as a possibility)"
        )
        + "."
    )
    who_buys = cfg.radar_buyer_note_by_stream.get(c.stream.value)
    if who_buys:
        out.append(f"Who buys: {_inline(who_buys)}")
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
            out.append(f"- Against (model-written): {_inline(point.why)} {_refs(refs)}")
    if skeptic.stance == "unknown":
        out.append("- Unknown: no evidence against was found; that does not mean none exists.")
    for question in skeptic.open_questions:
        out.append(f"- Open question (model-written): {_inline(question)}")
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


def _briefed(run: RadarRun) -> tuple[list[RankedEntry], list[RankedEntry]]:
    """(full entries, weaker entries). Only a stated requirement or strong evidence earns a full
    entry, up to `radar_brief_main_entries`; short lists beat padded ones (D80)."""
    cap = get_settings().radar_brief_main_entries
    ordered = sorted(run.entries, key=lambda e: e.rank)
    main = [e for e in ordered if e.requirement == "stated" or e.strength == "strong"][:cap]
    chosen = {id(e) for e in main}
    return main, [e for e in ordered if id(e) not in chosen]


_THIN_BELOW = 3


def _summary_table(entries: list[RankedEntry], today: date) -> list[str]:
    """One table row per entry, all code-composed from verified claims and settings."""
    out = [
        "| # | Status | Company | What | Requirement | Why now | Caution |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        req = f"stated [{e.requirement_ref}]" if e.requirement == "stated" else "inferred"
        out.append(
            f"| {e.rank} | {action_status(e)} | {_cell(_name(e.candidate))} | "
            f"{_cell(_what(e.candidate))} | {req} | {_cell(_why_now(e, today))} | "
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
        "Requirement: *stated* means a verified quote names what you sell; *inferred* means it "
        "is a possibility only. Status: *contact now*, *qualify first*, or *watch only* (a "
        "tender before award: the material buyer is not known yet). Every fact below links to "
        "its source.",
        "",
    ]
    if len(shown) < _THIN_BELOW:
        out += [
            "## Thin sources",
            "",
            f"Only {len(shown)} {'entry is' if len(shown) == 1 else 'entries are'} strong enough "
            "for a full write-up. Nothing was added to fill the space.",
            "",
        ]
    out += [
        "## Run",
        "",
        f"- Client: {_inline(run.client_id)}",
        f"- Offer: {_inline(run.offer)}",
        f"- As of: {_day(run.as_of)}",
        f"- Documents read, by kind: {kinds}",
        f"- Leads from search: {run.leads}",
        f"- Leads upgraded to full pages: {len(run.upgraded) - refused} succeeded, "
        f"{refused} refused",
        f"- Model calls: {run.llm_calls}; cost: ${run.cost_usd:.4f}",
    ]
    out += [f"- Run note: {_inline(note)}" for note in run.notes]
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
            f"| {e.rank} | {_cell(_name(e.candidate))} | {e.candidate.stream.value} | "
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
            f"| {entry.rank} | {_cell(_name(entry.candidate))} | "
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
            out.append(f"| {entry.rank} | {_cell(_name(entry.candidate))} |  |  |  |  |")
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
