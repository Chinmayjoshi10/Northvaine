"""T5.5: explained ranking, the Markdown brief, the scorecard and the written files.

Synthetic run with invented names; no network, no database, no model.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from northvaine.core.models import EvidenceKind
from northvaine.radar import brief
from northvaine.radar.models import (
    AgainstPoint,
    Candidate,
    CandidateClaim,
    CandidateEvent,
    GateDecision,
    RadarRun,
    RadarStream,
    RankedEntry,
    RejectedAs,
    RejectedEntry,
    SkepticFinding,
    UpgradedPage,
)

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def claim(ref: str, quote: str, *, doc=None, kind=EvidenceKind.FULL_TEXT, upgraded=None):
    return CandidateClaim(
        ref=ref,
        fingerprint=f"fp-{ref}",
        document_id=doc or uuid4(),
        statement=f"Statement for {ref}.",
        source_quote=quote,
        source_name="example-source",
        url=f"https://example.test/{ref}",
        available_at=NOW,
        evidence_kind=kind,
        verified_by="quote_and_support",
        upgraded_from=upgraded,
    )


def candidate(
    name: str,
    claims: list[CandidateClaim],
    *,
    stream=RadarStream.ANNOUNCEMENT,
    window_end: date | None = None,
    estimated: bool = False,
    occurred_on: date | None = None,
    country: str | None = "GB",
    roles: list[str] | None = None,
) -> Candidate:
    return Candidate(
        key=name.lower(),
        name=name,
        country=country,
        aliases=[],
        roles=["buyer"] if roles is None else roles,
        stream=stream,
        streams=[stream],
        events=[
            CandidateEvent(
                event_type="something_happened",
                description=f"{name} did something",
                occurred_on=occurred_on,
                available_at=None,
                claim_refs=[c.ref for c in claims],
                slots={},
                fingerprint=f"ev-{name}",
            )
        ],
        claims=claims,
        window_start=date(2026, 9, 1) if window_end else None,
        window_end=window_end,
        window_estimated=estimated,
        window_note="deadline as printed" if window_end else "",
    )


def gate(direct: bool | None = True, **over) -> GateDecision:
    base = dict(
        passed=True,
        rejected_as=None,
        by="llm",
        reason="a buyer",
        direct_buyer=direct,
        buyer_reason="orders the works itself",
        demand_reason="a new build needs material",
        suggested_action="approach the project office",
        cited_refs=["C1"],
    )
    base.update(over)
    return GateDecision(**base)


UNKNOWN = SkepticFinding(stance="unknown", against=[], open_questions=["Is it funded?"])
AGAINST = SkepticFinding(
    stance="against",
    against=[AgainstPoint(claim_ref="C1", why="could be a study only")],
    open_questions=[],
)


def two_docs(prefix: str) -> list[CandidateClaim]:
    return [claim("C1", f"{prefix} one quote"), claim("C2", f"{prefix} two quote")]


def ranked(items, **kw) -> list[RankedEntry]:
    return brief.rank(items, as_of=NOW, **kw)


# ----------------------------------------------------------------------------- ranking


def test_window_then_strength_and_reasons_are_plain() -> None:
    strong = candidate("Zed Strong", two_docs("z"))
    one_doc = uuid4()
    medium = candidate(
        "Alpha Medium",
        [claim("C1", "a", doc=one_doc), claim("C2", "b", doc=one_doc)],
        stream=RadarStream.TENDER,
        window_end=date(2026, 10, 7),
    )
    weak = candidate(
        "Beta Weak", [claim("C1", "w")], stream=RadarStream.TENDER, window_end=date(2026, 10, 6)
    )
    out = ranked([(weak, gate(), UNKNOWN), (medium, gate(), UNKNOWN), (strong, gate(), UNKNOWN)])
    assert [e.candidate.name for e in out] == ["Zed Strong", "Alpha Medium", "Beta Weak"]
    assert [e.strength for e in out] == ["strong", "medium", "weak"]
    assert [e.rank for e in out] == [1, 2, 3]
    # No offer given: every requirement is inferred. Tenders closing in under 5 days drop
    # below the undated announcement (D80).
    assert out[0].rank_reasons[0].startswith("Requirement: inferred")
    assert out[0].rank_reasons[2] == "Evidence: 2 verified claims from 2 pages"
    assert out[1].rank_reasons[1] == (
        "Window: tender closes in 2 days (stated deadline): likely too late to prepare a bid"
    )
    assert out[1].rank_reasons[3] == "Buyer: buys directly"


def test_one_official_record_is_medium_however_many_fields_it_has() -> None:
    doc = uuid4()
    claims = [claim(f"C{i}", f"q{i}", doc=doc, kind=EvidenceKind.STRUCTURED) for i in (1, 2, 3)]
    out = ranked([(candidate("Record Co", claims), gate(), UNKNOWN)])
    assert out[0].strength == "medium"  # strength counts independent documents (review of D80)
    assert out[0].rank_reasons[2] == "Evidence: 3 verified claims from 1 official record"


def test_open_window_before_recent_before_undated_before_closed() -> None:
    def one(name: str, **kw) -> Candidate:
        doc = uuid4()
        return candidate(name, [claim("C1", "a", doc=doc), claim("C2", "b", doc=doc)], **kw)

    closed = one("A Closed", stream=RadarStream.TENDER, window_end=date(2026, 9, 20))
    undated = one("B Undated")
    recent = one("C Recent", occurred_on=date(2026, 9, 30))
    open_late = one(
        "D Open Late", stream=RadarStream.TENDER, window_end=date(2026, 11, 1), estimated=True
    )
    open_soon = one("E Open Soon", stream=RadarStream.TENDER, window_end=date(2026, 10, 17))
    items = [(c, gate(), UNKNOWN) for c in (closed, undated, recent, open_late, open_soon)]
    out = ranked(items)
    assert [e.candidate.name for e in out] == [
        "E Open Soon",
        "D Open Late",
        "C Recent",
        "B Undated",
        "A Closed",
    ]
    reasons = {e.candidate.name: e.rank_reasons[1] for e in out}
    assert reasons["E Open Soon"] == "Window: tender closes in 12 days (stated deadline)"
    assert reasons["D Open Late"] == "Window: tender closes in 27 days (estimated deadline)"
    assert reasons["C Recent"] == "Timing: dated 2026-09-30 (5 days ago)"
    assert reasons["B Undated"] == "Timing: no date stated"
    assert "closed" in reasons["A Closed"]


def test_direct_buyer_first_then_name_breaks_ties() -> None:
    def one(name: str) -> Candidate:
        return candidate(name, two_docs(name))

    items = [
        (one("Mid"), gate(direct=None), UNKNOWN),
        (one("Zulu"), gate(direct=True), UNKNOWN),
        (one("Alpha"), gate(direct=False), UNKNOWN),
        (one("Beta"), gate(direct=True), UNKNOWN),
    ]
    out = ranked(items)
    assert [e.candidate.name for e in out] == ["Beta", "Zulu", "Alpha", "Mid"]
    assert out[2].rank_reasons[3] == "Buyer: does not buy directly (reached through others)"
    assert out[3].rank_reasons[3] == "Buyer: not stated whether it buys directly"
    assert ranked(list(reversed(items))) == out


def test_offer_terms_are_content_words_of_the_offer() -> None:
    terms = brief.offer_terms("Supplier of widgets and sprockets, selling across the EU.")
    assert terms == {"widgets", "sprockets"}


def test_a_stated_requirement_ranks_before_any_inferred_one() -> None:
    offer = "Maker of widgets for public buildings."
    stated = candidate("Zed Stated", [claim("C1", "Zed Stated orders new widget panels.")])
    inferred = candidate("Alpha Inferred", two_docs("a hall is built"))
    out = ranked([(inferred, gate(), UNKNOWN), (stated, gate(), UNKNOWN)], offer=offer)
    assert [e.candidate.name for e in out] == ["Zed Stated", "Alpha Inferred"]
    assert (out[0].requirement, out[0].requirement_ref) == ("stated", "C1")
    assert out[0].rank_reasons[0] == (
        "Requirement: stated (a verified quote names what you sell) [C1]"
    )
    assert out[1].requirement == "inferred" and out[1].requirement_ref is None


def _req(name: str, quote: str, terms: set[str], **kw) -> str:
    return brief.requirement_of(candidate(name, [claim("C1", quote)]), terms, **kw)[0]


def test_derived_terms_are_whole_words_of_what_is_sold() -> None:
    terms = brief.offer_terms("Supplier of widgets and sprockets for hotel brands")
    assert terms == {"widgets", "sprockets"}  # "hotel brands" is the market, not the product
    assert _req("Acme Ltd", "Acme Ltd orders a widget line", terms) == "stated"
    assert _req("Acme Ltd", "Acme Ltd buys new sprockets", terms) == "stated"
    # Never inside another word, never from the market, never from a generic noun.
    assert _req("Acme Ltd", "Acme Ltd re-widgetised its range", terms) == "inferred"
    assert _req("Acme Ltd", "Acme Ltd opens a hotel", terms) == "inferred"
    assert _req("Acme Ltd", "Acme Ltd buys new equipment", terms) == "inferred"


def test_explicit_data_terms_match_word_starts_in_any_language() -> None:
    terms = {"widget", "gizmo"}
    assert _req("Acme", "Acme: Widgetmontage im Rathaus", terms, prefix=True) == "stated"
    assert _req("Acme", "Acme installs gizmos", terms, prefix=True) == "stated"
    assert _req("Acme", "Acme buys a megawidget", terms, prefix=True) == "inferred"


def test_only_the_candidates_own_quotes_or_record_title_can_state_it() -> None:
    terms = {"widget"}
    other = candidate("Acme", [claim("C1", "Rival Co launched a widget range")])
    assert brief.requirement_of(other, terms, prefix=True)[0] == "inferred"
    doc = uuid4()
    record = candidate(
        "Town Hall",
        [
            claim("C1", "Buyer [eng]: Widget Town Council", doc=doc, kind=EvidenceKind.STRUCTURED),
            claim("C2", "Title [eng]: Road resurfacing", doc=doc, kind=EvidenceKind.STRUCTURED),
        ],
    )
    assert brief.requirement_of(record, terms, prefix=True)[0] == "inferred"  # party line
    titled = candidate(
        "Town Hall",
        [claim("C1", "Title [eng]: Widget panels", kind=EvidenceKind.STRUCTURED)],
    )
    assert brief.requirement_of(titled, terms, prefix=True) == ("stated", "C1")


# ----------------------------------------------------------------------------- fixtures


def make_run(
    n_passed: int = 2, *, extra_rejected: bool = True, stream: RadarStream = RadarStream.TENDER
) -> RadarRun:
    entries = []
    for i in range(n_passed):
        name = f"Invented Buyer {i}"
        doc = uuid4()
        claims = [
            claim("C1", f"{name} will build a hall.", doc=doc),
            claim(
                "C2",
                "Line one of a quote\nline two of a quote",
                doc=doc,
                upgraded="https://lead.test/x",
            ),
        ]
        entries.append(
            (
                candidate(
                    name,
                    claims,
                    stream=stream,
                    window_end=date(2026, 10, 20) + date.resolution * i,
                    estimated=True,
                    occurred_on=date(2026, 10, 1),
                ),
                gate(),
                AGAINST,
            )
        )
    ranked_entries = ranked(entries, offer="Invented offer")  # quotes name "invented"
    rejected = []
    if extra_rejected:
        person = candidate("Jane Q Person", [claim("C1", "a quote")])
        rejected = [
            RejectedEntry(
                candidate=candidate("Rival Supplies Ltd", [claim("C1", "r")]),
                gate=GateDecision(
                    passed=False,
                    rejected_as=RejectedAs.COMPETITOR,
                    by="llm",
                    reason="sells the same thing | rival",
                    direct_buyer=None,
                    buyer_reason=None,
                    demand_reason=None,
                    suggested_action=None,
                    cited_refs=["C1"],
                ),
            ),
            RejectedEntry(
                candidate=person,
                gate=GateDecision(
                    passed=False,
                    rejected_as=RejectedAs.NOT_AN_ORGANISATION,
                    by="llm",
                    reason="Jane Q Person is an individual",
                    direct_buyer=None,
                    buyer_reason=None,
                    demand_reason=None,
                    suggested_action=None,
                    cited_refs=[],
                ),
            ),
            RejectedEntry(
                candidate=candidate("", [claim("C1", "u")]),
                gate=GateDecision(
                    passed=False,
                    rejected_as=RejectedAs.UNIDENTIFIED,
                    by="code",
                    reason="no company named",
                    direct_buyer=None,
                    buyer_reason=None,
                    demand_reason=None,
                    suggested_action=None,
                    cited_refs=[],
                ),
            ),
        ]
    return RadarRun(
        client_id="demo_client",
        offer="Invented offer",
        as_of=NOW,
        queries={},
        documents_by_kind={"structured": 3, "full_text": 2},
        leads=4,
        upgraded=[
            UpgradedPage(
                lead_url="https://lead.test/x",
                final_url="https://lead.test/x",
                status=200,
                fetched_at=NOW,
                title="t",
                text="x",
                refused=None,
            ),
            UpgradedPage(
                lead_url="https://lead.test/y",
                final_url=None,
                status=403,
                fetched_at=None,
                title=None,
                text=None,
                refused="http_403",
            ),
        ],
        entries=ranked_entries,
        rejected=rejected,
        llm_calls=7,
        cost_usd=Decimal("0.0123"),
        notes=[],
    )


def entry_sections(text: str) -> list[str]:
    body = text.split("## Entries", 1)[1]
    body = re.split(r"\n## (?:Thin sources|Also passed|Rejected)", body, maxsplit=1)[0]
    return re.split(r"(?m)^### ", body)[1:]


# ----------------------------------------------------------------------------- brief


def test_header_and_streams_paragraph() -> None:
    text = brief.render_brief(make_run())
    assert "Client: demo_client" in text
    assert "Offer: Invented offer" in text
    assert "As of: 2026-10-05" in text
    assert "full_text 2, structured 3" in text
    assert "1 succeeded, 1 refused" in text
    assert "Model calls: 7; cost: $0.0123" in text
    assert "## Streams" in text
    assert "every matching notice in the query window was read" in text
    assert "some, never all" in text


def test_every_entry_has_nine_numbered_headings_stream_and_window() -> None:
    sections = entry_sections(brief.render_brief(make_run()))
    assert len(sections) == 2
    for section in sections:
        numbers = re.findall(r"(?m)^#### (\d)\. ", section)
        assert numbers == [str(i) for i in range(1, 10)]
        assert "- Stream: tender" in section
        assert "- Window: " in section
        assert section.rstrip().endswith("A person decides and makes contact.")


def test_blockquotes_are_source_quotes_and_refs_exist() -> None:
    run = make_run()
    text = brief.render_brief(run)
    for entry, section in zip(
        sorted(run.entries, key=lambda e: e.rank), entry_sections(text), strict=True
    ):
        quotes = {c.source_quote for c in entry.candidate.claims}
        blocks = re.findall(r"(?m)((?:^> .*\n?)+)", section)
        assert len(blocks) == len(quotes)
        for block in blocks:
            joined = "\n".join(line[2:] for line in block.strip("\n").split("\n"))
            assert joined in quotes
        refs = {c.ref for c in entry.candidate.claims}
        assert set(re.findall(r"\[(C\d+)\]", section)) <= refs


def test_none_gate_fields_say_not_stated() -> None:
    c = candidate("Quiet Co", two_docs("q"), roles=[], country=None)
    g = gate(direct=None, buyer_reason=None, demand_reason=None, suggested_action=None)
    entry = ranked([(c, g, UNKNOWN)])[0]
    run = make_run().model_copy(update={"entries": [entry]})
    section = entry_sections(brief.render_brief(run))[0]
    assert "Roles: not stated" in section
    assert "country not stated" in section
    for n in (4, 7, 9):
        part = re.split(rf"(?m)^#### {n}\. .*\n", section, maxsplit=1)[1]
        assert "not stated" in part.split("####")[0]
    assert "Assessment (model-written)" not in section
    assert "Suggestion (model-written)" not in section


def test_model_text_without_a_valid_citation_is_not_shown() -> None:
    c = candidate("Cited Co", two_docs("c"))
    g = gate(cited_refs=["C9"], demand_reason="made up number 5000")
    section = entry_sections(
        brief.render_brief(
            make_run().model_copy(update={"entries": [ranked([(c, g, UNKNOWN)])[0]]})
        )
    )[0]
    assert "5000" not in section
    assert "orders the works" not in section


def test_model_text_only_in_sections_4_7_8_9() -> None:
    section = entry_sections(brief.render_brief(make_run()))[0]
    parts = re.split(r"(?m)^#### (\d)\. .*\n", section)
    head, by_number = parts[0], dict(zip(parts[1::2], parts[2::2], strict=True))
    texts = [
        "a new build needs material",
        "orders the works itself",
        "approach the project",
        "could be a study only",
        "Is it funded?",
    ]
    for t in texts:
        assert t not in head
    for n in "12356":
        assert not any(t in by_number[n] for t in texts)
    assert "a new build needs material [C1]" in by_number["4"]
    assert "orders the works itself [C1]" in by_number["7"]
    assert "could be a study only [C1]" in by_number["8"]
    assert "approach the project office [C1]" in by_number["9"]


def test_uncertainty_always_has_content_and_code_flags() -> None:
    c = candidate(
        "Flag Co",
        [claim("C1", "Flag Co orders widgets", upgraded="https://lead.test/z")],
        stream=RadarStream.TENDER,
        window_end=date(2026, 10, 20),
        estimated=True,
    )
    entry = ranked(
        [(c, gate(), SkepticFinding(stance="unknown", against=[], open_questions=[]))],
        offer="widgets",
    )[0]
    section = entry_sections(
        brief.render_brief(make_run().model_copy(update={"entries": [entry]}))
    )[0]
    part = re.split(r"(?m)^#### 8\. .*\n", section)[1].split("#### 9")[0]
    assert "Unknown: no evidence against" in part
    assert "deadline is estimated" in part
    assert "single document" in part
    assert "when we fetched it" in part
    assert "page fetched from a search lead" in section


def test_sources_label_official_record_and_full_page() -> None:
    doc = uuid4()
    claims = [
        claim("C1", "a", doc=doc, kind=EvidenceKind.STRUCTURED),
        claim("C2", "b", kind=EvidenceKind.FULL_TEXT),
    ]
    entry = ranked([(candidate("Src Co", claims), gate(), UNKNOWN)])[0]
    section = entry_sections(
        brief.render_brief(make_run().model_copy(update={"entries": [entry]}))
    )[0]
    assert (
        "<https://example.test/C1> (example-source); available 2026-10-05; official record"
        in section
    )
    assert "<https://example.test/C2> (example-source); available 2026-10-05; full page" in section


def test_thin_sources_paragraph_and_rejected_table() -> None:
    run = make_run(n_passed=2, stream=RadarStream.AWARD)
    text = brief.render_brief(run)
    assert "## Thin sources" in text
    assert "Only 2 accounts are strong enough to approach this time" in text
    assert "Nothing was added to fill the space" in text
    table = text.split("## Rejected", 1)[1]
    assert "| Rival Supplies Ltd | competitor | llm | sells the same thing \\| rival |" in table
    assert "| (a person, name withheld) | not_an_organisation | llm | (withheld) |" in table
    assert "| (no company named) | unidentified | code | no company named |" in table
    assert "Jane" not in text
    assert text.count("\n| ") >= 4  # header, divider, three rows


def test_no_thin_paragraph_when_full_and_extra_entries_listed_one_line() -> None:
    run = make_run(n_passed=12, stream=RadarStream.AWARD)
    text = brief.render_brief(run)
    assert "## Thin sources" not in text
    assert len(entry_sections(text)) == 5  # radar_brief_main_entries (D80)
    also = text.split("## Also found, weaker", 1)[1].split("## Rejected")[0]
    assert len([ln for ln in also.splitlines() if re.match(r"\| \d+ \|", ln)]) == 7
    assert "| 12 | Invented Buyer" in also
    assert text.count("A person decides and makes contact.") == 5


def test_empty_run_is_honest() -> None:
    run = make_run(n_passed=0, extra_rejected=False)
    text = brief.render_brief(run)
    assert "No entry passed." in text
    assert "## Thin sources" in text
    assert "Nothing was rejected." in text


def test_rendering_is_deterministic() -> None:
    run = make_run()
    assert brief.render_brief(run) == brief.render_brief(run)
    assert brief.render_scorecard(run) == brief.render_scorecard(run)


# ----------------------------------------------------------------------------- scorecard


def test_scorecard_rows_wordings_and_chips() -> None:
    run = make_run()
    text = brief.render_scorecard(run)
    assert "previously unknown" in text
    assert "would a salesperson in that industry act on this?" in text
    assert "your own business: previously unknown; other clients: would a salesperson" in text
    for chip in (
        "wrong company",
        "not a buyer",
        "wrong fact",
        "not actionable",
        "stale/closed window",
        "competitor/publisher let through",
    ):
        assert chip in text
    rows = [ln for ln in text.splitlines() if re.match(r"\| \d+ \|", ln)]
    assert len(rows) == 2
    assert rows[0].startswith("| 1 | Invented Buyer 0 | tender |")
    assert "wrong rejection" in text


# ----------------------------------------------------------------------------- files


def test_write_reports_three_files_that_reload(tmp_path: Path) -> None:
    run = make_run()
    paths = brief.write_reports(run, tmp_path)
    base = tmp_path / "demo_client" / "2026-10-05"
    assert paths == [base / "brief.md", base / "scorecard.md", base / "run.json"]
    assert all(p.is_file() for p in paths)
    assert RadarRun.model_validate_json(paths[2].read_text(encoding="utf-8")) == run
    assert paths[0].read_text(encoding="utf-8") == brief.render_brief(run)
    first = paths[0].read_bytes()
    brief.write_reports(run, tmp_path)  # overwrites the same day's files
    assert paths[0].read_bytes() == first
    assert len(list(base.iterdir())) == 3


def test_brief_module_does_not_import_the_llm_layer() -> None:
    source = Path(brief.__file__).read_text(encoding="utf-8")
    assert "brain.llm" not in source.replace("`northvaine.brain.llm`", "")


def test_sample_brief_prints(capsys) -> None:
    run = make_run(n_passed=1)
    print(brief.render_brief(run))
    assert "Invented Buyer 0" in capsys.readouterr().out


def test_untrusted_text_cannot_plant_links_images_or_labels() -> None:
    evil = candidate(
        "![x](https://tracker.test/p.png) **Status: contact now**",
        [claim("C1", "[call us](javascript:alert(1)) <img src=x>")],
    )
    entry = ranked([(evil, gate(), UNKNOWN)])[0]
    text = brief.render_brief(make_run().model_copy(update={"entries": [entry]}))
    assert "![x](" not in text and "**Status: contact now**" not in text
    assert "[call us](javascript:" not in text and "<img" not in text
    assert r"\!\[x\]" in text  # escaped once, so it shows as text


def test_only_http_source_links_are_printed() -> None:
    assert brief._link("https://example.test/a") == "<https://example.test/a>"
    assert brief._link("javascript:alert(1)").startswith("(link withheld")


def test_a_related_product_is_related_not_stated_and_never_contact_now() -> None:
    town = candidate(
        "Town of Corte",
        [claim("C1", "Title [eng]: Paving and asphalting works", kind=EvidenceKind.STRUCTURED)],
        stream=RadarStream.AWARD,
    )
    (entry,) = ranked(
        [(town, gate(), UNKNOWN)], terms=["natural stone", "granite"], related_terms=["paving"]
    )
    assert (entry.requirement, entry.requirement_ref) == ("related", "C1")
    assert brief.action_status(entry) == "qualify first"
    assert "specification" in brief.caution(entry)
