"""Concept assignment and event clustering (T4.5, D51). Thresholds are settings."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from northvaine.brain.budget import RunContext
from northvaine.core.models import (
    ClusterCandidate,
    ConceptAssignment,
    EventConceptRow,
    EventDraft,
)
from northvaine.core.settings import Settings

__all__ = ["assign_cluster", "assign_concept", "cosine", "seed_concept_embeddings"]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when either vector is all zeros."""
    raise NotImplementedError("T4.5")


def assign_concept(
    draft: EventDraft,
    embedding: Sequence[float] | None,
    concepts: list[EventConceptRow],
    *,
    settings: Settings | None = None,
) -> ConceptAssignment:
    """Level 0 from the draft's type; level 1 = nearest child at `concept_match_min_cosine`,
    else a `proposed` child named by the extractor."""
    raise NotImplementedError("T4.5")


def assign_cluster(
    new: ClusterCandidate,
    existing: list[ClusterCandidate],
    *,
    settings: Settings | None = None,
) -> UUID:
    """An existing cluster id when type, subject or group, window and cosine agree, else new."""
    raise NotImplementedError("T4.5")


async def seed_concept_embeddings(session: Any, *, run: RunContext) -> int:
    """Embed level-0 concepts that have no embedding; returns how many were written."""
    raise NotImplementedError("T4.5")
