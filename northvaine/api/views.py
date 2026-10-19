"""Response shapes for the web app, composed from a run by reusing the brief's own helpers
(action status, caution, what, why-now), so the page and brief.md never disagree."""

from __future__ import annotations

import re
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from northvaine.core.settings import Settings
from northvaine.radar import brief
from northvaine.radar.edition import daily_edition
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
    RadarRun,
    RadarStream,
    RankedEntry,
)
from northvaine.radar.watch import developments


class Link(BaseModel):
    """One step of the commercial chain. `state` is how it is known: stated (a verified quote),
    inferred (code reasoning over verified records) or unknown. Never a guess dressed as fact."""

    # authority | project | contract | contractor | buyer; a trade record (D102): importer |
    # product | history | buyer
    slot: str
    label: str
    state: str  # stated | inferred | unknown
    quote: str | None = None
    url: str | None = None


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
    # D94: who the account is and how strong its evidence is (None in older run records)
    account_role: str | None = None
    evidence_level: str | None = None
    contract_nature: str | None = None
    company_key: str = ""
    chain: list[Link] = []
    # D103: act_now | just_changed | account_to_work, and the fact behind it
    label: str | None = None
    label_reason: str | None = None
    # also briefed in the client's previous run (False when there is no previous run)
    returning: bool = False
    # D110: watching over time, against all the client's earlier runs
    first_seen: str | None = None
    seen_runs: int = 0
    developments: list[str] = []
    back_in_motion: bool = False
    timing_signals: list[str] = []  # D111


class Funnel(BaseModel):
    """What the run looked at and what it set aside: all counted, none guessed."""

    documents: int
    candidates: int
    rejected: dict[str, int]  # reason -> count
    briefed: int


class LogItem(BaseModel):
    """One thing the run saw, as recorded: when it became public, what, and about whom."""

    at: str | None  # ISO time the source made it public; None when the source gives none
    kind: str  # an event type, or "set_aside"
    text: str
    company: str | None
    rank: int | None  # the situation it belongs to, when it is one


class BriefView(BaseModel):
    client_id: str
    offer: str
    client_name: str | None = None
    # the client's previous run date, when there is one; `Row.returning` compares with it
    previous: str | None = None
    as_of: str
    accounts: list[Row]
    tenders: list[Row]
    weaker: list[Row]
    thin: bool
    notes: list[str]
    funnel: Funnel | None = None
    log: list[LogItem] = []
    # D103: today's few checked targets, labelled; empty on a thin day (never padded)
    edition: list[Row] = []


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


class CompanyContactView(BaseModel):
    email: str | None
    phone: str | None
    url: str


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
    company_site: str | None = None
    site_proof: str | None = None
    company_contact: CompanyContactView | None = None
    like_customers: list[str] = []
    timing_signals: list[str] = []  # D111


_MD_ESCAPE = re.compile(r"\\([\\`*_\[\]()<>!#|~])")


def _plain(text: str) -> str:
    """Brief text without its Markdown escapes (brief._safe): the app renders plain text,
    never Markdown, so an escaped bracket must reach it as a bracket."""
    return _MD_ESCAPE.sub(r"\1", text)


def _plain_name(candidate: Candidate) -> str:
    return _plain(brief._name(candidate))


def _plain_what(candidate: Candidate) -> str:
    return _plain(brief._what(candidate))


def _row(entry: RankedEntry, today: date) -> Row:
    c = entry.candidate
    return Row(
        rank=entry.rank,
        status=brief.action_status(entry),
        company=_plain_name(c),
        country=brief._country(c.country),
        stream=c.stream.value,
        what=_plain_what(c),
        requirement=entry.requirement,
        requirement_ref=entry.requirement_ref,
        why_now=brief._why_now(entry, today),
        caution=brief.caution(entry),
        account_role=entry.account_role,
        evidence_level=entry.evidence_level,
        contract_nature=entry.contract_nature,
        company_key=c.key,
        chain=chain(entry),
        label=entry.label,
        label_reason=entry.label_reason,
        timing_signals=list(c.timing_signals),
    )


def _now_on_record(entry: RankedEntry, earlier: list[RankedEntry]) -> list[str]:
    """Chain slots that were unknown or inferred on the latest earlier entry and are stated now."""
    if not earlier:
        return []
    before = {link.slot: link.state for link in chain(earlier[-1])}
    return [
        f"Now on record: {link.slot}"
        for link in chain(entry)
        if link.state == "stated" and before.get(link.slot) in ("unknown", "inferred")
    ]


def brief_view(
    run: RadarRun,
    settings: Settings,
    previous: RadarRun | None = None,
    earlier: list[RadarRun] | None = None,
) -> BriefView:
    """`earlier`: the client's runs before this one (any order), for the D110 watch fields."""
    today = run.as_of.date()
    seen = {e.candidate.key for e in previous.entries} if previous else set()
    watch = developments(run, earlier or [], settings)
    oldest = run.as_of.date() - timedelta(days=settings.radar_watch_days)
    window = sorted(
        (r for r in earlier or [] if oldest <= r.as_of.date() < today), key=lambda r: r.as_of
    )

    def row(e: RankedEntry) -> Row:
        out = _row(e, today)
        if seen:
            out = out.model_copy(update={"returning": e.candidate.key in seen})
        w = watch.get(e.candidate.key)
        if w is None:
            return out
        key = e.candidate.key
        prior = [x for r in window for x in r.entries if x.candidate.key == key]
        # a slot now on record is listed, but on its own it is what we learned, not a move
        changes = [*w.changes, *_now_on_record(e, prior)]
        return out.model_copy(
            update={
                "first_seen": w.first_seen.isoformat(),
                "seen_runs": w.seen_runs,
                "developments": changes,
                "back_in_motion": w.back_in_motion,
            }
        )

    cap = settings.radar_brief_main_entries
    ordered = sorted(run.entries, key=lambda e: e.rank)
    accounts = [e for e in ordered if e.candidate.stream != RadarStream.TENDER][:cap]
    tenders = [e for e in ordered if e.candidate.stream == RadarStream.TENDER][:cap]
    shown = {id(e) for e in accounts + tenders}
    weaker = [e for e in ordered if id(e) not in shown]
    return BriefView(
        client_id=run.client_id,
        offer=brief._inline(run.offer),
        client_name=run.client_name,
        previous=brief._day(previous.as_of) if previous else None,
        as_of=brief._day(run.as_of),
        accounts=[row(e) for e in accounts],
        tenders=[row(e) for e in tenders],
        weaker=[row(e) for e in weaker],
        thin=len(accounts) + len(tenders) < brief._THIN_BELOW,
        notes=[brief._inline(n) for n in run.notes],
        funnel=_funnel(run),
        log=_log(run),
        edition=[row(e) for e in daily_edition(ordered, settings)],
    )


# Only organisations are named in the log; other set-aside mentions may be people (D76).
_NAMED_ASIDE = {"competitor", "reseller", "publisher", "not_a_buyer"}
_ASIDE_TEXT = {
    "competitor": "a competitor",
    "reseller": "sells what you sell",
    "publisher": "a publisher, not a buyer",
    "not_a_buyer": "not a buyer",
}


def _log(run: RadarRun, limit: int = 60) -> list[LogItem]:
    items: list[LogItem] = []
    for entry in run.entries:
        c = entry.candidate
        for ev in c.events:
            when = ev.available_at or next(
                (k.available_at for k in c.claims if k.ref in ev.claim_refs and k.available_at),
                None,
            )
            items.append(
                LogItem(
                    at=when.isoformat() if when else None,
                    kind=ev.event_type,
                    text=brief._inline(ev.description),
                    company=_plain_name(c),
                    rank=entry.rank,
                )
            )
    items.sort(key=lambda i: i.at or "", reverse=True)
    for r in run.rejected:
        reason = r.gate.rejected_as.value if r.gate.rejected_as else ""
        named = reason in _NAMED_ASIDE and not r.candidate.name.startswith("[")
        items.append(
            LogItem(
                at=None,
                kind="set_aside",
                text=f"Set aside: {_ASIDE_TEXT[reason]}"
                if named
                else "Set aside a mention with no identifiable organisation",
                company=_plain_name(r.candidate) if named else None,
                rank=None,
            )
        )
    return items[:limit]


def _funnel(run: RadarRun) -> Funnel:
    rejected: dict[str, int] = {}
    for r in run.rejected:
        reason = r.gate.rejected_as.value if r.gate.rejected_as else "rejected"
        rejected[reason] = rejected.get(reason, 0) + 1
    return Funnel(
        documents=sum(run.documents_by_kind.values()),
        candidates=len(run.entries) + len(run.rejected),
        rejected=rejected,
        briefed=len(run.entries),
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
        company=_plain_name(c),
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
        company_site=entry.company_site,
        site_proof=entry.site_proof,
        like_customers=list(entry.candidate.like_customers),
        timing_signals=list(entry.candidate.timing_signals),
        company_contact=(
            CompanyContactView(**entry.company_contact.model_dump())
            if entry.company_contact
            else None
        ),
    )


def _line(entry: RankedEntry, prefix: str) -> CandidateClaim | None:
    return next((k for k in entry.candidate.claims if k.source_quote.startswith(prefix)), None)


def _stated(slot: str, label: str, claim: CandidateClaim) -> Link:
    return Link(slot=slot, label=label, state="stated", quote=claim.source_quote, url=claim.url)


def chain(entry: RankedEntry) -> list[Link]:
    """Authority -> project -> contract -> contractor -> who buys what the client sells, each
    step as known from the run's verified record lines (D94), composed by code."""
    c, role = entry.candidate, entry.account_role
    if c.stream == RadarStream.TRADE:
        return _trade_chain(entry)
    name = _plain_name(c)
    buyer, title = _line(entry, "Buyer ["), _line(entry, "Title [")
    winner = _line(entry, "Winner [")
    unknown = lambda slot, label: Link(slot=slot, label=label, state="unknown")  # noqa: E731

    if buyer is not None:
        authority = _stated("authority", brief._after_colon(buyer.source_quote), buyer)
    elif role in ("demand_source", "direct_purchaser") and c.claims:
        authority = _stated("authority", name, c.claims[0])
    else:
        authority = unknown("authority", "who runs the project")

    project = (
        _stated("project", brief._after_colon(title.source_quote), title)
        if title is not None
        else Link(slot="project", label=_plain_what(c), state="inferred")
        if c.events
        else unknown("project", "the project")
    )

    nature = entry.contract_nature or "contract"
    if winner is not None:
        contract = _stated("contract", f"{nature} contract awarded", winner)
    elif c.stream == RadarStream.TENDER and c.claims:
        contract = _stated("contract", f"{nature} tender open", title or c.claims[0])
    else:
        contract = unknown("contract", "no contract on record")

    if role == "awarded_contractor" and winner is not None:
        contractor = _stated("contractor", name, winner)
    elif role == "direct_purchaser":
        contractor = Link(
            slot="contractor", label="none: the authority buys directly", state="stated"
        )
    elif entry.likely_bidders:
        top = entry.likely_bidders[0]
        more = len(entry.likely_bidders) - 1
        label = top.name + (f" +{more} likely" if more else " (likely)")
        contractor = Link(
            slot="contractor", label=label, state="inferred", quote=top.quote, url=top.source_url
        )
    else:
        contractor = unknown("contractor", "not yet awarded")

    ref = next((k for k in c.claims if k.ref == entry.requirement_ref), None)
    level = entry.evidence_level
    if level == "explicit_purchase" and ref is not None:
        buys = _stated("buyer", "buys what you sell", ref)
    elif level == "company_fit" and entry.company_fit:
        fit = entry.company_fit[0]
        buys = Link(
            slot="buyer",
            label="its own site names what you sell",
            state="stated",
            quote=fit.quote,
            url=fit.url,
        )
    elif level == "project_requirement":
        buys = Link(
            slot="buyer",
            label="the project needs what you sell",
            state="inferred",
            quote=ref.source_quote if ref else None,
            url=ref.url if ref else None,
        )
    else:
        buys = unknown("buyer", "who buys the material")
    return [authority, project, contract, contractor, buys]


def _trade_chain(entry: RankedEntry) -> list[Link]:
    """Importer -> product code -> import history -> buys what you sell, from the official
    import record lines (D102). What it sells itself comes only from its own site (D96)."""
    unknown = lambda slot, label: Link(slot=slot, label=label, state="unknown")  # noqa: E731
    importer = _line(entry, "Importer: ")
    product = _line(entry, "Commodity ")
    history = _line(entry, "New importer: ") or _line(entry, "Also recorded ")
    links = [
        _stated("importer", _plain_name(entry.candidate), importer)
        if importer
        else unknown("importer", "the importer"),
        _stated("product", product.source_quote.split(": imported")[0], product)
        if product
        else unknown("product", "the product code"),
        _stated(
            "history",
            "new importer this year"
            if history.source_quote.startswith("New importer")
            else "imported last year too",
            history,
        )
        if history
        else unknown("history", "import history"),
    ]
    if entry.company_fit:
        fit = entry.company_fit[0]
        links.append(
            Link(
                slot="buyer",
                label="its own site names what you sell",
                state="stated",
                quote=fit.quote,
                url=fit.url,
            )
        )
    else:
        links.append(unknown("buyer", "whether it stocks or uses what you sell"))
    return links
