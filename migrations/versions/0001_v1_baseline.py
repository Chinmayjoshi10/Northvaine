"""v1 baseline: the frozen copy of schema.sql at e141b6d.

Revision ID: 0001
Revises:
Create Date: 2026-10-02

The SQL lives in migrations/sql/0001_v1_baseline.sql and must never change (its sha256 is
pinned in tests/core/test_migrations_offline.py). It runs one statement per `op.execute`,
because asyncpg cannot run several commands in one prepared statement.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

from northvaine.core.sqlsplit import split_sql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BASELINE_SQL = Path(__file__).resolve().parent.parent / "sql" / "0001_v1_baseline.sql"

# Every v1 table in creation order. The baseline creates each table after the tables it
# references, so dropping in reverse order respects every foreign key.
V1_TABLES: tuple[str, ...] = (
    "workspaces",
    "users",
    "memberships",
    "companies",
    "sources",
    "documents",
    "document_chunks",
    "claims",
    "events",
    "business_profiles",
    "products",
    "workspace_companies",
    "theses",
    "cases",
    "case_evidence",
    "contacts",
    "messages",
    "quote_requests",
    "feedback",
    "outcomes",
    "strategy_versions",
    "questions",
    "jobs",
    "llm_calls",
    "audit_log",
)


def upgrade() -> None:
    for statement in split_sql(BASELINE_SQL.read_text(encoding="utf-8")):
        op.execute(sa.text(statement))


def downgrade() -> None:
    # The vector and pgcrypto extensions stay: they are database-wide and may be shared.
    for table in reversed(V1_TABLES):
        op.execute(sa.text(f"DROP TABLE {table}"))
