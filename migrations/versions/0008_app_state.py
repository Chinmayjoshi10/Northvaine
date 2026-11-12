"""Durable app state (D144): onboarding sessions, trials, finished radars, feedback and each run's
response cache survive a restart or redeploy of the free server.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-06

UPGRADE and DOWNGRADE are lists of single SQL statements; DOWNGRADE is the exact reverse.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE: list[str] = [
    "CREATE TABLE app_state ("
    "kind text NOT NULL, "
    "key text NOT NULL, "
    "value bytea NOT NULL, "
    "updated_at timestamptz NOT NULL DEFAULT now(), "
    "PRIMARY KEY (kind, key))",
]

DOWNGRADE: list[str] = [
    "DROP TABLE app_state",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
