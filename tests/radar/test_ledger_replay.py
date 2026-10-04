"""T4.6: the evidence ledger replayed on real recorded model replies, for every sample client.

For each client spec in `tests/fixtures/clients/` (plus the website fixtures) one loop replays the
recorded sensor fixtures through `get_sensor`, converts them with `evidence_document_from_sensor`
and runs `build_evidence` under `client_override(ReplayClient(recording))` inside
`replay_environment(recording)`. No network, no `.env`. The same replayed results feed
`test_evidence_invariants.py` through `replay_group` (cached, plain data only).

This module also checks what was SENT to the model (call shape and order, fencing, what the support
check may see), the injected-instruction page, and prints (does not assert) the cosine
distributions so the orchestrator can tune thresholds.

Nothing here edits a recording. A stale recording raises `LlmReplayMismatch`: report it, only the
orchestrator re-records.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from northvaine.brain import llm
from northvaine.brain.budget import RunContext
from northvaine.brain.errors import LlmReplayMismatch
from northvaine.brain.fencing import PREAMBLE
from northvaine.brain.replay import (
    LlmRecording,
    ReplayClient,
    load_recording,
    replay_environment,
)
from northvaine.core.models import (
    ConceptStatus,
    EventConceptRow,
    EvidenceDocument,
    EvidenceKind,
    LedgerResult,
)
from northvaine.core.settings import Settings
from northvaine.radar.concepts import cosine
from northvaine.radar.ledger import build_evidence, evidence_document_from_sensor
from northvaine.sensors.base import SensorDocument, SensorQuery, content_hash
from northvaine.sensors.html_text import html_to_text
from northvaine.sensors.registry import get_sensor
from northvaine.sensors.replay import ReplayMismatch, load_exchanges, replay_transport
from northvaine.sensors.website import WebsiteSensor

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "fixtures"
CLIENT_FILES = sorted((FIXTURES / "clients").glob("*.json"))
RECORDINGS = FIXTURES / "llm" / "ledger"
WEB_DIR = FIXTURES / "web"
MIGRATION_0002 = ROOT.parent / "migrations" / "versions" / "0002_architecture_v2.py"
WEB = "web"
GROUPS = [p.stem for p in CLIENT_FILES] + [WEB]
SENSOR_SETTINGS = Settings(
    _env_file=None, ted_min_interval_seconds=0, tavily_api_key=SecretStr("replay-only")
)
WEB_URL_PREFIX = "https://fixtures.invalid/"
WEB_FETCHED = datetime(2026, 10, 1, tzinfo=UTC)
FENCE = re.compile(
    r"-----BEGIN (?P<label>[A-Z_]+) DATA (?P<nonce>[0-9a-f]{32})-----\n"
    r"(?P<body>.*?)\n-----END (?P=label) DATA (?P=nonce)-----",
    re.DOTALL,
)


@pytest.fixture(autouse=True)
def _no_dotenv(clean_settings: None) -> None:
    """Defaults only: the replay must not depend on the developer's `.env` or shell."""


# --- documents ------------------------------------------------------------------------------


def load_spec(group: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "clients" / f"{group}.json").read_text(encoding="utf-8"))


async def sensor_documents(spec: dict[str, Any]) -> list[EvidenceDocument]:
    """The documents a client's recorded sensor fixtures produce, through `get_sensor`."""
    docs: dict[Any, EvidenceDocument] = {}
    for name, queries in spec["sensors"].items():
        for number, raw in enumerate(queries, start=1):
            path = FIXTURES / "sensors" / name / f"{spec['id']}_{number}.json"
            if not path.exists():
                continue  # the recorder refused some Tavily responses; only recorded calls replay
            transport = replay_transport(load_exchanges(path))
            async with httpx.AsyncClient(transport=transport) as client:
                sensor = get_sensor(name, client=client, settings=SENSOR_SETTINGS)
                try:
                    result = await sensor.search(SensorQuery.model_validate(raw))
                except ReplayMismatch:
                    continue
            for sensor_doc in result.documents:
                evidence = evidence_document_from_sensor(sensor_doc)
                docs.setdefault(evidence.id, evidence)
    return list(docs.values())


def web_documents() -> list[EvidenceDocument]:
    """`tests/fixtures/web/*.html` as `website` documents (the same shape the recorder used)."""
    docs = []
    for path in sorted(WEB_DIR.glob("*.html")):
        title, text = html_to_text(path.read_text(encoding="utf-8"))
        docs.append(
            evidence_document_from_sensor(
                SensorDocument(
                    source=WebsiteSensor.name,
                    tier=WebsiteSensor.tier,
                    url=f"{WEB_URL_PREFIX}{path.name}",
                    title=title,
                    text=text,
                    content_hash=content_hash(text),
                    fetched_at=WEB_FETCHED,
                    available_at=WEB_FETCHED,
                )
            )
        )
    return docs


async def group_documents(group: str) -> list[EvidenceDocument]:
    if group == WEB:
        return web_documents()
    return await sensor_documents(load_spec(group))


def seeded_concepts() -> list[EventConceptRow]:
    """The twelve level-0 concepts migration 0002 seeds, in `load_concepts` order (level, label).

    The recordings were made against the seeded database, so the extract prompt lists exactly
    these labels and descriptions. Read from the migration so no label is typed here.
    """
    spec = importlib.util.spec_from_file_location("nv_migration_0002", MIGRATION_0002)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [
        EventConceptRow(
            id=uuid4(),
            parent_id=None,
            level=0,
            label=label,
            description=description,
            embedding=None,
            status=ConceptStatus.ACTIVE,
            merged_into=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for label, description in sorted(module._SEED)
    ]


# --- the replay loop ------------------------------------------------------------------------


class SpyClient:
    """Wraps a `ReplayClient`: logs every request body (with its real nonce) per document."""

    def __init__(self, inner: ReplayClient) -> None:
        self.inner = inner
        self.current: list[tuple[str, dict[str, Any]]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    async def _chat(self, **body: Any) -> Any:
        self.current.append(("chat", body))
        return await self.inner.chat.completions.create(**body)

    async def _embed(self, **body: Any) -> Any:
        self.current.append(("embed", body))
        return await self.inner.embeddings.create(**body)


@dataclass
class DocRun:
    doc: EvidenceDocument
    result: LedgerResult
    calls: list[tuple[str, dict[str, Any]]]

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]


@dataclass
class GroupRun:
    name: str
    recording: LlmRecording
    runs: list[DocRun] = field(default_factory=list)
    served: list[str] = field(default_factory=list)
    concepts: list[EventConceptRow] = field(default_factory=list)


_CACHE: dict[str, GroupRun] = {}


def recording_for(group: str) -> LlmRecording:
    return load_recording(RECORDINGS / f"{group}.json")


async def replay_documents(
    group: str,
    docs: list[EvidenceDocument],
    recording: LlmRecording,
    concepts: list[EventConceptRow],
) -> GroupRun:
    """`build_evidence` for every document, as the recorder did (no recent events, one run)."""
    client = ReplayClient(recording)
    spy = SpyClient(client)
    out = GroupRun(name=group, recording=recording, concepts=concepts)
    run = RunContext()
    with replay_environment(recording), llm.client_override(spy):
        for doc in docs:
            spy.current = []
            result = await build_evidence(doc, concepts, [], run=run)
            out.runs.append(DocRun(doc=doc, result=result, calls=spy.current))
    out.served = list(client.served)
    return out


async def replay_group(group: str) -> GroupRun:
    """The replayed results of one group, computed once per process (plain data, no loop state)."""
    if group not in _CACHE:
        _CACHE[group] = await replay_documents(
            group, await group_documents(group), recording_for(group), seeded_concepts()
        )
    return _CACHE[group]


def schema_name(body: dict[str, Any]) -> str | None:
    return ((body.get("response_format") or {}).get("json_schema") or {}).get("name")


def fenced(content: str) -> tuple[list[tuple[str, str]], str]:
    """([(label, body)] of every fenced block, the text left once the blocks are removed)."""
    blocks = []
    for m in FENCE.finditer(content):
        body = m.group("body")
        assert body.startswith(PREAMBLE + "\n\n"), "a fence must start with the data preamble"
        blocks.append((m.group("label"), body[len(PREAMBLE) + 2 :]))
    return blocks, FENCE.sub("", content)


def request_text(body: dict[str, Any]) -> str:
    return "\n".join(str(m["content"]) for m in body["messages"])


def windows(text: str, size: int = 30, step: int = 10) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text]
    return [text[i : i + size] for i in range(0, len(text) - size + 1, step)]


# --- tests ----------------------------------------------------------------------------------


@pytest.mark.parametrize("group", GROUPS)
def test_every_client_has_a_recording_in_the_documented_shape(group: str) -> None:
    recording = recording_for(group)
    assert {"fast", "embed"} <= set(recording.models)
    assert recording.recorded_at
    assert {"extract_max_tokens", "support_max_tokens"} <= set(recording.settings)
    keys = [(e.kind, e.key) for e in recording.exchanges]
    assert len(keys) == len(set(keys)), "an exchange key must be unique"


@pytest.mark.parametrize("group", GROUPS)
async def test_group_replays_and_uses_every_recorded_exchange(group: str) -> None:
    run = await replay_group(group)
    docs = await group_documents(group)
    assert len(run.runs) == len(docs) >= 1
    # Every recorded exchange was asked for by the code under test: a recording nothing asks for
    # is stale, and a missing one would already have raised LlmReplayMismatch above.
    assert set(run.served) == {e.key for e in run.recording.exchanges}
    assert len(run.served) == len(set(run.served)), "no exchange is requested twice"


@pytest.mark.parametrize("group", GROUPS)
async def test_every_eligible_full_text_document_is_served_by_a_recording(group: str) -> None:
    run = await replay_group(group)
    full_text = [r for r in run.runs if r.result.eligibility.kind == EvidenceKind.FULL_TEXT]
    for r in full_text:
        assert r.kinds, f"{r.doc.url}: a full-text document made no model call"
        assert schema_name(r.calls[0][1]) == "ExtractionOutput"
    expected_exchanges = sum(len(r.calls) for r in run.runs)
    assert expected_exchanges == len(run.recording.exchanges)


async def test_a_missing_recording_fails_instead_of_skipping() -> None:
    """Change one character of an eligible full-text document: its request has no recording, so
    the replay must raise, never skip the document."""
    group = "stone_supplier"
    run = await replay_group(group)
    target = next(r for r in run.runs if r.result.eligibility.kind == EvidenceKind.FULL_TEXT)
    changed = target.doc.model_copy(update={"text": target.doc.text + " X"})
    with pytest.raises(LlmReplayMismatch):
        await replay_documents(group, [changed], run.recording, run.concepts)


async def test_replay_does_not_depend_on_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A different MODEL_FAST in the environment, and no Nebius credentials, change nothing; the
    environment is back to what it was afterwards."""
    group = "stone_supplier"
    baseline = await replay_group(group)
    monkeypatch.setenv("MODEL_FAST", "some/other-model")
    monkeypatch.setenv("MODEL_EMBED", "some/other-embed")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_BASE_URL", raising=False)
    from northvaine.core import settings as settings_module

    settings_module.get_settings.cache_clear()
    again = await replay_documents(
        group, await group_documents(group), recording_for(group), seeded_concepts()
    )
    assert os.environ["MODEL_FAST"] == "some/other-model"
    assert os.environ["MODEL_EMBED"] == "some/other-embed"
    assert [(r.doc.id, [c.status for c in r.result.checks]) for r in again.runs] == [
        (r.doc.id, [c.status for c in r.result.checks]) for r in baseline.runs
    ]
    # The recorded model id is what the requests carry, whatever the environment says.
    for r in again.runs:
        for kind, body in r.calls:
            wanted = baseline.recording.models["embed" if kind == "embed" else "fast"]
            assert body["model"] == wanted


@pytest.mark.parametrize("group", GROUPS)
async def test_leads_and_structured_records_make_no_model_call(group: str) -> None:
    run = await replay_group(group)
    for r in run.runs:
        if r.result.eligibility.kind in (EvidenceKind.LEAD, EvidenceKind.STRUCTURED):
            assert r.calls == [], f"{r.doc.source_name} {r.doc.url} called a model"
            assert r.result.llm_calls == 0
        if r.result.eligibility.kind == EvidenceKind.LEAD:
            assert r.result.checks == [] and r.result.events == []
            assert r.result.eligibility.reason
        if r.doc.source_name == "ted":
            assert r.result.eligibility.kind == EvidenceKind.STRUCTURED


async def test_a_client_with_only_snippet_leads_costs_nothing() -> None:
    run = await replay_group("packaging_supplier")
    assert run.recording.exchanges == []
    assert run.served == []
    assert run.runs
    assert all(r.result.eligibility.kind == EvidenceKind.LEAD for r in run.runs)


@pytest.mark.parametrize("group", GROUPS)
async def test_calls_happen_in_order_and_only_where_they_should(group: str) -> None:
    """extract, then (only if a quote passed the code check) one support call, then one embed per
    event, each embedding the code-composed description."""
    run = await replay_group(group)
    for r in run.runs:
        if r.result.eligibility.kind != EvidenceKind.FULL_TEXT:
            continue
        where = r.doc.url
        kinds = r.kinds
        assert kinds[0] == "chat" and schema_name(r.calls[0][1]) == "ExtractionOutput", where
        passed = [c for c in r.result.checks if c.quote_offset is not None]
        support = [b for k, b in r.calls if k == "chat" and schema_name(b) == "SupportOutput"]
        assert len(support) == (1 if passed else 0), where
        if support:
            assert schema_name(r.calls[1][1]) == "SupportOutput", f"{where}: support must be 2nd"
        embeds = [b for k, b in r.calls if k == "embed"]
        assert len(embeds) == len(r.result.events), where
        assert kinds == ["chat"] * (1 + len(support)) + ["embed"] * len(embeds), where
        assert [b["input"] for b in embeds] == [e.description for e in r.result.events], where
        assert r.result.llm_calls == len(kinds), where


@pytest.mark.parametrize("group", GROUPS)
async def test_no_support_request_carries_a_quote_that_failed_the_code_check(group: str) -> None:
    run = await replay_group(group)
    for r in run.runs:
        support = [b for k, b in r.calls if k == "chat" and schema_name(b) == "SupportOutput"]
        failed = [c for c in r.result.checks if c.quote_offset is None]
        passed = [c for c in r.result.checks if c.quote_offset is not None]
        sent: list[dict[str, Any]] = []
        for body in support:
            blocks, _ = fenced(request_text(body))
            assert [label for label, _ in blocks] == ["CLAIMS"]
            sent += [json.loads(line) for line in blocks[0][1].splitlines() if line.strip()]
        if r.result.eligibility.kind != EvidenceKind.FULL_TEXT:
            passed = []  # structured records are code-verified: nothing goes to the model
        assert [(s["statement"], s["quote"]) for s in sent] == [
            (c.draft.statement, c.draft.source_quote) for c in passed
        ], r.doc.url
        assert [s["index"] for s in sent] == list(range(len(passed)))
        for c in failed:
            assert c.status.value in ("quote_not_found", "quote_too_short")
            assert all(s["quote"] != c.draft.source_quote for s in sent), (
                f"{r.doc.url}: a failed quote reached the support check: {c.draft.source_quote!r}"
            )
            assert all(s["statement"] != c.draft.statement for s in sent) or any(
                p.draft.statement == c.draft.statement for p in passed
            )


@pytest.mark.parametrize("group", GROUPS)
async def test_document_text_statements_and_quotes_are_only_sent_inside_a_fence(
    group: str,
) -> None:
    run = await replay_group(group)
    for r in run.runs:
        for kind, body in r.calls:
            if kind != "chat":
                continue
            blocks, outside = fenced(request_text(body))
            labels = [label for label, _ in blocks]
            name = schema_name(body)
            if name == "ExtractionOutput":
                assert labels == ["DOC_TITLE", "DOC_URL", "DOC_TEXT"], r.doc.url
                by_label = dict(blocks)
                limit = 12000
                assert by_label["DOC_TEXT"] == r.doc.text[:limit]
                assert by_label["DOC_URL"] == r.doc.url
                assert by_label["DOC_TITLE"] == (r.doc.title or "")
                for piece in windows(r.doc.text[:limit]):
                    assert piece not in outside, f"{r.doc.url}: document text outside a fence"
                assert r.doc.url not in outside
            else:
                assert name == "SupportOutput"
                assert labels == ["CLAIMS"]
                for line in blocks[0][1].splitlines():
                    entry = json.loads(line)
                    assert set(entry) == {"index", "statement", "quote"}
                    for part in (entry["statement"], entry["quote"]):
                        assert part not in outside, f"{r.doc.url}: {part!r} outside the fence"
                        assert json.dumps(part, ensure_ascii=True) not in outside


@pytest.mark.parametrize("group", GROUPS)
async def test_a_support_request_never_contains_the_document(group: str) -> None:
    """The support check judges a quote alone: it sees statements and quotes, never the document
    text, title or url."""
    run = await replay_group(group)
    for r in run.runs:
        for kind, body in r.calls:
            if kind != "chat" or schema_name(body) != "SupportOutput":
                continue
            text = request_text(body)
            blocks, outside = fenced(text)
            assert blocks and [label for label, _ in blocks] == ["CLAIMS"]
            assert r.doc.url not in text
            if r.doc.title and len(r.doc.title) >= 8:
                assert r.doc.title not in text
            # Outside the one fence there is only the prompt; inside it only claim lines.
            for piece in windows(r.doc.text):
                assert piece not in outside, f"{r.doc.url}: document text outside the quotes"
            for line in blocks[0][1].splitlines():
                assert set(json.loads(line)) == {"index", "statement", "quote"}


async def test_the_injected_instruction_page_is_not_obeyed() -> None:
    run = await replay_group(WEB)
    injected = [r for r in run.runs if "ignore previous instructions" in r.doc.text]
    assert len(injected) == 1, "the web fixtures must include the injected-instruction page"
    r = injected[0]
    assert r.result.eligibility.kind == EvidenceKind.FULL_TEXT
    # exactly the two calls of an ordinary page: nothing was done on the page's behalf
    assert r.kinds == ["chat", "chat"]
    # The page text is quoted verbatim as data. What must not appear is anything that carries
    # the instruction out: no statement, subject, slot or description says it.
    produced: list[str] = []
    for check in r.result.checks:
        produced += [check.draft.statement]
        if check.draft.subject:
            produced.append(check.draft.subject.name)
    for event in r.result.events:
        produced += [event.description, *map(str, event.slots.values())]
        if event.subject:
            produced.append(event.subject.name)
    blob = " ".join(produced).lower()
    for phrase in ("system prompt", "reveal", "ignore previous", "instructions"):
        assert phrase not in blob, f"the page's instruction leaked into a result: {phrase!r}"
    # and the model reply was a plain extraction, so no verified claim is an order or a refusal
    for check in r.result.checks:
        if check.verified:
            assert "prompt" not in check.draft.statement.lower()


async def test_replay_checks_are_the_same_on_a_second_run() -> None:
    """Replay is deterministic: statuses, offsets, fingerprints and event fingerprints agree."""
    group = "coldchain_maker"
    first = await replay_group(group)
    second = await replay_documents(
        group, await group_documents(group), recording_for(group), seeded_concepts()
    )

    def view(g: GroupRun) -> list[Any]:
        return [
            (
                [(c.status, c.quote_offset, c.fingerprint) for c in r.result.checks],
                [e.fingerprint for e in r.result.events],
            )
            for r in g.runs
        ]

    assert view(first) == view(second)


# --- printed, not asserted: numbers for the orchestrator -------------------------------------


def histogram(values: list[float]) -> str:
    edges = [-1.0, 0.0, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0000001]
    bins = []
    for lo, hi in pairwise(edges):
        n = sum(1 for v in values if lo <= v < hi)
        bins.append(f"[{lo:.2f},{min(hi, 1.0):.2f}):{n}")
    return "  ".join(bins)


def describe(values: list[float]) -> str:
    if not values:
        return "none"
    ordered = sorted(values)
    mid = ordered[len(ordered) // 2]
    return (
        f"n={len(values)} min={ordered[0]:.3f} median={mid:.3f} max={ordered[-1]:.3f} "
        f"mean={sum(values) / len(values):.3f}"
    )


async def test_print_cosine_distributions(capsys: pytest.CaptureFixture[str]) -> None:
    """Prints the numbers that tune `concept_match_min_cosine` (0.80) and `event_cluster_min_cosine`
    (0.85). Asserts only that the vectors are usable (finite, 1024 long, not all zero)."""
    events = []  # (group, doc url, event)
    for group in GROUPS:
        run = await replay_group(group)
        for r in run.runs:
            events += [(group, r.doc.url, e) for e in r.result.events if e.embedding is not None]
    for _, _, e in events:
        assert e.embedding is not None
        assert len(e.embedding) == 1024
        assert all(math.isfinite(x) for x in e.embedding)
        assert any(e.embedding)

    pairs = []  # (cosine, same type, same document, a, b)
    for i, (_, ua, a) in enumerate(events):
        for _, ub, b in events[i + 1 :]:
            assert a.embedding is not None and b.embedding is not None
            pairs.append((cosine(a.embedding, b.embedding), a.event_type == b.event_type, ua == ub))
    same_type = [c for c, same, _ in pairs if same]
    other_type = [c for c, same, _ in pairs if not same]
    same_doc = [c for c, _, doc in pairs if doc]
    proposed = [e for _, _, e in events if e.concept.is_new]
    with capsys.disabled():
        print("\n=== cosine distributions over the replayed event embeddings ===")
        print(f"events with an embedding: {len(events)} (recorded vectors, 1024 dimensions)")
        print(f"cluster-style pairs, all:        {describe([c for c, _, _ in pairs])}")
        print(f"  same event type:               {describe(same_type)}")
        print(f"  different event type:          {describe(other_type)}")
        print(f"  same document:                 {describe(same_doc)}")
        print(f"  histogram (all pairs): {histogram([c for c, _, _ in pairs])}")
        for c, same, doc in sorted(pairs, reverse=True)[:8]:
            print(f"  top pair cosine={c:.3f} same_type={same} same_document={doc}")
        n_cluster = sum(1 for c, same, _ in pairs if same and c >= 0.85)
        n_concept = sum(1 for c, _, _ in pairs if c >= 0.80)
        print(f"pairs at or above event_cluster_min_cosine 0.85 (same type): {n_cluster}")
        print(f"pairs at or above concept_match_min_cosine 0.80 (any type):  {n_concept}")
        print("concept assignment: the seeded level-0 concepts have NO embedding in these")
        print("recordings (seed_concept_embeddings was not run), so an event is never compared")
        print("with a concept and none is matched on cosine. Outcomes per event:")
        for _, _, e in events:
            c = e.concept
            print(
                f"  {e.event_type:20} -> level {c.level} {c.label} "
                f"(new={c.is_new}, status={c.status}); description[:60]={e.description[:60]!r}"
            )
        print(f"events that proposed a new child concept: {len(proposed)}")
        print("(no cosine to print for concept assignment: nothing was above or below 0.80)")
