"""SIMULATED owner study of learning loop v0 (D89). Every number it produces is simulated.

Purpose (docs/research/learning_loop_design.md section 6): exercise the loop end to end on a
recorded run and check its dynamics. Does the search budget move toward what the owner likes?
Does a noisy owner break it? It says nothing about real product performance. Reports say
SIMULATED in the title and on every number.

How it works, all offline and seeded:
- **The pool:** one replayed run. Each lead knows which searches found it (`found_by`, D87).
- **Each round:**
  1. the strategy chooses which searches "run" (Thompson, exploration floor, D89);
  2. only leads those searches found are available;
  3. the brief takes the top slots plus one exploration pick;
  4. the simulated owner rates what is shown;
  5. the posteriors are refit.
- **The owner's taste** is data (an `OwnerSpec`: liked streams, countries, requirement levels),
  never industry words in code. Noise flips a share of ratings, and some leads are "later".
- **Two references:** the same budget with searches chosen at random (the fair baseline: does
  learning choose better than chance?), and every search every round (the ceiling, with no
  budget limit).
- **Measure:** precision of the shown brief against the owner's true (noise-free) taste. It is
  averaged over seeds, and the exploration pick is excluded.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from statistics import mean

from pydantic import Field

from northvaine.core.models import FeedbackRating, LabelSource, NorthvaineModel
from northvaine.radar.brief import main_selection
from northvaine.radar.learning import (
    Beta,
    Label,
    choose_queries,
    exploration_pick,
    fit_posteriors,
    query_keys_by_ref,
)
from northvaine.radar.models import RadarRun, RankedEntry

__all__ = ["OwnerSpec", "SimReport", "load_owner", "render_report", "simulate"]


class OwnerSpec(NorthvaineModel):
    """A simulated owner's taste, as data. Empty lists mean "no preference"."""

    name: str
    streams: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    noise: float = Field(default=0.15, ge=0, le=0.5)  # share of ratings flipped
    later: float = Field(default=0.05, ge=0, le=0.5)  # share rated "later" (no fit signal)

    def likes(self, entry: RankedEntry) -> bool:
        c = entry.candidate
        return (
            (not self.streams or c.stream.value in self.streams)
            and (not self.countries or (c.country or "") in self.countries)
            and (not self.requirements or entry.requirement in self.requirements)
        )


class RoundResult(NorthvaineModel):
    round: int
    learning: float  # mean precision over seeds
    baseline: float  # same budget, searches chosen at random
    ceiling: float  # every search, every round
    searches_run: float  # mean number of searches run, learning arm


class SimReport(NorthvaineModel):
    client: str
    owner: str
    seeds: int
    rounds: list[RoundResult]
    pool: int
    liked_in_pool: int
    note: str = "SIMULATED: a test of the loop's dynamics, not a measure of product performance"


def load_owner(path: Path) -> OwnerSpec:
    return OwnerSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _entry_keys(run: RadarRun, entry: RankedEntry, by_ref: dict[str, str]) -> set[str]:
    refs = {ref for c in entry.candidate.claims for ref in run.found_by.get(str(c.document_id), [])}
    return {by_ref[r] for r in refs if r in by_ref}


def _rate(owner: OwnerSpec, entry: RankedEntry, rng: random.Random) -> FeedbackRating:
    if rng.random() < owner.later:
        return FeedbackRating.LATER
    liked = owner.likes(entry)
    if rng.random() < owner.noise:
        liked = not liked
    return FeedbackRating.GOOD if liked else FeedbackRating.NOT_RELEVANT


def _one_arm(
    run: RadarRun,
    owner: OwnerSpec,
    *,
    arm: str,  # "learning", "random" or "all"
    seed: int,
    rounds: int,
    slots: int,
    strength: float,
    keep_share: float,
    floor: float,
    min_labels: float,
) -> list[tuple[float, int]]:
    by_ref = query_keys_by_ref(run.queries)
    keys_of = {id(e): _entry_keys(run, e, by_ref) for e in run.entries}
    all_keys = sorted(set(by_ref.values()))
    source_of = {k: k.split(":", 1)[0] for k in all_keys}
    labels: list[Label] = []
    out: list[tuple[float, int]] = []
    for r in range(rounds):
        rng = random.Random(f"{seed}|{r}|{arm}")
        running = set(all_keys)
        keep = max(1, round(keep_share * len(all_keys)))
        if arm == "random":
            running = set(rng.sample(all_keys, keep))
        elif arm == "learning" and sum(lab.weight for lab in labels) < min_labels:
            running = set(rng.sample(all_keys, keep))  # no strategy yet: same budget, at random
        elif arm == "learning":
            post = fit_posteriors(labels, strength=strength, query_source=source_of)
            beliefs: dict[str, Beta] = {
                k: post.yields.get("query", {}).get(
                    k, post.yields.get("source", {}).get(source_of[k], post.pooled)
                )
                for k in all_keys
            }
            picked, _ = choose_queries(beliefs, keep, floor=floor, rng=rng)
            running = set(picked)
        available = [e for e in run.entries if keys_of[id(e)] & running]
        main, rest = main_selection(available, slots - 1)
        pick = exploration_pick(len(rest), rng)
        shown = main + ([rest[pick[0]]] if pick else [])
        for e in shown:
            labels.append(
                Label(
                    rating=_rate(owner, e, rng),
                    weight=1.0,
                    source=LabelSource.SIMULATED,
                    queries=tuple(sorted(keys_of[id(e)])),
                    sources=tuple(sorted({c.source_name for c in e.candidate.claims})),
                    country=e.candidate.country,
                )
            )
        precision = sum(1 for e in main if owner.likes(e)) / len(main) if main else 0.0
        out.append((precision, len(running)))
    return out


def simulate(
    run: RadarRun,
    owner: OwnerSpec,
    *,
    seeds: int = 20,
    rounds: int = 10,
    slots: int = 5,
    strength: float = 10.0,
    keep_share: float = 0.7,
    floor: float = 0.1,
    min_labels: float = 5.0,
) -> SimReport:
    """The learning arm against the no-learning baseline, round by round, averaged over seeds."""
    params = {
        "rounds": rounds,
        "slots": slots,
        "strength": strength,
        "keep_share": keep_share,
        "floor": floor,
        "min_labels": min_labels,
    }
    learning = [_one_arm(run, owner, arm="learning", seed=s, **params) for s in range(seeds)]
    baseline = [_one_arm(run, owner, arm="random", seed=s, **params) for s in range(seeds)]
    ceiling = [_one_arm(run, owner, arm="all", seed=s, **params) for s in range(seeds)]
    results = [
        RoundResult(
            round=r + 1,
            learning=round(mean(arm[r][0] for arm in learning), 3),
            baseline=round(mean(arm[r][0] for arm in baseline), 3),
            ceiling=round(mean(arm[r][0] for arm in ceiling), 3),
            searches_run=round(mean(arm[r][1] for arm in learning), 2),
        )
        for r in range(rounds)
    ]
    return SimReport(
        client=run.client_id,
        owner=owner.name,
        seeds=seeds,
        rounds=results,
        pool=len(run.entries),
        liked_in_pool=sum(1 for e in run.entries if owner.likes(e)),
    )


def render_report(report: SimReport) -> str:
    lines = [
        f"# SIMULATED learning study: {report.client}, owner '{report.owner}'",
        "",
        f"**{report.note}.** The owner is simulated, its taste is data, and every number "
        "below is SIMULATED.",
        "",
        f"- Leads in the recorded pool: {report.pool}; liked by this owner: {report.liked_in_pool}",
        f"- Seeds: {report.seeds}. Precision = share of the main brief the owner truly likes "
        "(noise-free); the exploration pick is excluded.",
        "",
        "Learning and random run the same number of searches per round; the ceiling runs all.",
        "",
        "| Round | Learning (SIMULATED) | Random, same budget (SIMULATED) "
        "| All searches (SIMULATED) | Searches run |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.rounds:
        lines.append(
            f"| {r.round} | {r.learning:.2f} | {r.baseline:.2f} | {r.ceiling:.2f} "
            f"| {r.searches_run} |"
        )
    return "\n".join(lines) + "\n"
