"""Scorecard parsing and metrics (docs/EVALUATION.md). Synthetic scorecards; no network."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from northvaine.eval.scorecard import metrics, parse_scorecard

FILLED = """# Scorecard: demo (2026-10-08)

| # | Company | Stream | Correct | Relevant | New | Actionable | Failure chip |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Alpha Works | award | yes | yes | yes | yes |  |
| 2 | Beta Build | award | yes | yes | no | yes |  |
| 3 | Gamma Group | tender | yes | no | no | no | not a buyer |
| 4 | Delta Ltd | award | Y | yes | yes | yes |  |
| 5 | Unrated Co | award |  |  |  |  |  |

Wrong rejections: 1 of 6 rejected rows checked.

## After contact (the salesperson fills this in)

| # | Company | Known already? | New intelligence? | Contacted? | Outcome |
| --- | --- | --- | --- | --- | --- |
| 1 | Alpha Works | no | yes | yes | meeting |
| 2 | Beta Build | yes | yes | yes | redirect |
| 4 | Delta Ltd | no | yes | no |  |
| 5 | Unrated Co |  |  |  |  |
"""

ROOT = Path(__file__).resolve().parents[2]


def test_ratings_and_outcomes_are_parsed_and_blanks_are_not_no() -> None:
    card = parse_scorecard(FILLED, client="demo")
    assert [r.rank for r in card.ratings] == [1, 2, 3, 4, 5]
    assert card.ratings[3].correct is True  # "Y" counts as yes
    assert card.ratings[4].rated is False
    assert (card.wrong_rejections, card.rejections_checked) == (1, 6)
    assert [o.outcome for o in card.outcomes] == ["meeting", "redirect", "", ""]


def test_metrics_and_the_quality_gate() -> None:
    m = metrics(parse_scorecard(FILLED, client="demo"))
    assert m.rated == 4
    assert (m.correct_rate, m.relevant_rate, m.new_rate) == (1.0, 0.75, 0.5)
    assert m.all_four == 2 and m.passes_quality_gate is True
    assert m.wrong_rejection_rate == round(1 / 6, 3)
    assert m.failure_chips == {"not a buyer": 1}
    assert m.delivered == 3 and m.acted_on_rate == round(2 / 3, 3)
    assert m.response_rate == 1.0 and m.positive_rate == 0.5
    assert m.known_rate == round(1 / 3, 3)
    assert any("not a buyer" in n for n in m.notes)


def test_the_gate_fails_on_too_few_good_entries_or_too_many_wrong_rejections() -> None:
    m = metrics(parse_scorecard(FILLED, client="demo"), min_all_four=3)
    assert m.passes_quality_gate is False
    worse = FILLED.replace("Wrong rejections: 1 of 6", "Wrong rejections: 3 of 6")
    assert metrics(parse_scorecard(worse)).passes_quality_gate is False


def test_an_unrated_scorecard_says_so_and_has_no_verdict() -> None:
    table = FILLED.split("Wrong rejections")[0]
    blank = "\n".join(
        "| 1 | Alpha Works | award |  |  |  |  |  |" if line.startswith("| 1 |") else line
        for line in table.splitlines()
        if not line.startswith(("| 2 |", "| 3 |", "| 4 |"))
    )
    m = metrics(parse_scorecard(blank))
    assert m.rated == 0 and m.passes_quality_gate is None
    assert "not rated yet" in m.notes


def test_the_scorecard_written_by_the_brief_parses() -> None:
    from northvaine.radar.brief import render_scorecard
    from tests.radar.test_brief import make_run

    text = render_scorecard(make_run())
    card = parse_scorecard(text)
    assert card.ratings and all(not r.rated for r in card.ratings)
    # Tenders are "watch only", so they get no after-contact row; the table is still there.
    assert "## After contact" in text and card.outcomes == []


def test_eval_script_writes_a_report(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = tmp_path / "reports" / "radar" / "demo" / "2026-10-08"
    folder.mkdir(parents=True)
    (folder / "scorecard.md").write_text(FILLED, encoding="utf-8")
    assert module.main([], root=tmp_path) == 0
    written = list((tmp_path / "reports" / "eval").glob("*/eval.md"))
    assert written and "| demo | 4 | 100% | 75% |" in written[0].read_text(encoding="utf-8")


def test_a_rendered_scorecard_round_trips_even_with_a_pipe_in_a_name() -> None:
    from northvaine.radar.brief import render_scorecard
    from northvaine.radar.models import RadarStream
    from tests.radar.test_brief import make_run

    run = make_run(n_passed=1, stream=RadarStream.AWARD)
    entry = run.entries[0]
    piped = entry.model_copy(
        update={"candidate": entry.candidate.model_copy(update={"name": "A | B GmbH"})}
    )
    text = render_scorecard(run.model_copy(update={"entries": [piped]}))
    filled = "\n".join(
        line.replace("|  |  |  |  |  |", "| yes | yes | yes | yes |  |", 1)
        if line.startswith("| 1 |") and "award" in line
        else line.replace("|  |  |  |  |", "| no | yes | yes | meeting |", 1)
        if line.startswith("| 1 |")
        else line
        for line in text.splitlines()
    )
    card = parse_scorecard(filled)
    assert card.ratings[0].all_four and card.ratings[0].company.endswith("GmbH")
    assert card.outcomes[0].contacted is True and card.outcomes[0].outcome == "meeting"
