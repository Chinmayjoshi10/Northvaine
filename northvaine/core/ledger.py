"""Ledger store: the ONLY module that touches the `claims` table (T4.4, D49).

Consumers read verified claims through `verified_claims` (the SQL view). Check_invariants rules
keep SQL on `claims` and `ClaimRow` imports inside this file.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from northvaine.core.models import (
    ClaimCheck,
    ClusterCandidate,
    ConceptAssignment,
    EventConceptRow,
    NewEvent,
    VerifiedClaim,
)

__all__ = [
    "UnverifiedClaimError",
    "ensure_concept",
    "events_for_clustering",
    "load_concepts",
    "save_claims",
    "save_events",
    "set_concept_embedding",
    "verified_claims",
]


class UnverifiedClaimError(ValueError):
    """`save_events` was given a claim id that is not verified."""


async def save_claims(session: Any, checks: list[ClaimCheck]) -> dict[str, UUID]:
    """Store every check (verified or rejected) idempotently on fingerprint; returns
    fingerprint -> id."""
    raise NotImplementedError("T4.4")


async def verified_claims(
    session: Any,
    *,
    document_ids: Sequence[UUID] | None = None,
    as_of: datetime | None = None,
    workspace_id: UUID | None = None,
) -> list[VerifiedClaim]:
    """Read the `verified_claims` view: public claims plus, when given, that workspace's.
    With `as_of`, only `available_at <= as_of` (NULL excluded)."""
    raise NotImplementedError("T4.4")


async def load_concepts(
    session: Any, *, statuses: Sequence[str] = ("active", "proposed")
) -> list[EventConceptRow]:
    """The concept tree rows with one of `statuses`."""
    raise NotImplementedError("T4.4")


async def ensure_concept(session: Any, assignment: ConceptAssignment) -> UUID:
    """The id of the concept, created if new; idempotent on (parent_id, label)."""
    raise NotImplementedError("T4.4")


async def set_concept_embedding(session: Any, concept_id: UUID, embedding: Sequence[float]) -> None:
    """Store an embedding on a concept."""
    raise NotImplementedError("T4.4")


async def save_events(session: Any, events: list[NewEvent]) -> dict[str, UUID]:
    """Insert events with ON CONFLICT (fingerprint) DO NOTHING; returns fingerprint -> id.
    Raises `UnverifiedClaimError` if any claim id is not verified."""
    raise NotImplementedError("T4.4")


async def events_for_clustering(
    session: Any,
    *,
    event_type: str,
    occurred_from: date | None,
    occurred_to: date | None,
    as_of: datetime | None = None,
    limit: int = 200,
) -> list[ClusterCandidate]:
    """Recent events of one type for dedup. With `as_of`, `available_at <= as_of` and NULL
    excluded."""
    raise NotImplementedError("T4.4")
