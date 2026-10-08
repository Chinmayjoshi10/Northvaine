"""Migration 0003 (embedding dimension + llm_calls widening), rendered offline (T2.1a).

No database: `alembic upgrade head --sql` and `downgrade --sql` are rendered and read as text.
"""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from northvaine.core.standards import EMBED_DIM_EXPECTED

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "alembic.ini"
REVISION_0003 = ROOT / "migrations" / "versions" / "0003_embeddings_and_llm_calls.py"

EMBEDDING_TABLES = ("document_chunks", "event_concepts", "theses")


def render(clean_settings: None, target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    cfg = Config(str(ALEMBIC_INI), output_buffer=buffer)
    if down:
        command.downgrade(cfg, target, sql=True)
    else:
        command.upgrade(cfg, target, sql=True)
    return buffer.getvalue()


@pytest.fixture
def section_0003(clean_settings: None) -> str:
    """The part of the offline `upgrade head` script that belongs to revision 0003."""
    sql = render(clean_settings, "head")
    marker = "Running upgrade 0002 -> 0003"
    assert marker in sql, "0003 did not render; is it the head?"
    return sql.split(marker, 1)[1].split("Running upgrade 0003 -> 0004", 1)[0]


@pytest.fixture
def downgrade_0003(clean_settings: None) -> str:
    return render(clean_settings, "0003:0002", down=True)


@pytest.mark.parametrize("table", EMBEDDING_TABLES)
def test_every_embedding_column_is_sized_to_the_confirmed_dimension(
    section_0003: str, table: str
) -> None:
    expected = (
        f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({EMBED_DIM_EXPECTED})"
    )
    assert expected in section_0003, table


@pytest.mark.parametrize("table", EMBEDDING_TABLES)
def test_every_embedding_column_gets_an_hnsw_cosine_index(section_0003: str, table: str) -> None:
    """Cosine is correct because the model L2-normalizes its output (D14)."""
    pattern = re.compile(
        rf"CREATE INDEX {table}_embedding_hnsw ON {table}\s+"
        rf"USING hnsw \(embedding vector_cosine_ops\)",
        re.S,
    )
    assert pattern.search(section_0003), table


def test_the_primary_path_was_taken_not_the_halfvec_fallback(section_0003: str) -> None:
    """N <= 2000, so plain `vector` is indexable and `halfvec` is not needed (D7)."""
    assert EMBED_DIM_EXPECTED <= 2000
    assert "halfvec" not in section_0003


@pytest.mark.parametrize(
    ("column", "type_"),
    [("run_id", "uuid"), ("prompt_version", "text"), ("latency_ms", "int"), ("error", "text")],
)
def test_llm_calls_gains_the_budget_columns(section_0003: str, column: str, type_: str) -> None:
    assert f"ALTER TABLE llm_calls ADD COLUMN {column} {type_}" in section_0003


def test_llm_calls_gains_provider_with_a_default(section_0003: str) -> None:
    """D15: provenance cannot be reconstructed for rows already written."""
    assert (
        "ALTER TABLE llm_calls ADD COLUMN provider text NOT NULL DEFAULT 'nebius'"
        in section_0003
    )


@pytest.mark.parametrize(
    "index",
    [
        "CREATE INDEX llm_calls_created_at ON llm_calls (created_at)",
        "CREATE INDEX llm_calls_workspace_created ON llm_calls (workspace_id, created_at)",
    ],
)
def test_the_budget_sums_get_their_indexes(section_0003: str, index: str) -> None:
    assert index in section_0003


@pytest.mark.parametrize("table", EMBEDDING_TABLES)
def test_downgrade_restores_the_dimensionless_type(downgrade_0003: str, table: str) -> None:
    assert f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector" in downgrade_0003
    assert f"TYPE vector({EMBED_DIM_EXPECTED})" not in downgrade_0003


def test_downgrade_drops_every_index_and_column_upgrade_added(downgrade_0003: str) -> None:
    for name in (
        "llm_calls_workspace_created",
        "llm_calls_created_at",
        "theses_embedding_hnsw",
        "event_concepts_embedding_hnsw",
        "document_chunks_embedding_hnsw",
    ):
        assert f"DROP INDEX {name}" in downgrade_0003, name
    for column in ("provider", "error", "latency_ms", "prompt_version", "run_id"):
        assert f"ALTER TABLE llm_calls DROP COLUMN {column}" in downgrade_0003, column


def test_downgrade_is_the_exact_reverse_of_upgrade() -> None:
    """DOWNGRADE undoes UPGRADE in reverse order: every ALTER/CREATE has its mirror."""
    spec = importlib.util.spec_from_file_location("rev_0003", REVISION_0003)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert len(module.DOWNGRADE) == len(module.UPGRADE)
    for up, down in zip(module.UPGRADE, reversed(module.DOWNGRADE), strict=True):
        if up.startswith("CREATE INDEX"):
            name = up.split()[2]
            assert down == f"DROP INDEX {name}", up
        elif "ADD COLUMN" in up:
            table, column = up.split()[2], up.split("ADD COLUMN")[1].split()[0]
            assert down == f"ALTER TABLE {table} DROP COLUMN {column}", up
        else:  # the vector re-typings
            assert down.startswith(up.split(" TYPE ")[0] + " TYPE vector"), up
