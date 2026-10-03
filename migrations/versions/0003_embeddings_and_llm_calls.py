"""Fix the embedding dimension and widen llm_calls for the budget guard (T2.0).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03

DECISIONS D7/D14 confirm EMBED_DIM = 1024 live against Token Factory (probe P3): the model's
native 4096-dimension output cannot be indexed by pgvector at all (limit 2,000 for `vector`,
4,000 for `halfvec`), but `dimensions=1024` returns exactly 1024 floats, L2-normalized, so a
plain HNSW `vector_cosine_ops` index is correct. `document_chunks.embedding`, `event_concepts.
embedding` and `theses.embedding` go from dimensionless `vector` to `vector(1024)` and each gets
an HNSW index. `northvaine.core.standards.EMBED_DIM_EXPECTED` is the one place this number lives;
an offline test (T2.1a) proves schema.sql, this migration and that constant agree.

`llm_calls` gains `run_id`, `prompt_version`, `latency_ms`, `error` (DECISIONS D4, D5) and
`provider` (D15) plus
indexes on `created_at` and `(workspace_id, created_at)` so the four-level budget guard's sums
(T2.3) stay cheap as the table grows.

UPGRADE and DOWNGRADE are lists of single SQL statements, each run with `op.execute(sa.text(s))`
(asyncpg cannot run several commands in one prepared statement). DOWNGRADE is the exact reverse
of UPGRADE.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE: list[str] = [
    "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024)",
    "CREATE INDEX document_chunks_embedding_hnsw ON document_chunks "
    "USING hnsw (embedding vector_cosine_ops)",
    "ALTER TABLE event_concepts ALTER COLUMN embedding TYPE vector(1024)",
    "CREATE INDEX event_concepts_embedding_hnsw ON event_concepts "
    "USING hnsw (embedding vector_cosine_ops)",
    "ALTER TABLE theses ALTER COLUMN embedding TYPE vector(1024)",
    "CREATE INDEX theses_embedding_hnsw ON theses USING hnsw (embedding vector_cosine_ops)",
    "ALTER TABLE llm_calls ADD COLUMN run_id uuid",
    "ALTER TABLE llm_calls ADD COLUMN prompt_version text",
    "ALTER TABLE llm_calls ADD COLUMN latency_ms int",
    "ALTER TABLE llm_calls ADD COLUMN error text",
    "ALTER TABLE llm_calls ADD COLUMN provider text NOT NULL DEFAULT 'nebius'",
    "CREATE INDEX llm_calls_created_at ON llm_calls (created_at)",
    "CREATE INDEX llm_calls_workspace_created ON llm_calls (workspace_id, created_at)",
]

DOWNGRADE: list[str] = [
    "DROP INDEX llm_calls_workspace_created",
    "DROP INDEX llm_calls_created_at",
    "ALTER TABLE llm_calls DROP COLUMN provider",
    "ALTER TABLE llm_calls DROP COLUMN error",
    "ALTER TABLE llm_calls DROP COLUMN latency_ms",
    "ALTER TABLE llm_calls DROP COLUMN prompt_version",
    "ALTER TABLE llm_calls DROP COLUMN run_id",
    "DROP INDEX theses_embedding_hnsw",
    "ALTER TABLE theses ALTER COLUMN embedding TYPE vector",
    "DROP INDEX event_concepts_embedding_hnsw",
    "ALTER TABLE event_concepts ALTER COLUMN embedding TYPE vector",
    "DROP INDEX document_chunks_embedding_hnsw",
    "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
