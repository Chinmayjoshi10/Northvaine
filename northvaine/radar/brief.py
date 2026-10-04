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
_TIER_OPEN, _TIER_RECENT, _TIER_UNDATED, _TIER_CLOSED = 0, 1, 2, 3

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


def _urgency(candidate: Candidate, today: date, recent_days: int) -> tuple[int, int, str]:
    """(tier, position inside the tier, reason line). Lower sorts first."""
    end = candidate.window_end
    if candidate.stream == RadarStream.TENDER and end is not None:
        how = "estimated deadline" if candidate.window_estimated else "stated deadline"
        left = (end - today).days
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
) -> list[RankedEntry]:
    """Lexicographic order by (evidence strength, window urgency or recency, direct buyer),
    each component explained in `rank_reasons`; no numeric score (D64)."""
    cfg = settings or get_settings()
    today = as_of.date()
    scored = []
    for candidate, gate, skeptic in passed:
        strength, claims, documents = _strength(candidate)
        tier, position, urgency_line = _urgency(candidate, today, cfg.radar_recent_days)
        reasons = [
            _evidence_reason(candidate, claims, documents),
            urgency_line,
            _buyer_reason(gate),
        ]
        key = (
            _STRENGTH_ORDER[strength],
            tier,
            position,
            0 if gate.direct_buyer is True else 1,
            candidate.name,
        )
        scored.append((key, candidate, gate, skeptic, strength, reasons))
    scored.sort(key=lambda item: item[0])
    return [
        RankedEntry(
            rank=i,
            candidate=candidate,
            gate=gate,
            skeptic=skeptic,
            strength=strength,
            rank_reasons=reasons,
        )
        for i, (_, candidate, gate, skeptic, strength, reasons) in enumerate(scored, start=1)
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
    if c.events:
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
    out.append(
        _labelled("Suggestion (model-written)", _cited(gate.suggested_action, gate.cited_refs, c))
    )
    out.append("")
    out.append(DECISION_LINE)
    out.append("")
    return out


def _briefed(run: RadarRun) -> tuple[list[RankedEntry], list[RankedEntry]]:
    limit = get_settings().radar_brief_entries
    ordered = sorted(run.entries, key=lambda e: e.rank)
    return ordered[:limit], ordered[limit:]


def render_brief(run: RadarRun) -> str:
    """The Markdown brief: nine questions per entry, verified claims with verbatim quotes."""
    limit = get_settings().radar_brief_entries
    shown, rest = _briefed(run)
    kinds = ", ".join(f"{k} {v}" for k, v in sorted(run.documents_by_kind.items())) or "none"
    refused = sum(1 for u in run.upgraded if u.refused is not None)
    out = [
        f"# Opportunity brief: {_inline(run.client_id)}",
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
    if len(run.entries) < limit:
        out += [
            "## Thin sources",
            "",
            f"Only {len(run.entries)} of a possible {limit} entries passed. Sources are thin "
            "for this client. Nothing was added to fill the space.",
            "",
        ]
    if rest:
        out += ["## Also passed", ""]
        out += [
            f"- {entry.rank}. {_name(entry.candidate)} "
            f"({entry.candidate.stream.value}, evidence {entry.strength})"
            for entry in rest
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
