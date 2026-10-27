"""A day with nothing to act on still shows the best watch-list companies; makers are flagged."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from northvaine.api.views import _row, brief_view
from northvaine.core.settings import Settings
from northvaine.radar.models import Opportunity, RadarRun, RankedEntry
from tests.radar.test_fit import entry

TODAY = date(2026, 10, 28)


def _opp(label: str, why_now: str) -> Opportunity:
    return Opportunity(
        label=label,  # type: ignore[arg-type]
        play="account",
        intent=1,
        fit=1,
        confidence=1,
        latest=None,
        why_now=why_now,
        words="Weak intent",
    )


def _e(
    rank: int,
    label: str = "watch",
    why_now: str = "",
    site_role: str | None = None,
    passed: bool = True,
) -> RankedEntry:
    base = entry("awarded_contractor")
    cand = base.candidate.model_copy(update={"key": f"FR:co{rank}", "name": f"Company {rank}"})
    gate = base.gate.model_copy(update={"passed": passed})
    return base.model_copy(
        update={
            "rank": rank,
            "candidate": cand,
            "gate": gate,
            "site_role": site_role,
            "opportunity": _opp(label, why_now),
        }
    )


def _run(entries: list[RankedEntry]) -> RadarRun:
    return RadarRun(
        client_id="demo_client",
        offer="Invented offer",
        as_of=datetime(2026, 10, 28, 9, 0, tzinfo=UTC),
        queries={},
        documents_by_kind={},
        leads=len(entries),
        upgraded=[],
        entries=entries,
        rejected=[],
        llm_calls=0,
        cost_usd=Decimal("0"),
        notes=[],
    )


def _view(entries: list[RankedEntry]):  # type: ignore[no-untyped-def]
    return brief_view(_run(entries), Settings(_env_file=None))


def test_empty_edition_shows_up_to_three_watch_ranks_dated_first() -> None:
    entries = [
        _e(1),
        _e(2, why_now="Imported stone on 2026-10-01"),
        _e(3),
        _e(4, why_now="Renamed on 2026-09-20"),
        _e(5, why_now="New owner on 2026-09-01"),
    ]
    view = _view(entries)
    assert view.edition == []
    assert view.watch_best == [2, 4, 5]


def test_makers_and_failed_gates_are_left_out() -> None:
    entries = [
        _e(1, site_role="makes", why_now="Dated reason"),
        _e(2, passed=False, why_now="Dated reason"),
        _e(3, site_role="resells"),
        _e(4),
    ]
    assert _view(entries).watch_best == [3, 4]


def test_a_day_with_an_edition_has_no_watch_best() -> None:
    view = _view([_e(1, label="approach_now", why_now="Won a contract"), _e(2)])
    assert view.edition
    assert view.watch_best == []


def test_possible_competitor_follows_the_site_role() -> None:
    assert _row(_e(1, site_role="makes"), TODAY).possible_competitor is True
    assert _row(_e(1, site_role="resells"), TODAY).possible_competitor is False
    assert _row(_e(1), TODAY).possible_competitor is False
