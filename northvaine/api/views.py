"""Response shapes for the web app, composed from a run by reusing the brief's own helpers
(action status, caution, what, why-now), so the page and brief.md never disagree."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from northvaine.core.settings import Settings
from northvaine.radar import brief
from northvaine.radar.models import RadarRun, RadarStream, RankedEntry


class Row(BaseModel):
    rank: int
    status: str
    company: str
    country: str
    stream: str
    what: str
    requirement: str
    requirement_ref: str | None
    why_now: str
    caution: str


class BriefView(BaseModel):
    client_id: str
    offer: str
    as_of: str
    accounts: list[Row]
    tenders: list[Row]
    weaker: list[Row]
    thin: bool
    notes: list[str]


class Claim(BaseModel):
    ref: str
    statement: str
    quote: str
    url: str
    source: str
    is_value: bool


class Source(BaseModel):
    url: str
    name: str
    available: str
    kinds: list[str]


class Sentence(BaseModel):
    """A line of text for the page. `model_written` marks sentences an AI wrote."""

    text: str
    model_written: bool = False


class Bidder(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    country: str | None = None
    wins: int
    last_won: str | None = None
    source_url: str
    quote: str


class Dossier(BaseModel):
    rank: int
    company: str
    country: str
    stream: str
    stream_note: str
    status: str
    caution: str
    strength: str
    who_roles: list[str]
    what: str
    when: list[str]
    demand: Sentence
    claims: list[Claim]
    sources: list[Source]
    requirement: str
    requirement_ref: str | None
    who_buys: str | None
    direct_buyer: str
    buyer_reason: Sentence
    uncertain: list[Sentence]
    stage_action: str | None
    opening_question: str | None
    suggestion: Sentence
    rank_reasons: list[str]
    likely_bidders: list[Bidder]
    decision_line: str


def _row(entry: RankedEntry, today: date) -> Row:
    c = entry.candidate
    return Row(
        rank=entry.rank,
        status=brief.action_status(entry),
        company=brief._name(c),
        country=brief._country(c.country),
        stream=c.stream.value,
        what=brief._what(c),
        requirement=entry.requirement,
        requirement_ref=entry.requirement_ref,
        why_now=brief._why_now(entry, today),
        caution=brief.caution(entry),
    )


def brief_view(run: RadarRun, settings: Settings) -> BriefView:
    today = run.as_of.date()
    cap = settings.radar_brief_main_entries
    ordered = sorted(run.entries, key=lambda e: e.rank)
    accounts = [e for e in ordered if e.candidate.stream != RadarStream.TENDER][:cap]
    tenders = [e for e in ordered if e.candidate.stream == RadarStream.TENDER][:cap]
    shown = {id(e) for e in accounts + tenders}
    weaker = [e for e in ordered if id(e) not in shown]
    return BriefView(
        client_id=run.client_id,
        offer=brief._inline(run.offer),
        as_of=brief._day(run.as_of),
        accounts=[_row(e, today) for e in accounts],
        tenders=[_row(e, today) for e in tenders],
        weaker=[_row(e, today) for e in weaker],
        thin=len(accounts) + len(tenders) < brief._THIN_BELOW,
        notes=[brief._inline(n) for n in run.notes],
    )


def _sentence(text: str | None, cited: list[str], entry: RankedEntry) -> Sentence:
    return Sentence(text=brief._cited(text, cited, entry.candidate), model_written=True)


def _what_happened(entry: RankedEntry) -> str:
    c = entry.candidate
    plain = brief._plain_happened(c)
    if plain is not None:
        return plain
    if c.events:
        return " ".join(
            f"{brief._inline(ev.description)} {brief._refs(brief._valid_refs(ev.claim_refs, c))}"
            for ev in c.events
        )
    return brief.NOT_STATED


def _uncertain(entry: RankedEntry) -> list[Sentence]:
    c, skeptic = entry.candidate, entry.skeptic
    out: list[Sentence] = []
    for point in skeptic.against:
        refs = brief._valid_refs([point.claim_ref], c)
        if refs:
            text = f"{brief._inline(point.why)} {brief._refs(refs)}"
            out.append(Sentence(text=text, model_written=True))
    if skeptic.stance == "unknown":
        out.append(Sentence(text="No evidence against was found; that does not mean none exists."))
    out += [Sentence(text=brief._inline(q), model_written=True) for q in skeptic.open_questions]
    if c.window_estimated:
        out.append(Sentence(text="The deadline is estimated, not stated in the notice."))
    if len({k.document_id for k in c.claims}) <= 1:
        out.append(Sentence(text="All evidence comes from a single document."))
    if any(k.upgraded_from is not None for k in c.claims):
        out.append(
            Sentence(
                text="The page was found through a search lead; its date is when we fetched it, "
                "not a date the publisher stated."
            )
        )
    return out


def _sources(entry: RankedEntry) -> list[Source]:
    seen: dict[tuple[str, str, str], list[str]] = {}
    for claim in entry.candidate.claims:
        key = (claim.url, claim.source_name, brief._day(claim.available_at))
        kinds = seen.setdefault(key, [])
        kind = brief._source_kind(claim)
        if kind not in kinds:
            kinds.append(kind)
    return [
        Source(url=u, name=brief._inline(n), available=a, kinds=kinds)
        for (u, n, a), kinds in seen.items()
    ]


def dossier(entry: RankedEntry, raw_bidders: list[dict], settings: Settings) -> Dossier:
    c, gate = entry.candidate, entry.gate
    stream = c.stream.value
    when = [
        f"Event date: {brief._day(ev.occurred_on)} "
        f"{brief._refs(brief._valid_refs(ev.claim_refs, c))}".strip()
        for ev in c.events
    ]
    when.append(f"Window: {brief._window_line(c)}")
    who_buys = settings.radar_buyer_note_by_stream.get(stream)
    stage_action = settings.radar_action_by_stream.get(stream)
    opener = settings.radar_opening_question_by_stream.get(stream)
    direct = {True: "yes, buys directly", False: "no, reached through others"}.get(
        gate.direct_buyer, brief.NOT_STATED
    )
    return Dossier(
        rank=entry.rank,
        company=brief._name(c),
        country=brief._country(c.country),
        stream=stream,
        stream_note=brief._STREAM_NOTE[c.stream],
        status=brief.action_status(entry),
        caution=brief.caution(entry),
        strength=entry.strength,
        who_roles=[brief._inline(r) for r in c.roles],
        what=_what_happened(entry),
        when=when,
        demand=_sentence(gate.demand_reason, gate.cited_refs, entry),
        claims=[
            Claim(
                ref=k.ref,
                statement=brief._inline(k.statement),
                quote=k.source_quote,
                url=k.url,
                source=brief._inline(k.source_name),
                is_value=brief._is_value(k),
            )
            for k in c.claims
        ],
        sources=_sources(entry),
        requirement=entry.requirement,
        requirement_ref=entry.requirement_ref,
        who_buys=brief._inline(who_buys) if who_buys else None,
        direct_buyer=direct,
        buyer_reason=_sentence(gate.buyer_reason, gate.cited_refs, entry),
        uncertain=_uncertain(entry),
        stage_action=brief._inline(stage_action) if stage_action else None,
        opening_question=brief._inline(opener) if opener else None,
        suggestion=_sentence(gate.suggested_action, gate.cited_refs, entry),
        rank_reasons=[brief._inline(r) for r in entry.rank_reasons],
        likely_bidders=[Bidder.model_validate(b) for b in raw_bidders],
        decision_line=brief.DECISION_LINE,
    )
