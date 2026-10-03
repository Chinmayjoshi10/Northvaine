"""Migration 0004 (sensor documents), rendered offline and read as text (T3.0a)."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from tests.core.ddl_parser import parse_schema

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "alembic.ini"
REVISION_0004 = ROOT / "migrations" / "versions" / "0004_sensor_documents.py"
MARKER = "Running upgrade 0003 -> 0004"


def render(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    cfg = Config(str(ALEMBIC_INI), output_buffer=buffer)
    if down:
        command.downgrade(cfg, target, sql=True)
    else:
        command.upgrade(cfg, target, sql=True)
    return buffer.getvalue()


@pytest.fixture
def section_0004(clean_settings: None) -> str:
    sql = render("head")
    assert MARKER in sql
    return sql.split(MARKER, 1)[1]


@pytest.fixture
def downgrade_0004(clean_settings: None) -> str:
    return render("0004:0003", down=True)


def load_revision():
    spec = importlib.util.spec_from_file_location("rev_0004", REVISION_0004)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain() -> None:
    rev = load_revision()
    assert rev.revision == "0004" and rev.down_revision == "0003"


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE documents ADD COLUMN external_id text",
        "ALTER TABLE documents ADD COLUMN group_key text",
        "ALTER TABLE documents ADD COLUMN meta jsonb NOT NULL DEFAULT '{}'",
        "CREATE INDEX documents_group_key ON documents (source_id, group_key)",
        "CREATE INDEX documents_external_id ON documents (source_id, external_id)",
        "CREATE INDEX documents_available_at ON documents (available_at)",
        "ALTER TABLE sources ADD CONSTRAINT sources_name_key UNIQUE (name)",
    ],
)
def test_upgrade_renders_every_statement(section_0004: str, statement: str) -> None:
    assert statement in section_0004


def test_downgrade_drops_everything_upgrade_added(downgrade_0004: str) -> None:
    for statement in (
        "ALTER TABLE sources DROP CONSTRAINT sources_name_key",
        "DROP INDEX documents_available_at",
        "DROP INDEX documents_external_id",
        "DROP INDEX documents_group_key",
        "ALTER TABLE documents DROP COLUMN meta",
        "ALTER TABLE documents DROP COLUMN group_key",
        "ALTER TABLE documents DROP COLUMN external_id",
    ):
        assert statement in downgrade_0004, statement


def test_downgrade_is_the_exact_reverse_of_upgrade() -> None:
    rev = load_revision()
    assert len(rev.DOWNGRADE) == len(rev.UPGRADE)
    for up, down in zip(rev.UPGRADE, reversed(rev.DOWNGRADE), strict=True):
        if up.startswith("CREATE INDEX"):
            assert down == f"DROP INDEX {up.split()[2]}", up
        elif "ADD COLUMN" in up:
            table, column = up.split()[2], up.split("ADD COLUMN")[1].split()[0]
            assert down == f"ALTER TABLE {table} DROP COLUMN {column}", up
        else:
            table, name = up.split()[2], up.split("ADD CONSTRAINT")[1].split()[0]
            assert down == f"ALTER TABLE {table} DROP CONSTRAINT {name}", up


def test_the_replayed_documents_table_has_the_new_columns(clean_settings: None) -> None:
    columns = parse_schema(render("head")).tables["documents"]
    assert columns["external_id"].type == "text" and columns["external_id"].nullable
    assert columns["group_key"].type == "text" and columns["group_key"].nullable
    assert columns["meta"].type == "jsonb" and not columns["meta"].nullable


def test_migration_reads_no_settings() -> None:
    source = REVISION_0004.read_text(encoding="utf-8")
    assert "settings" not in source.replace("No settings are read", "")
