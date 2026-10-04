"""The frozen M4 contracts (factory/board/M4/PLAN.md, "Frozen contracts") exist as specified.

Checks shape only: names, parameter names/kinds/defaults, async-ness, and that importing the
modules needs no env and does no I/O. It never asserts that a stub raises: that would block the
tickets (T4.1-T4.5) that implement them. Fully implemented helpers are tested for behaviour.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from northvaine.brain import replay
from northvaine.core import ledger as core_ledger
from northvaine.core.models import DocumentRow, QuoteMode, SourceTier
from northvaine.radar import concepts, extract, structured, verify
from northvaine.radar import ledger as radar_ledger
from northvaine.radar import quote_check as quote
from northvaine.sensors.base import SensorDocument, content_hash

P = inspect.Parameter
POS = P.POSITIONAL_OR_KEYWORD
KW = P.KEYWORD_ONLY
NO = P.empty


def params(func: object) -> list[tuple[str, inspect._ParameterKind, object]]:
    sig = inspect.signature(func)  # type: ignore[arg-type]
    return [(p.name, p.kind, p.default) for p in sig.parameters.values()]


# (module, function) -> (is_async, parameters)
CONTRACT: dict[tuple[object, str], tuple[bool, list[tuple[str, object, object]]]] = {
    (replay, "normalize_body"): (False, [("body", POS, NO)]),
    (replay, "exchange_key"): (False, [("kind", POS, NO), ("body", POS, NO)]),
    (replay, "load_recording"): (False, [("path", POS, NO)]),
    (replay, "save_recording"): (False, [("path", POS, NO), ("recording", POS, NO)]),
    (replay, "replay_environment"): (False, [("recording", POS, NO)]),
    (quote, "normalize_text"): (False, [("text", POS, NO)]),
    (quote, "find_quote"): (
        False,
        [
            ("text", POS, NO),
            ("quote", POS, NO),
            ("mode", KW, QuoteMode.EXTRACTED),
            ("settings", KW, None),
        ],
    ),
    (quote, "quote_contains"): (False, [("quote", POS, NO), ("fragment", POS, NO)]),
    (verify, "is_evidence_document"): (False, [("doc", POS, NO), ("settings", POS, None)]),
    (verify, "claim_fingerprint"): (
        False,
        [("document_id", POS, NO), ("statement", POS, NO), ("source_quote", POS, NO)],
    ),
    (verify, "verify_claims"): (
        True,
        [
            ("doc", POS, NO),
            ("drafts", POS, NO),
            ("run", KW, NO),
            ("mode", KW, QuoteMode.EXTRACTED),
            ("support", KW, True),
            ("session", KW, None),
            ("settings", KW, None),
        ],
    ),
    (extract, "document_event_types"): (False, [("concepts", POS, NO), ("settings", POS, None)]),
    (extract, "extract"): (
        True,
        [
            ("doc", POS, NO),
            ("concepts", POS, NO),
            ("run", KW, NO),
            ("session", KW, None),
            ("settings", KW, None),
        ],
    ),
    (structured, "structured_evidence"): (False, [("doc", POS, NO)]),
    (concepts, "cosine"): (False, [("a", POS, NO), ("b", POS, NO)]),
    (concepts, "assign_concept"): (
        False,
        [
            ("draft", POS, NO),
            ("embedding", POS, NO),
            ("concepts", POS, NO),
            ("settings", KW, None),
        ],
    ),
    (concepts, "assign_cluster"): (
        False,
        [("new", POS, NO), ("existing", POS, NO), ("settings", KW, None)],
    ),
    (concepts, "seed_concept_embeddings"): (True, [("session", POS, NO), ("run", KW, NO)]),
    (radar_ledger, "evidence_document_from_row"): (
        False,
        [("row", POS, NO), ("source_name", POS, NO)],
    ),
    (radar_ledger, "evidence_document_from_sensor"): (
        False,
        [("doc", POS, NO), ("document_id", KW, None)],
    ),
    (radar_ledger, "event_fingerprint"): (
        False,
        [
            ("event_type", POS, NO),
            ("claim_fingerprints", POS, NO),
            ("occurred_on", POS, NO),
            ("subject_key", POS, NO),
        ],
    ),
    (radar_ledger, "ground_event"): (False, [("draft", POS, NO), ("checks", POS, NO)]),
    (radar_ledger, "describe_event"): (
        False,
        [("event_type", POS, NO), ("subject", POS, NO), ("statements", POS, NO)],
    ),
    (radar_ledger, "build_evidence"): (
        True,
        [
            ("doc", POS, NO),
            ("concepts", POS, NO),
            ("recent_events", POS, NO),
            ("run", KW, NO),
            ("session", KW, None),
            ("settings", KW, None),
        ],
    ),
    (radar_ledger, "process_document"): (
        True,
        [
            ("session", POS, NO),
            ("doc", POS, NO),
            ("run", KW, NO),
            ("as_of", KW, None),
            ("settings", KW, None),
        ],
    ),
    (core_ledger, "save_claims"): (True, [("session", POS, NO), ("checks", POS, NO)]),
    (core_ledger, "verified_claims"): (
        True,
        [
            ("session", POS, NO),
            ("document_ids", KW, None),
            ("as_of", KW, None),
            ("workspace_id", KW, None),
        ],
    ),
    (core_ledger, "load_concepts"): (
        True,
        [("session", POS, NO), ("statuses", KW, ("active", "proposed"))],
    ),
    (core_ledger, "ensure_concept"): (True, [("session", POS, NO), ("assignment", POS, NO)]),
    (core_ledger, "set_concept_embedding"): (
        True,
        [("session", POS, NO), ("concept_id", POS, NO), ("embedding", POS, NO)],
    ),
    (core_ledger, "save_events"): (True, [("session", POS, NO), ("events", POS, NO)]),
    (core_ledger, "events_for_clustering"): (
        True,
        [
            ("session", POS, NO),
            ("event_type", KW, NO),
            ("occurred_from", KW, NO),
            ("occurred_to", KW, NO),
            ("as_of", KW, None),
            ("limit", KW, 200),
        ],
    ),
}


@pytest.mark.parametrize(
    ("module", "name"), list(CONTRACT), ids=lambda v: v if isinstance(v, str) else v.__name__
)
def test_signature_and_async_kind(module: object, name: str) -> None:
    is_async, expected = CONTRACT[(module, name)]
    func = getattr(module, name)
    assert params(func) == expected
    assert inspect.iscoroutinefunction(func) is is_async


def test_replay_classes() -> None:
    assert params(replay.ReplayClient.__init__)[1:] == [("recording", POS, NO)]
    assert params(replay.RecordingClient.__init__)[1:] == [("inner", POS, NO)]
    assert params(replay.RecordingClient.recording)[1:] == [
        ("models", POS, NO),
        ("settings", POS, NO),
    ]
    assert list(replay.LlmExchange.model_fields) == [
        "kind",
        "key",
        "prompt_version",
        "request",
        "response",
    ]
    assert list(replay.LlmRecording.model_fields) == [
        "recorded_at",
        "models",
        "settings",
        "exchanges",
    ]


def test_unverified_claim_error_is_a_value_error() -> None:
    assert issubclass(core_ledger.UnverifiedClaimError, ValueError)


def test_every_public_name_is_exported() -> None:
    for module in (replay, quote, verify, extract, structured, concepts, radar_ledger, core_ledger):
        for name in module.__all__:
            assert hasattr(module, name), f"{module.__name__}.{name}"


def test_importing_the_modules_needs_no_env_and_does_no_io(tmp_path: Path) -> None:
    code = textwrap.dedent(
        """
        import builtins, socket, sys
        calls = []
        real_open = builtins.open
        def spy_open(file, *a, **k):
            calls.append(str(file))
            return real_open(file, *a, **k)
        builtins.open = spy_open
        def no_network(*a, **k):
            raise AssertionError("network at import")
        socket.socket.connect = no_network
        import northvaine.brain.replay
        import northvaine.core.ledger
        import northvaine.radar.quote_check, northvaine.radar.verify, northvaine.radar.extract
        import northvaine.radar.structured, northvaine.radar.concepts, northvaine.radar.ledger
        assert "httpx" not in sys.modules, "httpx imported"
        assert "sqlalchemy.ext.asyncio" not in sys.modules, "sqlalchemy imported eagerly"
        """
    )
    hidden = {"DATABASE_URL", "TEST_DATABASE_URL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL"}
    env = {k: v for k, v in os.environ.items() if k.upper() not in hidden}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_replay_module_does_not_import_the_sdk() -> None:
    source = Path(replay.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
    assert "import openai" not in source and "from openai" not in source


# --- implemented in T4.0: behaviour ----------------------------------------------------------


def _sensor_doc(text: str = "Line one\nLine two") -> SensorDocument:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    return SensorDocument(
        source="website",
        tier=SourceTier.COMPANY,
        url="https://example.com/a",
        title="A title",
        text=text,
        content_hash=content_hash(text),
        fetched_at=now,
        available_at=now,
        group_key="g1",
        meta={"k": "v"},
    )


def test_evidence_document_from_sensor_id_is_deterministic() -> None:
    doc = _sensor_doc()
    first = radar_ledger.evidence_document_from_sensor(doc)
    second = radar_ledger.evidence_document_from_sensor(doc)
    assert first.id == second.id == uuid5(NAMESPACE_URL, doc.content_hash)
    assert first.source_name == "website" and first.url == doc.url and first.title == "A title"
    assert first.text == doc.text and first.group_key == "g1" and first.meta == {"k": "v"}
    assert first.available_at == doc.available_at and first.workspace_id is None


def test_evidence_document_from_sensor_takes_an_explicit_id() -> None:
    chosen = uuid4()
    assert (
        radar_ledger.evidence_document_from_sensor(_sensor_doc(), document_id=chosen).id == chosen
    )


def test_different_content_gives_a_different_id() -> None:
    a = radar_ledger.evidence_document_from_sensor(_sensor_doc("one"))
    b = radar_ledger.evidence_document_from_sensor(_sensor_doc("two"))
    assert a.id != b.id


def test_evidence_document_from_sensor_copies_meta() -> None:
    doc = _sensor_doc()
    evidence = radar_ledger.evidence_document_from_sensor(doc)
    evidence.meta["added"] = 1
    assert "added" not in doc.meta


def test_evidence_document_from_row() -> None:
    row_id, workspace = uuid4(), uuid4()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    row = DocumentRow(
        id=row_id, source_id=uuid4(), url="https://example.com/x", content_hash="h",
        title=None, text="body", published_on=date(2026, 9, 30), fetched_at=now,
        workspace_id=workspace, available_at=now, external_id="e", group_key="gk",
        meta={"text_kind": "raw"},
    )  # fmt: skip
    doc = radar_ledger.evidence_document_from_row(row, "tavily")
    assert doc.id == row_id and doc.source_name == "tavily" and doc.text == "body"
    assert doc.workspace_id == workspace and doc.group_key == "gk" and doc.title is None
    assert doc.available_at == now and doc.meta == {"text_kind": "raw"}
    assert isinstance(doc.id, UUID)


BASE = ("contract_awarded", ["b", "a", "c"], date(2026, 3, 1), "acme")


def test_event_fingerprint_is_a_stable_sha256_hex() -> None:
    fp = radar_ledger.event_fingerprint(*BASE)
    assert fp == radar_ledger.event_fingerprint(*BASE)
    assert len(fp) == 64 and int(fp, 16) >= 0


def test_event_fingerprint_ignores_claim_order() -> None:
    reordered = (BASE[0], ["c", "b", "a"], BASE[2], BASE[3])
    assert radar_ledger.event_fingerprint(*reordered) == radar_ledger.event_fingerprint(*BASE)


@pytest.mark.parametrize(
    "changed",
    [
        ("tender_published", BASE[1], BASE[2], BASE[3]),
        (BASE[0], ["a", "b"], BASE[2], BASE[3]),
        (BASE[0], ["a", "b", "c", "d"], BASE[2], BASE[3]),
        (BASE[0], BASE[1], date(2026, 3, 2), BASE[3]),
        (BASE[0], BASE[1], None, BASE[3]),
        (BASE[0], BASE[1], BASE[2], "other"),
        (BASE[0], BASE[1], BASE[2], None),
    ],
)
def test_event_fingerprint_changes_with_any_other_input(changed: tuple) -> None:  # type: ignore[type-arg]
    assert radar_ledger.event_fingerprint(*changed) != radar_ledger.event_fingerprint(*BASE)


def test_event_fingerprint_does_not_confuse_field_boundaries() -> None:
    a = radar_ledger.event_fingerprint("t", ["x,y"], None, None)
    b = radar_ledger.event_fingerprint("t", ["x", "y"], None, None)
    assert a != b
