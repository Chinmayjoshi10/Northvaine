"""Graph v0 and feedback provenance: company_identifiers, links, feedback/outcome source (D88).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09

DECISIONS D88, D89.

- `company_identifiers`: one row per (scheme, value), such as a normalised name and country
  key, a registry number, an LEI or a domain. An identifier belongs to exactly one company, so
  matching reads it before any fuzzy step.
- `links`: the "connect the dots" web. Each link joins two nodes addressed by
  (kind, id): a company, an event, or a procedure (a source's own id for one buying process).
  - **Proof:** every link carries verified `claim_ids` (checked by code before insert).
  - **Derivation:** stated, related or inferred (D84). Only an inferred link has a confidence.
  - **Two times:** when the link held (`valid_from`, `valid_to`) and when it was knowable
    (`available_at`).
  - **Idempotent** on `fingerprint`.
- `feedback.source`, `feedback.weight` and `outcomes.source`: an owner, a simulated owner or a
  judge (D79, D89). A simulated label is always marked as such.

UPGRADE and DOWNGRADE are lists of single SQL statements; DOWNGRADE is the exact reverse.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE: list[str] = [
    "CREATE TABLE company_identifiers ("
    "company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE, "
    "scheme text NOT NULL CHECK (scheme ~ '^[a-z][a-z0-9_]*$'), "
    "value text NOT NULL, "
    "claim_id uuid REFERENCES claims(id), "
    "created_at timestamptz NOT NULL DEFAULT now(), "
    "PRIMARY KEY (scheme, value))",
    "CREATE INDEX company_identifiers_company ON company_identifiers (company_id)",
    "CREATE TABLE links ("
    "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
    "workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE, "
    "src_kind text NOT NULL CHECK (src_kind IN ('company','event','procedure')), "
    "src_id text NOT NULL, "
    "dst_kind text NOT NULL CHECK (dst_kind IN ('company','event','procedure')), "
    "dst_id text NOT NULL, "
    "relation text NOT NULL CHECK (relation ~ '^[a-z][a-z0-9_]*$'), "
    "derivation text NOT NULL CHECK (derivation IN ('stated','related','inferred')), "
    "claim_ids uuid[] NOT NULL, "
    "confidence real, "
    "valid_from date, "
    "valid_to date, "
    "available_at timestamptz, "
    "recorded_at timestamptz NOT NULL DEFAULT now(), "
    "details jsonb NOT NULL DEFAULT '{}', "
    "fingerprint text NOT NULL, "
    "CONSTRAINT links_fingerprint_key UNIQUE (fingerprint), "
    "CONSTRAINT links_have_claims CHECK (cardinality(claim_ids) > 0), "
    "CONSTRAINT links_confidence_when_inferred CHECK ("
    "(derivation = 'inferred') = (confidence IS NOT NULL) "
    "AND (confidence IS NULL OR (confidence > 0 AND confidence <= 1))))",
    "CREATE INDEX links_src ON links (src_kind, src_id)",
    "CREATE INDEX links_dst ON links (dst_kind, dst_id)",
    "ALTER TABLE feedback ADD COLUMN source text NOT NULL DEFAULT 'owner' "
    "CHECK (source IN ('owner','simulated','judge'))",
    "ALTER TABLE feedback ADD COLUMN weight real NOT NULL DEFAULT 1",
    "ALTER TABLE outcomes ADD COLUMN source text NOT NULL DEFAULT 'owner' "
    "CHECK (source IN ('owner','simulated','judge'))",
]

DOWNGRADE: list[str] = [
    "ALTER TABLE outcomes DROP COLUMN source",
    "ALTER TABLE feedback DROP COLUMN weight",
    "ALTER TABLE feedback DROP COLUMN source",
    "DROP INDEX links_dst",
    "DROP INDEX links_src",
    "DROP TABLE links",
    "DROP INDEX company_identifiers_company",
    "DROP TABLE company_identifiers",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
