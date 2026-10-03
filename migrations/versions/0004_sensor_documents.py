"""Sensor documents: external_id, group_key, meta, indexes, unique source name (T3.0a).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04

DECISIONS D40. `documents` gains `external_id` (the provider's own id), `group_key` (links
records of one thing, e.g. a TED procedure) and `meta jsonb` (structured fields; `schema_ver`
inside), with indexes on (source_id, group_key), (source_id, external_id) and (available_at).
`sources.name` becomes unique: sources stay global provider rows ('ted', 'tavily', ...).

Before `migrate` on a database that already has sources, check for duplicates:
SELECT name FROM sources GROUP BY name HAVING count(*) > 1.

UPGRADE and DOWNGRADE are lists of single SQL statements, each run with `op.execute(sa.text(s))`.
DOWNGRADE is the exact reverse of UPGRADE. No settings are read here (literals only).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE: list[str] = [
    "ALTER TABLE documents ADD COLUMN external_id text",
    "ALTER TABLE documents ADD COLUMN group_key text",
    "ALTER TABLE documents ADD COLUMN meta jsonb NOT NULL DEFAULT '{}'",
    "CREATE INDEX documents_group_key ON documents (source_id, group_key)",
    "CREATE INDEX documents_external_id ON documents (source_id, external_id)",
    "CREATE INDEX documents_available_at ON documents (available_at)",
    "ALTER TABLE sources ADD CONSTRAINT sources_name_key UNIQUE (name)",
]

DOWNGRADE: list[str] = [
    "ALTER TABLE sources DROP CONSTRAINT sources_name_key",
    "DROP INDEX documents_available_at",
    "DROP INDEX documents_external_id",
    "DROP INDEX documents_group_key",
    "ALTER TABLE documents DROP COLUMN meta",
    "ALTER TABLE documents DROP COLUMN group_key",
    "ALTER TABLE documents DROP COLUMN external_id",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
