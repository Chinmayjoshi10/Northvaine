"""Owner feedback to learning labels (D95): one rule set, unknown is never negative."""

from __future__ import annotations

from typing import Any

import pytest

from northvaine.core.models import FeedbackRating
from northvaine.radar.labels import rating_of

G, N, W = FeedbackRating.GOOD, FeedbackRating.NOT_RELEVANT, FeedbackRating.WRONG_FACTS
L = FeedbackRating.LATER


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"failure_chip": "wrong fact"}, W),
        ({"correct": False, "relevant": True, "actionable": True}, W),
        ({"outcome": "meeting"}, G),
        ({"outcome": "redirect", "relevant": False}, G),  # an outcome outranks a first opinion
        ({"accepted_for_contact": True}, G),
        ({"relevant": True, "actionable": True}, G),
        ({"failure_chip": "not a buyer"}, N),
        ({"relevant": False}, N),
        ({"relevant": True, "actionable": False}, L),  # "Not now" is timing (D100)
        ({"relevant": True, "actionable": False, "failure_chip": "not actionable"}, N),
        ({"actionable": False}, N),
        ({"known_already": True}, None),
        ({"contacted": True, "outcome": "none"}, None),  # no reply yet is unknown, not negative
        ({}, None),
    ],
)
def test_rating_of(record: dict[str, Any], expected: FeedbackRating | None) -> None:
    got = rating_of(record)
    assert (got[0] if got else None) == expected


def test_the_reason_keeps_the_closed_set_chip() -> None:
    assert rating_of({"failure_chip": "stale/closed window"}) == (N, "stale/closed window")
    assert rating_of({"outcome": "quote"}) == (G, "outcome: quote")
