"""Procedure linking over TED notices (T3.4)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from northvaine.sensors.base import DateFlag, SensorDocument
from northvaine.sensors.procedures import group_by_procedure, procedure_timeline
from northvaine.sensors.ted import parse_notice

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sensors" / "ted"
FETCHED = datetime(2026, 10, 4, tzinfo=UTC)
TYPES = {"tender_published": "cn-standard", "contract_awarded": "can-standard"}


def recorded_documents() -> list[SensorDocument]:
    docs = []
    for path in sorted(FIXTURES.glob("*.json")):
        for exchange in json.loads(path.read_text(encoding="utf-8")):
            for record in exchange["body_json"]["notices"]:
                docs.append(parse_notice(record, fetched_at=FETCHED))
    return docs


def synthetic(kind, number, pub, group="p1", deadlines=(), decisions=()):
    record = {
        "publication-number": number,
        "notice-type": TYPES[kind],
        "notice-version": 1,
        "procedure-identifier": group,
        "publication-date": pub,
        "deadline-receipt-request": list(deadlines),
        "winner-decision-date": list(decisions),
    }
    return parse_notice(record, fetched_at=FETCHED)


def test_recorded_cn_can_pair_of_one_procedure():
    groups = group_by_procedure(recorded_documents())
    both = {"tender_published", "contract_awarded"}
    pairs = {
        key: docs for key, docs in groups.items() if {d.meta["notice_kind"] for d in docs} >= both
    }
    assert pairs, "the recorded fixtures hold at least one cn/can pair of one procedure"
    for key, docs in pairs.items():
        timeline = procedure_timeline(docs)
        assert timeline.group_key == key
        assert timeline.tender_published_on is not None
        assert timeline.award_published_on is not None
        if timeline.deadline is not None:
            expected = (timeline.deadline - timeline.tender_published_on).days
            assert timeline.tender_to_deadline_days == expected
        if timeline.deadline and timeline.winner_decision_on:
            assert (
                timeline.deadline_to_decision_days
                == (timeline.winner_decision_on - timeline.deadline).days
            )
        if timeline.winner_decision_on:
            assert (
                timeline.decision_to_award_days
                == (timeline.award_published_on - timeline.winner_decision_on).days
            )


def test_synthetic_pair_intervals_and_no_flags():
    # Synthetic: checks the arithmetic on known dates, independent of the recordings.
    cn = synthetic(
        "tender_published", "1-2026", "2026-02-01+01:00", deadlines=["2026-03-03T12:00:00+01:00"]
    )
    can = synthetic(
        "contract_awarded", "2-2026", "2026-06-10+02:00", decisions=["2026-05-29+02:00"]
    )
    timeline = procedure_timeline([can, cn])
    assert timeline.tender_published_on == date(2026, 2, 1)
    assert timeline.deadline == date(2026, 3, 3)
    assert timeline.winner_decision_on == date(2026, 5, 29)
    assert timeline.award_published_on == date(2026, 6, 10)
    assert timeline.tender_to_deadline_days == 30
    assert timeline.deadline_to_decision_days == 87
    assert timeline.decision_to_award_days == 12
    assert timeline.flags == []


def test_flags_are_kept_and_negative_intervals_are_not_corrected():
    cn = synthetic("tender_published", "1-2026", "2026-02-01", deadlines=["2026-01-01"])
    timeline = procedure_timeline([cn])
    assert timeline.tender_to_deadline_days == -31
    assert DateFlag.DEADLINE_BEFORE_PUBLICATION in timeline.flags


def test_a_procedure_whose_tender_is_no_longer_searchable():
    can = synthetic("contract_awarded", "2-2026", "2026-06-10", decisions=["2026-05-29"])
    timeline = procedure_timeline([can])
    assert timeline.tender_published_on is None
    assert timeline.tender_to_deadline_days is None
    assert timeline.deadline_to_decision_days is None
    assert timeline.decision_to_award_days == 12
    assert timeline.flags == []


def test_group_by_procedure_keeps_order_and_skips_unlinked():
    a = synthetic("tender_published", "1-2026", "2026-02-01", group="x")
    b = synthetic("contract_awarded", "2-2026", "2026-02-02", group="y")
    c = synthetic("contract_awarded", "3-2026", "2026-02-03", group="x")
    unlinked = a.model_copy(update={"group_key": None})
    groups = group_by_procedure([a, b, c, unlinked])
    assert list(groups) == ["x", "y"]
    assert groups["x"] == [a, c]


def test_timeline_rejects_mixed_or_empty_input():
    a = synthetic("tender_published", "1-2026", "2026-02-01", group="x")
    b = synthetic("tender_published", "2-2026", "2026-02-01", group="y")
    with pytest.raises(ValueError):
        procedure_timeline([a, b])
    with pytest.raises(ValueError):
        procedure_timeline([])
