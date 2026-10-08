"""Owner feedback to learning labels (D95): the outcome data contract.

The web app stores each answer as a structured record (`api/feedback.py`, JSON lines): the
scorecard questions, a closed-set failure reason, and the after-contact fields (known already,
new intelligence, accepted for contact, contacted, outcome). Nothing is parsed from Markdown.

`rating_of` maps one record to what it teaches, using one rule set:

| Answer | Rating |
| --- | --- |
| failure reason "wrong fact", or correct = no | `wrong_facts` (source reliability only) |
| a positive outcome (redirect, info request, requirement, sample, quote, meeting) | `good` |
| accepted for contact, or relevant and actionable | `good` |
| any other failure reason, or relevant = no, or actionable = no | `not_relevant` |
| anything else | no label (unknown is not negative) |

`import_feedback` writes the labels into `feedback`, linked to the run's saved cases.
It is idempotent: a record already imported is skipped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from northvaine.core.models import FeedbackRating, LabelSource

__all__ = ["POSITIVE_OUTCOMES", "cases_for_run", "import_feedback", "rating_of"]

POSITIVE_OUTCOMES = {"redirect", "info request", "requirement", "sample", "quote", "meeting"}


def rating_of(record: Mapping[str, Any]) -> tuple[FeedbackRating, str | None] | None:
    """(rating, reason) for one feedback record, or None when it teaches nothing yet."""
    chip = record.get("failure_chip")
    if chip == "wrong fact" or record.get("correct") is False:
        return FeedbackRating.WRONG_FACTS, chip or "wrong fact"
    if record.get("outcome") in POSITIVE_OUTCOMES:
        return FeedbackRating.GOOD, f"outcome: {record['outcome']}"
    if record.get("accepted_for_contact") is True or (
        record.get("relevant") is True and record.get("actionable") is True
    ):
        return FeedbackRating.GOOD, None
    if chip or record.get("relevant") is False or record.get("actionable") is False:
        return FeedbackRating.NOT_RELEVANT, chip
    return None


def _text(sql: str) -> Any:
    from sqlalchemy import text

    return text(sql)


async def import_feedback(
    session: Any,
    records: Sequence[Mapping[str, Any]],
    cases_by_rank: Mapping[int, UUID],
) -> int:
    """Write one `feedback` row per labelled record whose entry has a saved case; returns how
    many were written. A record is identified by its case and its `received_at` time, so
    importing twice writes nothing new."""
    written = 0
    for record in records:
        label = rating_of(record)
        case_id = cases_by_rank.get(int(record.get("rank", 0)))
        if label is None or case_id is None:
            continue
        received = record.get("received_at")
        when = datetime.fromisoformat(str(received)) if received else None
        result = await session.execute(
            _text(
                "INSERT INTO feedback (case_id, rating, reason, source, created_at) "
                "SELECT :case_id, :rating, :reason, :source, coalesce(:created_at, now()) "
                "WHERE NOT EXISTS (SELECT 1 FROM feedback WHERE case_id = :case_id "
                "AND created_at = :created_at)"
            ),
            {
                "case_id": case_id,
                "rating": label[0].value,
                "reason": label[1],
                "source": LabelSource.OWNER.value,
                "created_at": when,
            },
        )
        written += result.rowcount or 0
    return written


async def cases_for_run(session: Any, workspace_id: UUID, run: Any) -> dict[int, UUID]:
    """Each entry's rank mapped to its saved case (saved by `persist_run`, D86), found through
    the company's `name_country` identifier and the entry's window."""
    out: dict[int, UUID] = {}
    for entry in run.entries:
        c = entry.candidate
        found = await session.execute(
            _text(
                "SELECT cs.id FROM cases cs JOIN company_identifiers i "
                "ON i.company_id = cs.company_id AND i.scheme = 'name_country' "
                "WHERE cs.workspace_id = :w AND i.value = :key "
                "AND cs.window_start IS NOT DISTINCT FROM CAST(:start AS date) "
                "ORDER BY cs.updated_at DESC LIMIT 1"
            ),
            {"w": workspace_id, "key": c.key, "start": c.window_start},
        )
        case_id = found.scalar_one_or_none()
        if case_id is not None:
            out[entry.rank] = case_id
    return out
