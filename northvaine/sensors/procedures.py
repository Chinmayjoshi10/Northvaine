"""Link TED notices of one procedure and measure their timeline (T3.4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from pydantic import Field

from northvaine.core.models import NorthvaineModel
from northvaine.sensors.base import DateFlag, SensorDocument


class ProcedureTimeline(NorthvaineModel):
    group_key: str
    tender_published_on: date | None = None
    deadline: date | None = None
    winner_decision_on: date | None = None
    award_published_on: date | None = None
    tender_to_deadline_days: int | None = None
    deadline_to_decision_days: int | None = None
    decision_to_award_days: int | None = None
    flags: list[DateFlag] = Field(default_factory=list)


def group_by_procedure(docs: Sequence[SensorDocument]) -> dict[str, list[SensorDocument]]:
    """Group documents by `group_key` (the TED procedure-identifier). T3.4."""
    raise NotImplementedError("T3.4")


def procedure_timeline(docs: Sequence[SensorDocument]) -> ProcedureTimeline:
    """The timeline of one procedure from its notices. T3.4."""
    raise NotImplementedError("T3.4")
