"""Evidence ledger: claim status/meta/fingerprint, event fields, the verified_claims view (T4.0).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04

DECISIONS D49, D52. `claims` gains `status` (why a claim is or is not verified), `meta` and a
unique `fingerprint`, plus two table-level CHECKs that make a `verified` row without a status,
an offset or a verifier impossible. `events` gains `available_at`, `description`, `embedding`
(no index yet) and a unique `fingerprint` (event idempotency). The `verified_claims` view is the
only read path for consumers (CLAUDE.md #2).

Both `claims` and `events` are EMPTY at 0004: no code writes them. `fingerprint` is NOT NULL
without a default, so upgrade first raises a clear error if either table has rows.

UPGRADE and DOWNGRADE are lists of single SQL statements, each run with `op.execute(sa.text(s))`.
DOWNGRADE is the exact reverse of UPGRADE. No settings are read here (literals only); 1024 is
EMBED_DIM_EXPECTED (checked by tests/core/test_embed_dim_consistency.py).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE: list[str] = [
    "ALTER TABLE claims ADD COLUMN status text NOT NULL DEFAULT 'pending' "
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
]

DOWNGRADE: list[str] = [
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
]

_GUARD = (
    "DO $$ BEGIN "
    "IF EXISTS (SELECT 1 FROM claims) OR EXISTS (SELECT 1 FROM events) THEN "
    "RAISE EXCEPTION 'migration 0005 needs empty claims and events tables "
    "(fingerprint is NOT NULL with no default); empty them or backfill first'; "
    "END IF; END $$"
)


def upgrade() -> None:
    op.execute(sa.text(_GUARD))
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
