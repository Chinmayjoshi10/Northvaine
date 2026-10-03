"""Link TED notices of one procedure and measure their timeline (T3.4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from pydantic import Field

from northvaine.core.models import EventType, NorthvaineModel
from northvaine.core.settings import get_settings
from northvaine.sensors.base import DateFlag, SensorDocument
from northvaine.sensors.dates import parse_date, validate_notice_dates


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
    """Group documents by `group_key` (the TED procedure-identifier), keeping input order.
    Documents with no group_key cannot be linked and are left out."""
    groups: dict[str, list[SensorDocument]] = {}
    for doc in docs:
        if doc.group_key:
            groups.setdefault(doc.group_key, []).append(doc)
    return groups


def _dates(doc: SensorDocument, key: str) -> list[date]:
    return [d for d in (parse_date(v) for v in doc.meta.get(key, [])) if d is not None]


def _days(later: date | None, earlier: date | None) -> int | None:
    return (later - earlier).days if later is not None and earlier is not None else None


def procedure_timeline(docs: Sequence[SensorDocument]) -> ProcedureTimeline:
    """The timeline of one procedure from its notices (D28).

    Tender side (notice_kind 'tender_published'): earliest publication, latest deadline.
    Award side ('contract_awarded'): earliest publication, latest winner decision. A side with
    no notice (earlier notices may no longer be searchable) leaves its dates and intervals
    None, without a flag. Intervals may be negative: that is the data, flagged not corrected.
    Raises ValueError for no documents or documents of different procedures.
    """
    keys = {d.group_key for d in docs}
    if not docs or len(keys) != 1 or None in keys:
        raise ValueError("procedure_timeline needs one or more documents of a single procedure")
    group_key = str(next(iter(keys)))
    tenders = [d for d in docs if d.meta.get("notice_kind") == EventType.TENDER_PUBLISHED.value]
    awards = [d for d in docs if d.meta.get("notice_kind") == EventType.CONTRACT_AWARDED.value]

    tender_on = min((d.published_on for d in tenders if d.published_on), default=None)
    award_on = min((d.published_on for d in awards if d.published_on), default=None)
    deadline = max((x for d in tenders for x in _dates(d, "deadlines")), default=None)
    decision = max((x for d in awards for x in _dates(d, "winner_decision_dates")), default=None)

    flags: list[DateFlag] = [f for d in docs for f in d.date_flags]
    extreme = get_settings().ted_extreme_lag_days
    if tender_on is not None:
        flags += validate_notice_dates(
            tender_on, [deadline] if deadline else [], [], extreme_lag_days=extreme
        )
    if award_on is not None:
        flags += validate_notice_dates(
            award_on, [], [decision] if decision else [], extreme_lag_days=extreme
        )
    return ProcedureTimeline(
        group_key=group_key,
        tender_published_on=tender_on,
        deadline=deadline,
        winner_decision_on=decision,
        award_published_on=award_on,
        tender_to_deadline_days=_days(deadline, tender_on),
        deadline_to_decision_days=_days(decision, deadline),
        decision_to_award_days=_days(award_on, decision),
        flags=list(dict.fromkeys(flags)),
    )
