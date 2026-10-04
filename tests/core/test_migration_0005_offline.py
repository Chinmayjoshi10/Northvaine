"""Migration 0005 (evidence ledger), rendered offline and read as text (T4.0)."""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from tests.core.ddl_parser import parse_schema

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "alembic.ini"
REVISION_0005 = ROOT / "migrations" / "versions" / "0005_evidence_ledger.py"
MARKER = "Running upgrade 0004 -> 0005"


def render(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    cfg = Config(str(ALEMBIC_INI), output_buffer=buffer)
    if down:
        command.downgrade(cfg, target, sql=True)
    else:
        command.upgrade(cfg, target, sql=True)
    return buffer.getvalue()


@pytest.fixture
def section_0005(clean_settings: None) -> str:
    sql = render("head")
    assert MARKER in sql
    return sql.split(MARKER, 1)[1]


@pytest.fixture
def downgrade_0005(clean_settings: None) -> str:
    return render("0005:0004", down=True)


def load_revision():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("rev_0005", REVISION_0005)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain() -> None:
    rev = load_revision()
    assert rev.revision == "0005" and rev.down_revision == "0004"


def test_upgrade_first_refuses_non_empty_tables(section_0005: str) -> None:
    guard = section_0005.index("RAISE EXCEPTION")
    first_alter = section_0005.index("ALTER TABLE claims ADD COLUMN status")
    assert guard < first_alter
    assert "FROM claims" in section_0005[:first_alter]
    assert "FROM events" in section_0005[:first_alter]


@pytest.mark.parametrize(
    "fragment",
    [
        "ALTER TABLE claims ADD COLUMN status text NOT NULL DEFAULT 'pending'",
        "CHECK (status IN ('pending','verified','quote_not_found','quote_too_short',"
        "'unsupported','ineligible_document'))",
        "ALTER TABLE claims ADD COLUMN meta jsonb NOT NULL DEFAULT '{}'",
        "ALTER TABLE claims ADD COLUMN fingerprint text NOT NULL",
        "ALTER TABLE claims ADD CONSTRAINT claims_fingerprint_key UNIQUE (fingerprint)",
        "ALTER TABLE claims ADD CONSTRAINT claims_verified_status "
        "CHECK (verified = (status = 'verified'))",
        "ALTER TABLE claims ADD CONSTRAINT claims_verified_complete "
        "CHECK (NOT verified OR (quote_offset IS NOT NULL AND verified_by IS NOT NULL))",
        "CREATE INDEX claims_document ON claims (document_id)",
        "ALTER TABLE events ADD COLUMN available_at timestamptz",
        "ALTER TABLE events ADD COLUMN description text",
        "ALTER TABLE events ADD COLUMN embedding vector(1024)",
        "ALTER TABLE events ADD COLUMN fingerprint text NOT NULL",
        "ALTER TABLE events ADD CONSTRAINT events_fingerprint_key UNIQUE (fingerprint)",
        "CREATE INDEX events_type_occurred ON events (event_type, occurred_on)",
        "CREATE VIEW verified_claims AS SELECT c.*, d.available_at, d.workspace_id "
        "FROM claims c JOIN documents d ON d.id = c.document_id WHERE c.verified",
    ],
)
def test_upgrade_renders_every_statement(section_0005: str, fragment: str) -> None:
    assert fragment in section_0005


def test_events_embedding_has_no_index(section_0005: str) -> None:
    assert "events_embedding" not in section_0005
    assert "hnsw" not in section_0005.lower()


def test_downgrade_drops_everything_upgrade_added(downgrade_0005: str) -> None:
    for statement in (
        "DROP VIEW verified_claims",
        "DROP INDEX events_type_occurred",
        "ALTER TABLE events DROP CONSTRAINT events_fingerprint_key",
        "ALTER TABLE events DROP COLUMN fingerprint",
        "ALTER TABLE events DROP COLUMN embedding",
        "ALTER TABLE events DROP COLUMN description",
        "ALTER TABLE events DROP COLUMN available_at",
        "DROP INDEX claims_document",
        "ALTER TABLE claims DROP CONSTRAINT claims_verified_complete",
        "ALTER TABLE claims DROP CONSTRAINT claims_verified_status",
        "ALTER TABLE claims DROP CONSTRAINT claims_fingerprint_key",
        "ALTER TABLE claims DROP COLUMN fingerprint",
        "ALTER TABLE claims DROP COLUMN meta",
        "ALTER TABLE claims DROP COLUMN status",
    ):
        assert statement in downgrade_0005, statement


def test_downgrade_is_the_exact_reverse_of_upgrade() -> None:
    rev = load_revision()
    assert len(rev.DOWNGRADE) == len(rev.UPGRADE)
    for up, down in zip(rev.UPGRADE, reversed(rev.DOWNGRADE), strict=True):
        if up.startswith("CREATE INDEX"):
            assert down == f"DROP INDEX {up.split()[2]}", up
        elif up.startswith("CREATE VIEW"):
            assert down == f"DROP VIEW {up.split()[2]}", up
        elif "ADD COLUMN" in up:
            table, column = up.split()[2], up.split("ADD COLUMN")[1].split()[0]
            assert down == f"ALTER TABLE {table} DROP COLUMN {column}", up
        else:
            table, name = up.split()[2], up.split("ADD CONSTRAINT")[1].split()[0]
            assert down == f"ALTER TABLE {table} DROP CONSTRAINT {name}", up


def test_the_replayed_tables_have_the_new_columns(clean_settings: None) -> None:
    schema = parse_schema(render("head"))
    claims, events = schema.tables["claims"], schema.tables["events"]
    assert claims["status"].type == "text" and not claims["status"].nullable
    assert claims["status"].check_values == (
        "pending", "verified", "quote_not_found", "quote_too_short", "unsupported",
        "ineligible_document",
    )  # fmt: skip
    assert claims["meta"].type == "jsonb" and not claims["meta"].nullable
    assert claims["fingerprint"].type == "text" and not claims["fingerprint"].nullable
    assert events["available_at"].type == "timestamptz" and events["available_at"].nullable
    assert events["description"].type == "text" and events["description"].nullable
    assert events["embedding"].type == "vector(1024)" and events["embedding"].nullable
    assert events["fingerprint"].type == "text" and not events["fingerprint"].nullable
    assert "verified_claims" in schema.views
    assert {"claims_document", "events_type_occurred"} <= schema.indexes


def test_migration_reads_no_settings() -> None:
    source = REVISION_0005.read_text(encoding="utf-8")
    assert not re.search(r"get_settings|Settings|environ", source)
