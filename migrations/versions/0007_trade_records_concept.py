"""Seed the level-0 event concept for official trade records (D102).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-14

`imports_recorded`: official trade records show the company imported goods under given product
codes in a period. Evidence for it is written by code only (radar/structured.py), never by the
extractor (settings.extract_excluded_event_types).

`_SEED` has the same shape as in 0002, so `radar.run.seeded_concepts` reads both.
UPGRADE and DOWNGRADE are lists of single SQL statements; DOWNGRADE is the exact reverse.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED = (
    (
        "imports_recorded",
        "Official trade records show the company imported goods under given product codes",
    ),
)

UPGRADE: list[str] = [
    "INSERT INTO event_concepts (level, label, description) VALUES "
    + ", ".join(f"(0, '{label}', '{desc}')" for label, desc in _SEED),
]

DOWNGRADE: list[str] = [
    "DELETE FROM event_concepts WHERE level = 0 AND parent_id IS NULL AND label IN ("
    + ", ".join(f"'{label}'" for label, _desc in _SEED)
    + ")",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
