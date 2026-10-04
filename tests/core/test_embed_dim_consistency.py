"""The embedding dimension lives in exactly one place and everything else agrees (T2.1a).

`core.standards.EMBED_DIM_EXPECTED` is the single source (D7/D14). `schema.sql` and migration
0003 both carry the number as a literal, because a migration must not read settings. This is the
offline guard that catches a drifted dimension without spending a cent - and the dimension is the
one fact 0003 bakes into the database, so a drift means a re-migration, not a config change.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from northvaine.core.standards import EMBED_DIM_EXPECTED

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schema.sql"
REVISION_0003 = ROOT / "migrations" / "versions" / "0003_embeddings_and_llm_calls.py"

# pgvector index limits (docs/integrations/pgvector.md fact 8).
VECTOR_INDEX_LIMIT = 2000
HALFVEC_INDEX_LIMIT = 4000

VECTOR_TYPE = re.compile(r"\bvector\((?P<n>\d+)\)")


def dimensions_in(path: Path) -> set[int]:
    return {int(m.group("n")) for m in VECTOR_TYPE.finditer(path.read_text(encoding="utf-8"))}


def migration_sql() -> str:
    """0003's actual statements - not its docstring, which discusses halfvec and 4096."""
    spec = importlib.util.spec_from_file_location("rev_0003_dim", REVISION_0003)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return "\n".join([*module.UPGRADE, *module.DOWNGRADE])


def test_schema_sql_uses_exactly_one_dimension_and_it_is_the_constant() -> None:
    found = dimensions_in(SCHEMA)
    assert found, "schema.sql has no sized vector column"
    assert found == {EMBED_DIM_EXPECTED}, found


def test_migration_0003_uses_exactly_one_dimension_and_it_is_the_constant() -> None:
    found = dimensions_in(REVISION_0003)
    assert found, "migration 0003 has no sized vector column"
    assert found == {EMBED_DIM_EXPECTED}, found


def test_all_three_sources_agree() -> None:
    assert dimensions_in(SCHEMA) == dimensions_in(REVISION_0003) == {EMBED_DIM_EXPECTED}


def test_the_dimension_is_indexable_by_pgvector() -> None:
    """N > 4000 cannot be indexed at all; N > 2000 would need the halfvec fallback."""
    assert EMBED_DIM_EXPECTED <= HALFVEC_INDEX_LIMIT, (
        f"{EMBED_DIM_EXPECTED} exceeds pgvector's halfvec index limit; re-probe with a smaller "
        "`dimensions` value (D7)."
    )
    sql = migration_sql()
    if EMBED_DIM_EXPECTED > VECTOR_INDEX_LIMIT:  # pragma: no cover - fallback path
        assert "halfvec_cosine_ops" in sql, (
            "2000 < N <= 4000 requires the halfvec expression index fallback (D7)"
        )
    else:
        assert "halfvec" not in sql, "primary path taken, so no halfvec index is expected"


def test_the_primary_path_uses_plain_hnsw_cosine() -> None:
    sql = migration_sql()
    assert "vector_cosine_ops" in sql
    assert sql.count("USING hnsw") == 3


@pytest.mark.parametrize("value", [0, -1, 4096, 8192])
def test_the_constant_is_a_plausible_dimension(value: int) -> None:
    """Guards against someone 'fixing' a failure by typing the native 4096 back in."""
    assert value != EMBED_DIM_EXPECTED
    assert EMBED_DIM_EXPECTED > 0


REVISION_0005 = ROOT / "migrations" / "versions" / "0005_evidence_ledger.py"


def test_migration_0005_uses_exactly_one_dimension_and_it_is_the_constant() -> None:
    """events.embedding is sized in 0005 with a literal, like 0003 (migrations read no settings)."""
    found = dimensions_in(REVISION_0005)
    assert found, "migration 0005 has no sized vector column"
    assert found == {EMBED_DIM_EXPECTED}, found
