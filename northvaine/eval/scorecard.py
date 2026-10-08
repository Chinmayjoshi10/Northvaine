"""Read a filled-in radar scorecard and compute the product's quality and outcome metrics.

The scorecard is written by `radar/brief.py` and filled in by a person: the founder rates each
entry (correct, relevant, new or worth acting on, actionable, failure chip), checks the rejected
list, and the salesperson fills the "after contact" table. Pure code: no model, no network.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

__all__ = ["ContactOutcome", "EntryRating", "Metrics", "Scorecard", "metrics", "parse_scorecard"]

_YES = {"yes", "y", "true", "1", "✓", "✔"}
_NO = {"no", "n", "false", "0", "✗", "✘"}
_POSITIVE_OUTCOMES = {"requirement", "sample", "quote", "meeting", "won", "order"}
_RESPONSE_OUTCOMES = _POSITIVE_OUTCOMES | {"redirect", "info request", "info", "reply"}
_ROW = re.compile(r"^\|\s*(\d+)\s*\|")
_WRONG_REJECTIONS = re.compile(r"Wrong rejections:\s*(\d+)\s*of\s*(\d+)", re.IGNORECASE)


def _flag(cell: str) -> bool | None:
    """yes -> True, no -> False, blank or anything else -> None (not rated)."""
    value = cell.strip().casefold()
    if value in _YES:
        return True
    if value in _NO:
        return False
    return None


_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _cells(line: str) -> list[str]:
    """Split a table row on unescaped pipes only (names may carry an escaped pipe)."""
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.strip() for c in _UNESCAPED_PIPE.split(body)]


@dataclass
class EntryRating:
    rank: int
    company: str
    stream: str
    correct: bool | None
    relevant: bool | None
    new: bool | None
    actionable: bool | None
    failure_chip: str

    @property
    def rated(self) -> bool:
        return any(v is not None for v in (self.correct, self.relevant, self.new, self.actionable))

    @property
    def all_four(self) -> bool:
        return all(v is True for v in (self.correct, self.relevant, self.new, self.actionable))


@dataclass
class ContactOutcome:
    rank: int
    company: str
    known: bool | None
    new_intelligence: bool | None
    contacted: bool | None
    outcome: str


@dataclass
class Scorecard:
    client: str
    ratings: list[EntryRating] = field(default_factory=list)
    outcomes: list[ContactOutcome] = field(default_factory=list)
    wrong_rejections: int | None = None
    rejections_checked: int | None = None


def parse_scorecard(text: str, client: str = "") -> Scorecard:
    """Parse the Markdown scorecard. Unfilled cells count as not rated, never as no."""
    card = Scorecard(client=client)
    section = "ratings"
    for line in text.splitlines():
        if line.startswith("## After contact"):
            section = "outcomes"
            continue
        match = _WRONG_REJECTIONS.search(line)
        if match:
            card.wrong_rejections, card.rejections_checked = int(match[1]), int(match[2])
            continue
        if not _ROW.match(line):
            continue
        cells = _cells(line)
        if section == "ratings" and len(cells) >= 8:
            card.ratings.append(
                EntryRating(
                    rank=int(cells[0]),
                    company=cells[1],
                    stream=cells[2],
                    correct=_flag(cells[3]),
                    relevant=_flag(cells[4]),
                    new=_flag(cells[5]),
                    actionable=_flag(cells[6]),
                    failure_chip=cells[7],
                )
            )
        elif section == "outcomes" and len(cells) >= 6:
            card.outcomes.append(
                ContactOutcome(
                    rank=int(cells[0]),
                    company=cells[1],
                    known=_flag(cells[2]),
                    new_intelligence=_flag(cells[3]),
                    contacted=_flag(cells[4]),
                    outcome=cells[5].strip().casefold(),
                )
            )
    return card


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 3) if total else None


@dataclass
class Metrics:
    client: str
    rated: int
    correct_rate: float | None
    relevant_rate: float | None
    new_rate: float | None
    actionable_rate: float | None
    all_four: int
    failure_chips: dict[str, int]
    wrong_rejection_rate: float | None
    delivered: int
    known_rate: float | None
    new_intelligence_rate: float | None
    acted_on_rate: float | None
    response_rate: float | None
    positive_rate: float | None
    outcomes: dict[str, int]
    passes_quality_gate: bool | None
    notes: list[str] = field(default_factory=list)


def metrics(card: Scorecard, *, min_all_four: int = 2) -> Metrics:
    """Quality (founder ratings) and outcome (after contact) metrics for one scorecard.

    `passes_quality_gate` is the M5 go rule: at least `min_all_four` entries rated yes on all
    four questions, and at most 1 in 3 of the checked rejections wrong. None until rated."""
    rated = [r for r in card.ratings if r.rated]

    def share(attr: str) -> float | None:
        answered = [getattr(r, attr) for r in rated if getattr(r, attr) is not None]
        return _rate(sum(1 for v in answered if v), len(answered))

    all_four = sum(1 for r in rated if r.all_four)
    chips = Counter(r.failure_chip for r in rated if r.failure_chip)
    wrong = (
        _rate(card.wrong_rejections or 0, card.rejections_checked)
        if card.rejections_checked
        else None
    )
    filled = [
        o
        for o in card.outcomes
        if o.contacted is not None
        or o.known is not None
        or o.new_intelligence is not None
        or o.outcome
    ]
    contacted = [o for o in filled if o.contacted]
    known = [o.known for o in filled if o.known is not None]
    new_intel = [o.new_intelligence for o in filled if o.new_intelligence is not None]
    responses = [o for o in contacted if o.outcome in _RESPONSE_OUTCOMES]
    positives = [o for o in contacted if o.outcome in _POSITIVE_OUTCOMES]
    notes: list[str] = []
    gate: bool | None = None
    if rated:
        gate = all_four >= min_all_four and (wrong is None or wrong <= 1 / 3)
        if all_four < min_all_four:
            notes.append(f"only {all_four} entries rated yes on all four (need {min_all_four})")
        if wrong is not None and wrong > 1 / 3:
            notes.append("more than 1 in 3 of the checked rejections were wrong")
    else:
        notes.append("not rated yet")
    if chips:
        top, count = chips.most_common(1)[0]
        notes.append(f"most common failure: {top} ({count}): fix that step first")
    return Metrics(
        client=card.client,
        rated=len(rated),
        correct_rate=share("correct"),
        relevant_rate=share("relevant"),
        new_rate=share("new"),
        actionable_rate=share("actionable"),
        all_four=all_four,
        failure_chips=dict(chips.most_common()),
        wrong_rejection_rate=wrong,
        delivered=len(filled),
        known_rate=_rate(sum(1 for v in known if v), len(known)),
        new_intelligence_rate=_rate(sum(1 for v in new_intel if v), len(new_intel)),
        acted_on_rate=_rate(len(contacted), len(filled)),
        response_rate=_rate(len(responses), len(contacted)),
        positive_rate=_rate(len(positives), len(contacted)),
        outcomes=dict(Counter(o.outcome for o in filled if o.outcome).most_common()),
        passes_quality_gate=gate,
        notes=notes,
    )
