"""The web of one saved run (`radar/graph.run_graph`): pure, no database, every line cited."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from northvaine.radar import brief
from northvaine.radar.graph import run_graph
from northvaine.radar.models import LikelyBidder, RadarRun
from tests.radar.test_brief import NOW, UNKNOWN, candidate, claim, gate


def run_of(*candidates, bidders: list[LikelyBidder] | None = None) -> RadarRun:
    entries = brief.rank([(c, gate(), UNKNOWN) for c in candidates], as_of=NOW, offer="Offer")
    if bidders:
        entries[0] = entries[0].model_copy(update={"likely_bidders": bidders})
    return RadarRun(
        client_id="acme",
        offer="Offer",
        as_of=NOW,
        queries={},
        documents_by_kind={},
        leads=0,
        upgraded=[],
        entries=entries,
        rejected=[],
        llm_calls=0,
        cost_usd=0,
        notes=[],
    )


def test_two_companies_on_one_document_meet_at_one_event() -> None:
    doc = uuid4()
    authority = candidate("Invented Council", [claim("C1", "The council tenders.", doc=doc)])
    winner = candidate(
        "Invented Builder", [claim("C1", "Awarded to the builder.", doc=doc)], roles=["winner"]
    )
    g = run_graph(run_of(authority, winner))
    events = [n for n in g.nodes if n.kind == "event"]
    assert len(events) == 1 and events[0].id == str(doc)
    assert {(e.src, e.relation) for e in g.edges} == {
        ("company:invented council", "buyer"),
        ("company:invented builder", "winner"),
    }
    assert all(e.derivation == "stated" and e.confidence is None for e in g.edges)


def test_quotes_are_kept_once_and_each_line_cites_its_own() -> None:
    doc = uuid4()
    c = candidate(
        "Invented Buyer",
        [claim("C1", "First quote.", doc=doc), claim("C2", "Second quote.", doc=doc)],
    )
    (edge,) = run_graph(run_of(c)).edges
    assert [q.quote for q in edge.evidence] == ["First quote.", "Second quote."]
    assert edge.valid_from is None


def test_likely_bidders_are_inferred_with_their_award_quote_and_persons_are_withheld() -> None:
    c = candidate("Invented Buyer", [claim("C1", "A tender.")])
    bidders = [
        LikelyBidder(
            name="Invented Contractor",
            country="GB",
            wins=3,
            last_won=date(2026, 9, 1),
            source_url="https://example.test/award",
            quote="Winner [GB]: Invented Contractor",
        ),
        LikelyBidder(
            name="[natural person withheld]",
            country="GB",
            wins=1,
            last_won=None,
            source_url="https://example.test/award2",
            quote="Winner [GB]: [natural person withheld]",
        ),
    ]
    g = run_graph(run_of(c, bidders=bidders))
    assert not any(n.label.startswith("[") for n in g.nodes)
    (line,) = [e for e in g.edges if e.relation == "likely_bidder"]
    assert line.derivation == "inferred" and line.confidence == 0.75
    assert line.evidence[0].url == "https://example.test/award"
    assert line.valid_from == NOW.date()
