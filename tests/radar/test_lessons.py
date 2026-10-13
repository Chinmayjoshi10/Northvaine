"""What each answer taught (D100): labels from files, one honest sentence per answer."""

from __future__ import annotations

from northvaine.core.settings import Settings
from northvaine.radar.lessons import learn_from_files
from northvaine.sensors.base import SensorQuery
from tests.radar.test_brief import make_run

SETTINGS = Settings(_env_file=None)


def run_with_searches():
    """Three entries; the first two found by search 1, the third by search 2."""
    run = make_run(3)
    found_by: dict[str, list[str]] = {}
    for entry in run.entries:
        ref = "tavily:1" if entry.rank <= 2 else "tavily:2"
        for c in entry.candidate.claims:
            found_by[str(c.document_id)] = [ref]
    queries = {"tavily": [SensorQuery(text="first search"), SensorQuery(text="second search")]}
    return run.model_copy(update={"queries": queries, "found_by": found_by})


def answer(rank: int, at: str, **fields) -> dict:
    return {
        "as_of": "2026-10-05",
        "rank": rank,
        "company": f"Co {rank}",
        "received_at": at,
        **fields,
    }


def test_a_take_moves_its_search_up_and_a_no_moves_it_down() -> None:
    run = run_with_searches()
    records = [
        answer(1, "2026-10-06T09:00:00Z", relevant=True, actionable=True, note="Take it"),
        answer(3, "2026-10-06T09:01:00Z", relevant=False, failure_chip="not a buyer", note="No"),
    ]
    got = learn_from_files(records, {"2026-10-05": run}, settings=SETTINGS)
    newest, oldest = got.lessons
    assert oldest.teaches == "good" and "“first search” up" in oldest.change
    assert newest.teaches == "not_relevant" and "“second search” down" in newest.change
    assert newest.said == "No · not a buyer"
    assert got.labels == 2 and not got.active  # below learning_min_labels: no run changes yet
    assert got.strategy is not None and got.strategy.labels == 2


def test_later_teaches_timing_only_and_a_changed_mind_replaces_the_answer() -> None:
    run = run_with_searches()
    records = [
        answer(1, "2026-10-06T09:00:00Z", relevant=False, note="No"),
        answer(1, "2026-10-06T10:00:00Z", relevant=True, actionable=False, note="Not now"),
    ]
    got = learn_from_files(records, {"2026-10-05": run}, settings=SETTINGS)
    assert got.answers == 1
    (only,) = got.lessons
    assert only.teaches == "later" and "timing" in only.change
    assert got.labels == 0


def test_a_wrong_fact_lowers_trust_in_the_source_and_missing_runs_are_said_plainly() -> None:
    run = run_with_searches()
    records = [
        answer(2, "2026-10-06T09:00:00Z", failure_chip="wrong fact", note="Not for us"),
        {
            **answer(1, "2026-10-06T09:05:00Z", relevant=True, actionable=True),
            "as_of": "2026-01-01",
        },
    ]
    got = learn_from_files(records, {"2026-10-05": run}, settings=SETTINGS)
    missing, wrong = got.lessons
    assert "trust example-source less" in wrong.change
    assert missing.teaches is None and "no longer on file" in missing.change


def test_enough_answers_make_the_strategy_active() -> None:
    run = run_with_searches()
    records = [
        answer(1 + i % 3, f"2026-10-06T09:0{i}:00Z", relevant=True, actionable=True)
        for i in range(3)
    ] + [
        {**answer(r, "2026-10-07T09:00:00Z", relevant=True, actionable=True), "as_of": day}
        for r, day in ((1, "2026-10-04"), (2, "2026-10-04"))
    ]
    runs = {"2026-10-05": run, "2026-10-04": run}
    got = learn_from_files(records, runs, settings=SETTINGS)
    assert got.labels == SETTINGS.learning_min_labels and got.active
