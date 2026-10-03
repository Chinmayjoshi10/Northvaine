"""Migration 0002 (architecture v2) and schema.sql, checked offline with no database.

0002's own section is asserted here; schema.sql is checked against the current head (0003).
"""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from northvaine.core.sqlsplit import split_sql
from northvaine.core.standards import EMBED_DIM_EXPECTED

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "alembic.ini"
REVISION_0002 = ROOT / "migrations" / "versions" / "0002_architecture_v2.py"
SCHEMA = ROOT / "schema.sql"

NEW_TABLES = (
    "event_concepts", "hypotheses", "playbooks", "search_programs", "expectations",
    "beliefs", "belief_source_calibration", "policy_params", "decisions",
    "failure_attributions", "missed_opportunities", "controls", "lessons",
    "inbound_queries", "case_open_questions",
)  # fmt: skip

SEED_LABELS = (
    "facility_opened", "contract_awarded", "tender_published", "hiring_surge",
    "leadership_change", "product_launch", "market_entry", "trade_measure",
    "website_change", "reorder_due", "quote_stale", "inbound_question",
)  # fmt: skip

NULLS_NOT_DISTINCT_TABLES = (
    "beliefs", "policy_params", "belief_source_calibration", "event_concepts", "controls",
)  # fmt: skip


def load_revision_0002():
    spec = importlib.util.spec_from_file_location("rev_0002_architecture_v2", REVISION_0002)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def section_0002(clean_settings: None) -> str:
    """The part of the offline `upgrade head` script that belongs to revision 0002."""
    buffer = io.StringIO()
    command.upgrade(Config(str(ALEMBIC_INI), output_buffer=buffer), "head", sql=True)
    sql = buffer.getvalue()
    marker = "Running upgrade 0001 -> 0002"
    assert marker in sql
    section = sql.split(marker, 1)[1]
    # Stop at the next revision. Without this bound the fixture swallows every
    # later migration, so 0003's sized vectors would be read as 0002's.
    return section.split("Running upgrade 0002 -> 0003", 1)[0]


def statement(section: str, head: str) -> str:
    match = re.search(rf"{head}.*?;\n", section, re.S)
    assert match, head
    return match.group(0)


def test_revision_0002_shape() -> None:
    rev = load_revision_0002()
    assert rev.revision == "0002"
    assert rev.down_revision == "0001"
    assert rev.UPGRADE and rev.DOWNGRADE


@pytest.mark.parametrize("which", ["UPGRADE", "DOWNGRADE"])
def test_every_item_is_one_statement_without_bind_parameters(which: str) -> None:
    for item in getattr(load_revision_0002(), which):
        assert split_sql(item) == [item.strip()], item
        assert not re.search(r":[A-Za-z_]", item), item


def test_downgrade_restores_vector_columns_and_theses_counters() -> None:
    down = "\n".join(load_revision_0002().DOWNGRADE)
    assert "ALTER TABLE theses ALTER COLUMN embedding TYPE vector(1024)" in down
    assert "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024)" in down
    assert "ALTER TABLE theses ADD COLUMN alpha real NOT NULL DEFAULT 1" in down
    assert "ALTER TABLE theses ADD COLUMN beta real NOT NULL DEFAULT 1" in down
    assert "CREATE INDEX jobs_ready ON jobs (status, run_after)" in down


def test_downgrade_drops_new_tables_in_reverse_creation_order() -> None:
    rev = load_revision_0002()
    created = re.findall(r"CREATE TABLE (\w+)", "\n".join(rev.UPGRADE))
    dropped = re.findall(r"DROP TABLE (\w+)", "\n".join(rev.DOWNGRADE))
    assert sorted(created) == sorted(NEW_TABLES)
    assert dropped == list(reversed(created))


def test_offline_upgrade_creates_new_tables_view_and_seed(section_0002: str) -> None:
    created = re.findall(r"CREATE TABLE (\w+) \(", section_0002)
    assert sorted(created) == sorted(NEW_TABLES)
    assert "CREATE VIEW patterns" in section_0002
    for label in SEED_LABELS:
        assert f"'{label}'" in section_0002, label
    assert section_0002.count("(0, '") == 12


def test_offline_upgrade_uses_nulls_not_distinct(section_0002: str) -> None:
    for table in NULLS_NOT_DISTINCT_TABLES:
        create = statement(section_0002, f"CREATE TABLE {table} ")
        assert "UNIQUE NULLS NOT DISTINCT" in create, table
    index = statement(section_0002, "CREATE UNIQUE INDEX cases_open_unique")
    assert "NULLS NOT DISTINCT" in index


def test_offline_upgrade_has_no_sized_vector(section_0002: str) -> None:
    assert "vector(" not in section_0002


def test_offline_upgrade_drops_theses_counters(section_0002: str) -> None:
    assert "ALTER TABLE theses DROP COLUMN alpha" in section_0002
    assert "ALTER TABLE theses DROP COLUMN beta" in section_0002
    assert "DROP INDEX jobs_ready" in section_0002


def test_schema_sql_is_the_v3_end_state() -> None:
    """schema.sql tracks the head, and the head is 0003 (T2.0, DECISIONS D7/D14)."""
    text = SCHEMA.read_text(encoding="utf-8")
    first_line = text.splitlines()[1]
    assert "migrations 0001+0002+0003" in first_line and "T1.8" in first_line
    for table in NEW_TABLES:
        assert f"CREATE TABLE {table} (" in text, table
    assert "CREATE VIEW patterns" in text
    # 0003 sizes the vectors; dimensionless columns cannot be indexed.
    assert f"vector({EMBED_DIM_EXPECTED})" in text
    assert "vector(" in text
    assert not re.search(r"b(alpha|beta)s+real", text) and "ALTER TABLE" not in text
    for label in SEED_LABELS:
        assert f"'{label}'" in text, label
    # No colon followed by a word character, even in comments (sa.text reads it as a bind).
    assert not re.search(r":[A-Za-z0-9_]", text)
    statements = split_sql(text)
    assert len(statements) == len(set(statements))
