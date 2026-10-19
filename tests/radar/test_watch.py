"""D110: what changed about a company since earlier runs. Synthetic runs; no network."""

from __future__ import annotations

from datetime import date, timedelta

from northvaine.core.settings import Settings
from northvaine.radar import brief
from northvaine.radar.models import RadarRun, RankedEntry
from northvaine.radar.watch import developments
from tests.radar.test_brief import NOW, UNKNOWN, candidate, claim, gate, make_run

SETTINGS = Settings(_env_file=None)


def entry(name: str = "Watched Co", **over) -> RankedEntry:
    c = candidate(name, [claim("C1", f"{name} opens a site")])
    e = brief.rank([(c, gate(), UNKNOWN)], as_of=NOW, offer="Invented offer")[0]
    return e.model_copy(update=over)


def make(days_from_now: int, entries: list[RankedEntry]) -> RadarRun:
    return make_run(1).model_copy(
        update={"as_of": NOW + timedelta(days=days_from_now), "entries": entries}
    )


def with_event(e: RankedEntry, fingerprint: str, occurred_on: date | None = None) -> RankedEntry:
    ev = e.candidate.events[0].model_copy(
        update={"fingerprint": fingerprint, "event_type": "new_import", "occurred_on": occurred_on}
    )
    c = e.candidate.model_copy(update={"events": [*e.candidate.events, ev]})
    return e.model_copy(update={"candidate": c})


def test_new_event_is_a_change() -> None:
    old = entry()
    now = with_event(old, "ev-new", date(2026, 10, 9))
    out = developments(make(5, [now]), [make(0, [old])], SETTINGS)["watched co"]
    assert out.back_in_motion
    assert out.changes == ["New since 2026-10-05: new import, on 2026-10-09"]


def test_evidence_rose() -> None:
    old = entry(evidence_level="company_fit")
    now = entry(evidence_level="explicit_purchase")
    out = developments(make(5, [now]), [make(0, [old])], SETTINGS)["watched co"]
    assert out.changes == ["Evidence rose from company fit to explicit purchase"]
    down = developments(make(5, [old]), [make(0, [now])], SETTINGS)["watched co"]
    assert not down.back_in_motion


def test_our_own_checks_are_not_motion() -> None:
    # which sites are read changes night to night, so a fit appearing is not the company moving
    out = developments(make(5, [entry(fit_level="stated")]), [make(0, [entry()])], SETTINGS)
    assert not out["watched co"].back_in_motion
    rose = developments(
        make(5, [entry(evidence_level="company_fit")]),
        [make(0, [entry(evidence_level="generic_mention")])],
        SETTINGS,
    )
    assert not rose["watched co"].back_in_motion


def imports(e: RankedEntry, fingerprint: str, codes: list[str]) -> RankedEntry:
    text = " ".join(f"The official import record states commodity {c} (an article)." for c in codes)
    ev = e.candidate.events[0].model_copy(
        update={"fingerprint": fingerprint, "event_type": "imports_recorded", "description": text}
    )
    return e.model_copy(update={"candidate": e.candidate.model_copy(update={"events": [ev]})})


def test_another_month_of_the_same_imports_is_not_news() -> None:
    old = imports(entry(), "jan-to-aug", ["68021000"])
    now = imports(entry(), "jan-to-sep", ["68021000"])  # a new month: a new fingerprint
    out = developments(make(30, [now]), [make(0, [old])], SETTINGS)["watched co"]
    assert not out.back_in_motion


def test_a_new_product_code_is_news() -> None:
    old = imports(entry(), "jan-to-aug", ["68021000"])
    now = imports(entry(), "jan-to-sep", ["68021000", "68030010"])
    out = developments(make(30, [now]), [make(0, [old])], SETTINGS)["watched co"]
    assert out.back_in_motion
    assert out.changes == [
        "New since 2026-10-05: imports a product code it did not before (68030010)"
    ]


def test_new_label() -> None:
    now = make(5, [entry(label="just_changed")])
    out = developments(now, [make(0, [entry(label="account_to_work")])], SETTINGS)
    assert out["watched co"].changes == ["Now labelled just changed"]


def test_no_change_is_only_returning() -> None:
    out = developments(make(5, [entry()]), [make(0, [entry()])], SETTINGS)["watched co"]
    assert out.changes == [] and not out.back_in_motion


def test_unseen_company_has_no_row() -> None:
    assert developments(make(5, [entry("Other Co")]), [make(0, [entry()])], SETTINGS) == {}


def test_later_run_is_ignored() -> None:
    old = entry()
    assert developments(make(0, [old]), [make(5, [with_event(old, "x")])], SETTINGS) == {}
    assert developments(make(0, [old]), [make(0, [old])], SETTINGS) == {}


def test_outside_the_window_is_ignored() -> None:
    old = entry()
    assert developments(make(200, [old]), [make(0, [old])], SETTINGS) == {}


def test_first_seen_and_seen_runs() -> None:
    e = entry()
    out = developments(make(10, [e]), [make(5, [e]), make(0, [e]), make(2, [])], SETTINGS)
    assert out["watched co"].first_seen == date(2026, 10, 5)
    assert out["watched co"].seen_runs == 2


def test_an_old_event_found_late_is_listed_but_not_motion() -> None:
    old = entry()
    now = with_event(old, "ev-late", date(2026, 7, 6))  # happened before the last look
    out = developments(make(5, [now]), [make(0, [old])], SETTINGS)["watched co"]
    assert not out.back_in_motion
    assert out.changes == ["Newly found: new import, on 2026-07-06"]
