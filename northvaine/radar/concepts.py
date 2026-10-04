"""Concept assignment and event clustering (T4.5, D51). Thresholds are settings."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from northvaine.brain.budget import RunContext
from northvaine.core.models import (
    SNAKE,
    ClusterCandidate,
    ConceptAssignment,
    ConceptStatus,
    EventConceptRow,
    EventDraft,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.quote_check import normalize_text

__all__ = ["assign_cluster", "assign_concept", "cosine", "seed_concept_embeddings"]

_SNAKE = re.compile(SNAKE)
_USABLE = (ConceptStatus.ACTIVE, ConceptStatus.PROPOSED)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when either vector is all zeros."""
    if len(a) != len(b):
        raise ValueError(f"vector lengths differ: {len(a)} and {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _key(value: str | None) -> str | None:
    """A comparison key: normalized and casefolded; None when empty."""
    key = normalize_text(value or "").casefold().strip()
    return key or None


def assign_concept(
    draft: EventDraft,
    embedding: Sequence[float] | None,
    concepts: list[EventConceptRow],
    *,
    settings: Settings | None = None,
) -> ConceptAssignment:
    """Level 0 from the draft's type; level 1 = nearest child at `concept_match_min_cosine`,
    else a `proposed` child named by the extractor."""
    settings = settings or get_settings()
    parent = next(
        (
            c
            for c in concepts
            if c.level == 0 and c.label == draft.event_type and c.status in _USABLE
        ),
        None,
    )
    if parent is None:
        raise ValueError(f"no level-0 concept for event type {draft.event_type!r}")

    def parent_assignment() -> ConceptAssignment:
        return ConceptAssignment(
            concept_id=parent.id,
            parent_id=parent.parent_id,
            level=parent.level,
            label=parent.label,
            description=parent.description,
            status=parent.status.value,
            is_new=False,
            embedding=parent.embedding,
        )

    if embedding is None:
        return parent_assignment()

    children = [c for c in concepts if c.parent_id == parent.id and c.status in _USABLE]
    best: EventConceptRow | None = None
    best_score = settings.concept_match_min_cosine
    for child in children:
        if child.embedding is None:
            continue
        score = cosine(embedding, child.embedding)
        if score >= best_score:
            best, best_score = child, score
    label = draft.concept_label
    if label is not None and not _SNAKE.match(label):
        label = None
    if best is None and label is not None:
        best = next((c for c in children if c.label == label), None)
    if best is not None:
        return ConceptAssignment(
            concept_id=best.id,
            parent_id=parent.id,
            level=best.level,
            label=best.label,
            description=best.description,
            status=best.status.value,
            is_new=False,
            embedding=best.embedding,
        )
    if label is None:
        return parent_assignment()
    return ConceptAssignment(
        concept_id=None,
        parent_id=parent.id,
        level=parent.level + 1,
        label=label,
        description=draft.concept_hint
        or f"A kind of {parent.label.replace('_', ' ')} event named {label.replace('_', ' ')}.",
        status=ConceptStatus.PROPOSED.value,
        is_new=True,
        embedding=list(embedding),
    )


def _within_window(a: date | None, b: date | None, days: int) -> bool:
    return a is not None and b is not None and abs((a - b).days) <= days


def _same(a: str | None, b: str | None) -> bool:
    return a is not None and a == b


def assign_cluster(
    new: ClusterCandidate,
    existing: list[ClusterCandidate],
    *,
    settings: Settings | None = None,
) -> UUID:
    """An existing cluster id when type, subject or group, window and cosine agree, else new."""
    settings = settings or get_settings()
    window = settings.event_cluster_window_days
    new_subject, new_group = _key(new.subject_key), _key(new.group_key)
    best: ClusterCandidate | None = None
    best_score = -1.0
    for other in existing:
        if other.event_type != new.event_type:
            continue
        subject_match = _same(new_subject, _key(other.subject_key))
        group_match = _same(new_group, _key(other.group_key))
        in_window = _within_window(new.occurred_on, other.occurred_on, window)
        if new.embedding is not None and other.embedding is not None:
            if not (subject_match or group_match):
                continue
            # Two undated events match only through the same group key.
            both_undated = new.occurred_on is None and other.occurred_on is None
            if not in_window and not (group_match and both_undated):
                continue
            score = cosine(new.embedding, other.embedding)
            if score < settings.event_cluster_min_cosine:
                continue
        else:
            if not (group_match or (subject_match and in_window)):
                continue
            score = 0.0
        if score > best_score:
            best, best_score = other, score
    return best.cluster_id if best is not None else uuid4()


async def seed_concept_embeddings(session: Any, *, run: RunContext) -> int:
    """Embed level-0 concepts that have no embedding; returns how many were written."""
    # Imported here: brain.llm pulls in the SDK (httpx), which importing radar must not do.
    from northvaine.brain.llm import embed
    from northvaine.core.ledger import load_concepts, set_concept_embedding

    written = 0
    for concept in await load_concepts(session, statuses=("active",)):
        if concept.level != 0 or concept.embedding is not None:
            continue
        result = await embed(
            text=f"{concept.label.replace('_', ' ')}: {concept.description}",
            purpose="concept_seed_embed",
            run=run,
            session=session,
        )
        await set_concept_embedding(session, concept.id, result.value)
        written += 1
    return written
