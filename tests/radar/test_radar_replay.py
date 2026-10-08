"""T5.7: the radar replayed on its real recordings, for all three sample clients.

`tests/fixtures/radar/<client>/` holds a live run (HTTP exchanges, fetched pages, model exchanges).
`scripts/radar.py` replays it with no `.env` and no network; this module replays it the same way
(through `radar.run_replay`, with spies on the pipeline stages) and asserts, on the real data, what
the founder relies on before reading a brief:

* the replay uses every recorded exchange, and a one-character document change breaks it;
* zero unsupported facts: every claim is verified, its quote is in its document, every brief
  blockquote is one of those quotes, every citation resolves;
* model-written sentences cite refs that exist and introduce no number (D63);
* the gate comes first, the skeptic only after a passed gate, every candidate is accounted for;
* every entry states its stream and window, enumerable wording only on tender/award entries;
* no email, phone number, key or natural-person name in a recording, run record or brief;
* one code path serves all three clients, and replay is byte-identical across runs.

Nothing here edits a recording. A stale recording raises a replay mismatch: report it, only the
orchestrator re-records (D53). Expected counts live in `tests/golden/radar_expectations.json`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
import pytest

from northvaine.brain.errors import LlmReplayMismatch
from northvaine.brain.replay import ReplayClient
from northvaine.core.models import (
    ClaimCheck,
    EvidenceDocument,
    EvidenceKind,
    LedgerResult,
    QuoteMode,
)
from northvaine.core.settings import Settings
from northvaine.radar.models import (
    Candidate,
    GateDecision,
    RadarRun,
    RadarStream,
    RejectedAs,
    RejectedEntry,
    load_client_spec,
)
from northvaine.radar.quote_check import find_quote
from northvaine.sensors.replay import ReplayMismatch, replay_transport

ROOT = Path(__file__).resolve().parents[2]
RECORDINGS = ROOT / "tests" / "fixtures" / "radar"
CLIENTS_DIR = ROOT / "tests" / "fixtures" / "clients"
CLIENTS = ["stone_supplier", "coldchain_maker", "packaging_supplier"]
SETTINGS = Settings(_env_file=None)

# --- the script under test, loaded by path (`scripts/` is not a package) ------------------------


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "nv_radar_script_t57", ROOT / "scripts" / "radar.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


radar = _load_script()


# --- one cached replay per client ---------------------------------------------------------------


class _CountingTransport(httpx.AsyncBaseTransport):
    """Wraps the replay transport and counts the requests it served."""

    def __init__(self, inner: httpx.AsyncBaseTransport, counter: list[int]) -> None:
        self.inner, self.counter = inner, counter

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        self.counter.append(1)
        return response


@dataclass
class Replayed:
    client: str
    recording: Any
    run: RadarRun
    documents: dict[Any, EvidenceDocument]  # by document id, as the ledger read them
    results: list[tuple[EvidenceDocument, LedgerResult]]
    built: list[Candidate]  # every candidate the code built, before the gate
    unidentified: list[RejectedEntry]  # rejected by code in `build_candidates`
    calls: list[tuple[str, str]]  # ("gate" | "skeptic", candidate key), in call order
    gate_passed: dict[str, bool] = field(default_factory=dict)
    http_served: int = 0
    llm_served: list[str] = field(default_factory=list)


def spec_of(client: str) -> Any:
    return load_client_spec(client, CLIENTS_DIR)


def load(client: str) -> Any:
    return radar.load_replay(RECORDINGS / client, client)


def replay_recording(client: str, recording: Any) -> Replayed:
    """`radar.run_replay` on `recording`, with spies on the pipeline stages. No network."""
    from northvaine.radar import run as run_module

    out = Replayed(client, recording, None, {}, [], [], [], [])  # type: ignore[arg-type]
    http_counter: list[int] = []
    clients: list[ReplayClient] = []

    def counting_transport(exchanges: Any, **kwargs: Any) -> httpx.AsyncBaseTransport:
        return _CountingTransport(replay_transport(exchanges, **kwargs), http_counter)

    class SpyClient(ReplayClient):
        def __init__(self, rec: Any) -> None:
            super().__init__(rec)
            clients.append(self)

    real_build_evidence = run_module.build_evidence
    real_build_candidates = run_module.build_candidates
    real_gate = run_module.gate_candidate
    real_skeptic = run_module.skeptic

    async def build_evidence(doc: EvidenceDocument, *args: Any, **kwargs: Any) -> LedgerResult:
        result = await real_build_evidence(doc, *args, **kwargs)
        out.documents[doc.id] = doc
        out.results.append((doc, result))
        return result

    def build_candidates(results: Any, **kwargs: Any) -> Any:
        candidates, rejected = real_build_candidates(results, **kwargs)
        out.built, out.unidentified = list(candidates), list(rejected)
        return candidates, rejected

    async def gate(candidate: Candidate, *args: Any, **kwargs: Any) -> GateDecision:
        out.calls.append(("gate", candidate.key))
        decision = await real_gate(candidate, *args, **kwargs)
        out.gate_passed[candidate.key] = decision.passed
        return decision

    async def skeptic(candidate: Candidate, *args: Any, **kwargs: Any) -> Any:
        out.calls.append(("skeptic", candidate.key))
        return await real_skeptic(candidate, *args, **kwargs)

    with (
        mock.patch.object(run_module, "build_evidence", build_evidence),
        mock.patch.object(run_module, "build_candidates", build_candidates),
        mock.patch.object(run_module, "gate_candidate", gate),
        mock.patch.object(run_module, "skeptic", skeptic),
        mock.patch.object(radar, "replay_transport", counting_transport),
        mock.patch.object(radar, "ReplayClient", SpyClient),
    ):
        out.run = asyncio.run(radar.run_replay(spec_of(client), recording))
    out.http_served = len(http_counter)
    out.llm_served = list(clients[0].served)
    return out


@cache
def replay(client: str) -> Replayed:
    return replay_recording(client, load(client))


def brief_of(client: str) -> str:
    from northvaine.radar.brief import render_brief

    return render_brief(replay(client).run)


# --- parsing the rendered brief -----------------------------------------------------------------

REF = re.compile(r"\[(C\d+)\]")
NUMBER = re.compile(r"\d(?:[\d.,]*\d)?")


def entry_blocks(brief: str) -> dict[int, str]:
    """The text of each `### n. Name` entry block, by rank."""
    start = brief.index("\n## Entries\n")
    end_match = re.search(r"\n## (?!Entries)", brief[start + 1 :])
    body = brief[start : start + 1 + end_match.start()] if end_match else brief[start:]
    parts = re.split(r"(?m)^### (\d+)\. ", body)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def sections(block: str) -> dict[int, list[str]]:
    """Non-empty lines of each `#### n. Question` section of an entry block."""
    found: dict[int, list[str]] = {}
    current = 0
    for line in block.split("\n"):
        match = re.match(r"#### (\d)\. ", line)
        if match:
            current = int(match.group(1))
            found[current] = []
        elif current and line.strip():
            found[current].append(line)
    return found


def blockquotes(text: str) -> list[str]:
    """Each run of `> ` lines in `text`, rejoined to the quote it renders."""
    quotes: list[str] = []
    current: list[str] | None = None
    for line in text.split("\n"):
        if line.startswith(">"):
            current = current if current is not None else []
            current.append(line[2:] if line.startswith("> ") else "")
        elif current is not None:
            quotes.append("\n".join(current))
            current = None
    if current is not None:
        quotes.append("\n".join(current))
    # The brief escapes Markdown in untrusted text (D82); compare the text a reader sees.
    return [re.sub(r"\\(.)", r"\1", q) for q in quotes]


def number_tokens(text: str) -> set[str]:
    """Numbers with thousands marks and decimal separators stripped ('1,500' == '1500')."""
    return {re.sub(r"[.,]", "", t) for t in NUMBER.findall(text)}


def shown_entries(client: str) -> list[Any]:
    """The entries the brief writes up in full (D80: stated or strong, capped)."""
    from northvaine.radar.brief import _briefed

    return _briefed(replay(client).run)[0]


# --- every recorded exchange is used, and a changed document is caught --------------------------


@pytest.mark.parametrize("client", CLIENTS)
def test_the_replay_uses_every_recorded_exchange(client: str) -> None:
    r = replay(client)
    assert r.http_served == len(r.recording.exchanges), "recorded HTTP exchanges left unused"
    recorded = {e.key for e in r.recording.llm.exchanges}
    assert set(r.llm_served) == recorded, "recorded model exchanges left unused"
    assert len(r.llm_served) >= len(recorded)
    assert r.run.llm_calls > 0 and r.run.cost_usd > 0


def _first_document_string(
    recording: Any, documents: list[EvidenceDocument]
) -> tuple[int, list[Any], str]:
    """(exchange index, path inside body_json, string) of a body string that sits inside the part
    of a document the model reads (the first `extract_max_doc_chars` characters)."""
    limit = SETTINGS.extract_max_doc_chars

    def walk(node: Any, path: list[Any]) -> Iterator[tuple[list[Any], str]]:
        if isinstance(node, str):
            yield path, node
        elif isinstance(node, list):
            for i, item in enumerate(node):
                yield from walk(item, [*path, i])
        elif isinstance(node, dict):
            for key, item in node.items():
                yield from walk(item, [*path, key])

    for index, exchange in enumerate(recording.exchanges):
        for path, text in walk(exchange.body_json, []):
            if len(text) >= 30 and any(
                d.text.find(text) >= 0 and d.text.find(text) + 30 < limit for d in documents
            ):
                return index, path, text
    raise AssertionError("no recorded string appears in a document")


@pytest.mark.parametrize("client", CLIENTS)
def test_a_one_character_document_change_raises_a_replay_mismatch(client: str) -> None:
    r = replay(client)
    read_by_model = [d for d, result in r.results if result.llm_calls > 0]
    assert read_by_model, "the model read no document"
    index, path, text = _first_document_string(r.recording, read_by_model)
    changed = text[:6] + ("Q" if text[6] != "Q" else "Z") + text[7:]
    assert changed != text and len(changed) == len(text)
    exchanges = [e.model_copy(deep=True) for e in r.recording.exchanges]
    node: Any = exchanges[index].body_json
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = changed
    tampered = dataclasses.replace(r.recording, exchanges=exchanges)
    with pytest.raises((LlmReplayMismatch, ReplayMismatch)):
        replay_recording(client, tampered)


# --- zero unsupported facts ---------------------------------------------------------------------


def _all_candidates(r: Replayed) -> list[Candidate]:
    return [e.candidate for e in r.run.entries] + [x.candidate for x in r.run.rejected]


def _verified_checks(r: Replayed) -> dict[tuple[Any, str], ClaimCheck]:
    return {
        (doc.id, check.fingerprint): check
        for doc, result in r.results
        for check in result.checks
        if check.verified
    }


@pytest.mark.parametrize("client", CLIENTS)
def test_every_claim_is_verified_and_its_quote_is_in_its_document(client: str) -> None:
    r = replay(client)
    verified = _verified_checks(r)
    candidates = _all_candidates(r)
    assert candidates
    problems: list[str] = []
    count = 0
    for candidate in candidates:
        for claim in candidate.claims:
            count += 1
            check = verified.get((claim.document_id, claim.fingerprint))
            doc = r.documents.get(claim.document_id)
            if check is None or doc is None:
                problems.append(
                    f"{claim.ref} of {candidate.name!r}: no verified claim in a document"
                )
                continue
            if (
                claim.statement != check.draft.statement
                or claim.source_quote != check.draft.source_quote
            ):
                problems.append(
                    f"{claim.ref} of {candidate.name!r}: differs from the verified claim"
                )
            mode = (
                QuoteMode.STRUCTURED
                if claim.evidence_kind == EvidenceKind.STRUCTURED
                else QuoteMode.EXTRACTED
            )
            if not find_quote(doc.text, claim.source_quote, mode=mode, settings=SETTINGS).found:
                problems.append(
                    f"{claim.ref} of {candidate.name!r}: quote not found in its document"
                )
            if not claim.verified_by:
                problems.append(f"{claim.ref} of {candidate.name!r}: nobody verified it")
            if claim.url != doc.url or claim.available_at != doc.available_at:
                problems.append(
                    f"{claim.ref} of {candidate.name!r}: source differs from its document"
                )
    assert count > 0
    assert not problems, "\n".join(problems[:10])


@pytest.mark.parametrize("client", CLIENTS)
def test_claim_refs_are_unique_and_every_event_cites_existing_refs(client: str) -> None:
    for candidate in _all_candidates(replay(client)):
        refs = [c.ref for c in candidate.claims]
        assert len(refs) == len(set(refs)), candidate.name
        for event in candidate.events:
            assert set(event.claim_refs) <= set(refs), (candidate.name, event.claim_refs)


@pytest.mark.parametrize("client", CLIENTS)
def test_every_brief_blockquote_is_a_verified_quote_and_every_citation_resolves(
    client: str,
) -> None:
    r = replay(client)
    brief = brief_of(client)
    shown = shown_entries(client)
    blocks = entry_blocks(brief)
    assert sorted(blocks) == [e.rank for e in shown]
    all_quotes = {c.source_quote for cand in _all_candidates(r) for c in cand.claims}
    assert set(blockquotes(brief)) <= all_quotes, (
        "a blockquote in the brief is not a verified quote"
    )
    for entry in shown:
        block = blocks[entry.rank]
        own = {c.ref: c.source_quote for c in entry.candidate.claims}
        assert set(blockquotes(block)) == set(own.values()), entry.candidate.name
        cited = set(REF.findall(block))
        assert cited <= set(own), (entry.candidate.name, cited - set(own))
        # every claim is shown with its ref as a bold label
        assert {m for m in re.findall(r"\*\*\[(C\d+)\]\*\*", block)} == set(own)


@pytest.mark.parametrize("client", CLIENTS)
def test_the_rejected_table_shows_no_claims_or_quotes(client: str) -> None:
    brief = brief_of(client)
    table = brief[brief.index("\n## Rejected\n") :]
    assert "> " not in table.replace("| ", "")  # no blockquote, only table rows
    assert not REF.search(table)


# --- model-written sentences cite existing refs and add no number (D63) -------------------------

MODEL_LINE = re.compile(r"\(model-written\)")


@pytest.mark.parametrize("client", CLIENTS)
def test_model_written_sentences_cite_existing_refs_and_numbers_are_grounded(client: str) -> None:
    blocks = entry_blocks(brief_of(client))
    problems: list[str] = []
    checked = 0
    for entry in shown_entries(client):
        quotes = {c.ref: c.source_quote for c in entry.candidate.claims}
        secs = sections(blocks[entry.rank])
        for n in (4, 7, 8, 9):
            for line in secs.get(n, []):
                refs = REF.findall(line)
                text = REF.sub("", line)
                if n in (4, 7, 9) and MODEL_LINE.search(line):
                    checked += 1
                    stated = text.split(": ", 1)[1].strip()
                    if stated == "not stated":
                        continue
                    if not refs or not set(refs) <= set(quotes):
                        problems.append(f"#{entry.rank} section {n}: no existing ref: {line[:80]}")
                if n == 8 and line.startswith("- Against (model-written)"):
                    checked += 1
                    if len(refs) != 1 or refs[0] not in quotes:
                        problems.append(f"#{entry.rank} section 8: no existing ref: {line[:80]}")
                # numbers: in the quotes cited on the line; an uncited line (an open question)
                # is held to all of the entry's quotes. Strip the "Header (model-written):" label.
                if not MODEL_LINE.search(text):
                    continue  # code-written lines (stage notes, bidder lists) carry no claim
                sentence = text.split("):", 1)[1]
                if not NUMBER.search(sentence):
                    continue
                if refs:
                    pool = " ".join(quotes[ref] for ref in refs if ref in quotes)
                elif n == 8:
                    pool = " ".join(quotes.values())
                else:
                    problems.append(
                        f"#{entry.rank} section {n}: a number with no citation: {line[:80]}"
                    )
                    continue
                missing = number_tokens(sentence) - number_tokens(pool)
                if missing:
                    problems.append(
                        f"#{entry.rank} section {n}: ungrounded {sorted(missing)}: {line[:80]}"
                    )
    assert checked > 0, "no model-written sentence was checked"
    assert not problems, "\n".join(problems[:10])


@pytest.mark.skip(
    reason="D78: open questions are questions, not facts; they need no citation, only "
    "number grounding against the entry's quotes (tested elsewhere)"
)
def test_open_questions_cite_claim_refs() -> None:
    uncited = 0
    seen = 0
    for client in CLIENTS:
        for entry in shown_entries(client):
            for question in entry.skeptic.open_questions:
                seen += 1
                lines = [
                    line
                    for line in entry_blocks(brief_of(client))[entry.rank].split("\n")
                    if line.startswith("- Open question") and question.split()[0] in line
                ]
                uncited += sum(1 for line in lines if not REF.search(line))
    assert seen > 0
    assert uncited == 0


# --- order, rejections, accounting --------------------------------------------------------------

NOT_GATED = re.compile(r"(\d+) candidate\(s\) not gated")
SKIPPED = re.compile(r"candidate skipped \(")
NOT_BRIEFED = re.compile(r"passed the gate but not briefed .*?: (.+)$")


def _unaccounted(r: Replayed) -> int:
    """Candidates the run itself says it did not decide: not gated (cap or budget), skipped after
    a model failure (D73), or passed but not investigated."""
    total = 0
    for note in r.run.notes:
        if (m := NOT_GATED.search(note)) is not None:
            total += int(m.group(1))
        elif SKIPPED.search(note):
            total += 1
        elif (m := NOT_BRIEFED.search(note)) is not None:
            total += len(m.group(1).split(", "))
    return total


@pytest.mark.parametrize("client", CLIENTS)
def test_every_candidate_is_an_entry_or_a_kept_rejection_with_a_reason(client: str) -> None:
    r = replay(client)
    run = r.run
    assert r.built, "no candidate was built"
    assert len(run.entries) + len(run.rejected) + _unaccounted(r) == len(r.built) + len(
        r.unidentified
    )
    entry_keys = [e.candidate.key for e in run.entries]
    reject_keys = [x.candidate.key for x in run.rejected]
    assert len(entry_keys) == len(set(entry_keys)) and len(reject_keys) == len(set(reject_keys))
    assert not set(entry_keys) & set(reject_keys)
    built_keys = {c.key for c in r.built} | {x.candidate.key for x in r.unidentified}
    assert set(entry_keys) | set(reject_keys) <= built_keys
    for rej in run.rejected:
        assert rej.gate.passed is False
        assert isinstance(rej.gate.rejected_as, RejectedAs)
        assert rej.gate.by in ("code", "llm") and rej.gate.reason.strip()
        if rej.gate.rejected_as == RejectedAs.UNIDENTIFIED:
            assert rej.gate.by == "code"
    for entry in run.entries:
        assert entry.gate.passed and entry.gate.rejected_as is None
    # the ranks run 1..n with no gap
    assert sorted(e.rank for e in run.entries) == list(range(1, len(run.entries) + 1))


@pytest.mark.parametrize("client", CLIENTS)
def test_the_skeptic_runs_only_after_a_passed_gate_and_never_on_a_rejection(client: str) -> None:
    r = replay(client)
    entry_keys = {e.candidate.key for e in r.run.entries}
    reject_keys = {x.candidate.key for x in r.run.rejected}
    skeptic_keys = [key for kind, key in r.calls if kind == "skeptic"]
    gated = [key for kind, key in r.calls if kind == "gate"]
    assert not set(skeptic_keys) & reject_keys, "a rejected candidate was investigated"
    assert set(skeptic_keys) <= entry_keys | set(_noted_unbriefed(r))
    assert entry_keys <= set(skeptic_keys), "an entry has no skeptic call"
    for position, (kind, key) in enumerate(r.calls):
        if kind == "skeptic":
            assert ("gate", key) in r.calls[:position], f"skeptic before gate for {key}"
            assert r.gate_passed[key] is True
    assert len(gated) == len(set(gated)), "a candidate was gated twice"
    # a code-rejected (unidentified) candidate never reaches the gate or the skeptic
    for rej in r.unidentified:
        assert ("gate", rej.candidate.key) not in r.calls
    # every entry carries a skeptic finding: evidence against, or "unknown" with open questions
    for entry in r.run.entries:
        finding = entry.skeptic
        assert finding.stance in ("against", "unknown")
        if finding.stance == "unknown":
            assert not finding.against
        for point in finding.against:
            assert point.claim_ref in {c.ref for c in entry.candidate.claims}


def _noted_unbriefed(r: Replayed) -> list[str]:
    return [
        c.key for c in r.built if c.name in " ".join(n for n in r.run.notes if "not briefed" in n)
    ]


@pytest.mark.parametrize("client", CLIENTS)
def test_the_gate_decides_before_any_investigation_of_the_same_candidate(client: str) -> None:
    r = replay(client)
    for e in r.run.entries:
        assert e.gate.by == "llm" and e.gate.cited_refs
        refs = {c.ref for c in e.candidate.claims}
        assert set(e.gate.cited_refs) <= refs


# --- stream and window --------------------------------------------------------------------------

ENUMERABLE_WORDING = re.compile(
    r"every matching notice|listed in official registers", re.IGNORECASE
)


@pytest.mark.parametrize("client", CLIENTS)
def test_every_entry_states_stream_and_window_and_enumerable_wording_is_for_tenders(
    client: str,
) -> None:
    blocks = entry_blocks(brief_of(client))
    for entry in shown_entries(client):
        block = blocks[entry.rank]
        c = entry.candidate
        assert re.search(r"(?m)^- Stream: \S", block), entry.rank
        assert re.search(r"(?m)^- Window: \S", block), entry.rank
        assert f"- Stream: {c.stream.value}" in block  # the "When" section names the stream
        enumerable = c.stream in (RadarStream.TENDER, RadarStream.AWARD)
        assert bool(ENUMERABLE_WORDING.search(block)) == enumerable, (entry.rank, c.stream)
        if c.stream == RadarStream.TENDER:
            assert c.window_start is not None and c.window_end is not None, c.name
            assert c.window_start.isoformat() in block and c.window_end.isoformat() in block
        else:
            assert "tender closes" not in " ".join(entry.rank_reasons)


@pytest.mark.parametrize("client", CLIENTS)
def test_enumerable_streams_come_from_an_enumerable_source(client: str) -> None:
    """A tender or award entry rests on a register notice, not on a press page."""
    sources = {s.casefold() for s in SETTINGS.radar_enumerable_sources}
    for entry in replay(client).run.entries:
        c = entry.candidate
        if c.stream in (RadarStream.TENDER, RadarStream.AWARD):
            assert any(k.source_name.casefold() in sources for k in c.claims), c.name


# --- personal data and secrets ------------------------------------------------------------------

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
PHONE = (
    re.compile(r"(?<![\w+])\+\d{1,3}[\s.\-()]*\d[\d\s.\-()]{6,}\d"),
    re.compile(r"(?<![\w.])\(\d{2,5}\)[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}(?!\d)"),
    re.compile(r"(?<![\w.\-])0\d{1,4}[\s.\-/]\d{3,4}[\s.\-/]?\d{2,4}(?![\w\-])"),
)
SECRET = re.compile(r"(?<![A-Za-z0-9])(?:nvapi-|sk-|eyJ|tvly-)[-_A-Za-z0-9.]{12,}")


def _strings(node: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _strings(item, f"{path}[{i}]")
    elif isinstance(node, dict):
        for key, item in node.items():
            yield from _strings(str(key), f"{path}.<key>")
            yield from _strings(item, f"{path}.{key}")


def _personal(text: str) -> list[str]:
    hits = [m.group(0) for m in EMAIL.finditer(text)]
    for pattern in PHONE:
        hits += [m.group(0) for m in pattern.finditer(text)]
    hits += [m.group(0)[:8] + "..." for m in SECRET.finditer(text)]
    return hits


@pytest.mark.parametrize("client", CLIENTS)
def test_no_email_phone_or_key_in_a_recording(client: str) -> None:
    found: list[str] = []
    for name in radar.FILES:
        data = json.loads((RECORDINGS / client / name).read_text(encoding="utf-8"))
        for path, text in _strings(data):
            found += [f"{name} {path}: {hit}" for hit in _personal(text)]
    assert not found, "\n".join(found[:10])


@pytest.mark.parametrize("client", CLIENTS)
def test_no_email_phone_or_key_in_the_run_record_or_the_reports(
    client: str, tmp_path: Path
) -> None:
    from northvaine.radar.brief import render_scorecard, write_reports

    r = replay(client)
    paths = write_reports(r.run, tmp_path)
    texts = {p.name: p.read_text(encoding="utf-8") for p in paths}
    texts["scorecard.md"] += render_scorecard(r.run)
    for name, text in texts.items():
        assert not _personal(text), (name, _personal(text)[:5])


def _marker_patterns() -> list[re.Pattern[str]]:
    return [
        re.compile(r"(?<!\w)" + re.escape(m) + r"(?!\w)", re.IGNORECASE)
        for m in SETTINGS.ted_natural_person_markers
    ]


@pytest.mark.parametrize("client", CLIENTS)
def test_no_natural_person_legal_form_name_in_an_entry_or_a_rejection_row(client: str) -> None:
    r = replay(client)
    patterns = _marker_patterns()
    texts: list[tuple[str, str]] = []
    for entry in r.run.entries:
        c = entry.candidate
        texts += [(f"entry {c.name}", " ".join([c.name, *c.aliases]))]
        texts += [(f"entry {c.name} {k.ref}", f"{k.statement} {k.source_quote}") for k in c.claims]
        texts += [(f"entry {c.name} event", e.description) for e in c.events]
    for rej in r.run.rejected:
        c = rej.candidate
        texts += [(f"rejection {c.name}", " ".join([c.name, *c.aliases, rej.gate.reason]))]
    texts += [("brief", brief_of(client)), ("run.json", r.run.model_dump_json())]
    hits = [f"{where}: {p.pattern}" for where, text in texts for p in patterns if p.search(text)]
    assert not hits, "\n".join(hits[:10])


@pytest.mark.parametrize("client", CLIENTS)
def test_a_not_an_organisation_name_never_appears_in_the_brief(client: str) -> None:
    r = replay(client)
    brief = brief_of(client)
    for rej in r.run.rejected:
        if rej.gate.rejected_as == RejectedAs.NOT_AN_ORGANISATION:
            assert rej.candidate.name not in brief, rej.candidate.name
            assert "(a person, name withheld)" in brief


# --- point in time ------------------------------------------------------------------------------


@pytest.mark.parametrize("client", CLIENTS)
def test_register_documents_are_not_available_after_the_run_date(client: str) -> None:
    r = replay(client)
    for doc in r.documents.values():
        if doc.source_name == "tavily":
            continue  # search results: covered by test_no_document_is_available_after_the_run_date
        assert doc.available_at is None or doc.available_at <= r.run.as_of, doc.url


@pytest.mark.parametrize("client", CLIENTS)
def test_upgraded_pages_are_available_when_fetched(client: str) -> None:
    r = replay(client)
    for doc in r.documents.values():
        origin = doc.meta.get("upgraded_from")
        if origin is not None:
            page = next(
                (p for p in r.run.upgraded if p.lead_url == origin and p.refused is None), None
            )
            assert page is not None, doc.url
            # capped at the run's own moment (D78)
            assert doc.available_at == min(page.fetched_at, r.run.as_of), doc.url
    for page in r.run.upgraded:
        if page.refused is None:
            assert page.fetched_at is not None and page.fetched_at <= r.run.as_of


@pytest.mark.parametrize("client", CLIENTS)
def test_no_document_is_available_after_the_run_date(client: str) -> None:
    r = replay(client)
    late = [d.url for d in r.documents.values() if d.available_at and d.available_at > r.run.as_of]
    assert not late, late[:3]


# --- generality and determinism -----------------------------------------------------------------


def test_one_code_path_serves_all_three_clients_and_the_clients_differ() -> None:
    specs = [spec_of(c) for c in CLIENTS]
    assert len({s.id for s in specs}) == 3
    assert len({s.offer for s in specs}) == 3
    for client in CLIENTS:
        r = replay(client)
        assert r.run.client_id == client == r.recording.meta.client
        assert r.run.as_of == r.recording.meta.as_of
        assert r.run.queries == r.recording.meta.queries


@pytest.mark.parametrize("client", CLIENTS)
def test_thin_sources_paragraph_appears_exactly_when_entries_fall_short(client: str) -> None:
    brief = brief_of(client)
    from northvaine.radar.brief import _approachable

    full = _approachable(shown_entries(client))
    assert ("\n## Thin sources\n" in brief) == (full < 3)  # D82: approachable accounts
    if full < 3:
        assert "Nothing was added to fill the space." in brief


def test_packaging_with_few_entries_shows_the_thin_sources_paragraph() -> None:
    if len(shown_entries("packaging_supplier")) >= 3:
        pytest.skip("the packaging recording now fills the brief; the paragraph is covered above")
    assert "## Thin sources" in brief_of("packaging_supplier")


def _two_runs(client: str, tmp_path: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
    outputs = []
    for name in ("first", "second"):
        out = tmp_path / name
        assert radar.main(["--client", client, "--out", str(out)]) == 0
        folder = out / client / replay(client).run.as_of.date().isoformat()
        outputs.append({p.name: p.read_bytes() for p in sorted(folder.iterdir())})
    assert sorted(outputs[0]) == ["brief.md", "run.json", "scorecard.md"]
    return outputs[0], outputs[1]


@pytest.mark.parametrize("client", CLIENTS)
def test_two_replays_write_byte_identical_brief_and_scorecard(client: str, tmp_path: Path) -> None:
    first, second = _two_runs(client, tmp_path)
    assert first["brief.md"] == second["brief.md"]
    assert first["scorecard.md"] == second["scorecard.md"]
    assert first["brief.md"].decode("utf-8") == brief_of(client)  # the in-process replay agrees
    assert chr(13).encode() not in first["brief.md"]


def test_two_replays_write_byte_identical_run_records(tmp_path: Path) -> None:
    for client in CLIENTS:
        first, second = _two_runs(client, tmp_path / client)
        assert first["run.json"] == second["run.json"], client


def test_replay_never_reaches_the_network(tmp_path: Path) -> None:
    client = "packaging_supplier"
    """A real transport that raises proves replay serves everything from the recording."""

    class NoNetwork(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"replay reached the network: {request.url}")

    with mock.patch.object(httpx, "AsyncHTTPTransport", NoNetwork):
        assert radar.main(["--client", client, "--out", str(tmp_path)]) == 0
