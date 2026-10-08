"""Learning loop v0, the maths (D89). Pure functions: no database, no network, seeded randomness.

What is learned (docs/research/learning_loop_design.md section 4):
- **Yields:** for each search query, source and country, a Beta posterior over "a lead it
  found is rated good". A query shrinks to its source, a source and a country to the
  workspace's pooled rate (empirical Bayes with a stated prior strength).
- **Source reliability:** for each source, from `wrong_facts` ratings only. Wrong facts are a
  data-quality failure, never a fit failure.
- `later` is timing, not fit: it moves no yield.

How behaviour changes:
- **Searches** are chosen by Thompson sampling, with an exploration floor so that no query is
  starved by a few early labels. Each choice logs its real selection probability (propensity),
  estimated by repeated draws.
- **Ranking ties** are broken by the learned yield of a lead's sources and country. The
  deterministic order (requirement, urgency, strength) is never overridden.
- **One exploration slot:** one brief slot goes to a uniformly random eligible lead from below
  the cut, with propensity 1/m, so labels about what the cut throws away stay unbiased.
- **Pause, not delete:** a query whose good-rate is very probably below its parent's, with
  enough labels, is suggested for pausing.
- **Trust region:** one version moves a posterior mean by at most a stated relative share.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from northvaine.core.models import FeedbackRating, LabelSource

__all__ = [
    "Beta",
    "Label",
    "Posteriors",
    "choose_queries",
    "exploration_pick",
    "fit_posteriors",
    "learned_score",
    "pause_suggestions",
    "query_key",
    "query_keys_by_ref",
    "thompson_shares",
    "trust_region",
]


@dataclass(frozen=True)
class Beta:
    a: float
    b: float

    @property
    def mean(self) -> float:
        return self.a / (self.a + self.b)

    @property
    def n(self) -> float:
        return self.a + self.b

    def draw(self, rng: random.Random) -> float:
        return rng.betavariate(self.a, self.b)


@dataclass(frozen=True)
class Label:
    """One owner (or simulated) rating of a briefed lead, with what found it."""

    rating: FeedbackRating
    weight: float
    source: LabelSource
    queries: tuple[str, ...]  # query keys (see query_key)
    sources: tuple[str, ...]
    country: str | None


@dataclass
class Posteriors:
    """Every learned belief of one strategy version, by kind then key."""

    pooled: Beta
    yields: dict[str, dict[str, Beta]] = field(default_factory=dict)  # query/source/country
    reliability: dict[str, Beta] = field(default_factory=dict)  # source -> not-wrong-facts
    counts: dict[str, dict[str, float]] = field(default_factory=dict)  # labelled weight per key

    def mean(self, kind: str, key: str, default: float | None = None) -> float:
        belief = self.yields.get(kind, {}).get(key)
        if belief is not None:
            return belief.mean
        return self.pooled.mean if default is None else default


def query_key(sensor: str, text: str) -> str:
    """A stable key for one search: the sensor and a hash of its query text, so a belief
    follows the search itself, not its position in a client's list."""
    return f"{sensor}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"


def query_keys_by_ref(queries: Mapping[str, Sequence[Any]]) -> dict[str, str]:
    """Each run query ref ("sensor:index", 1-based) mapped to its stable key. A code-only query
    has no text, so it is keyed on its fixed parameters, never its dates, which shift every
    run."""
    out: dict[str, str] = {}
    for sensor, listed in queries.items():
        for index, query in enumerate(listed, start=1):
            basis = query.text or query.model_dump_json(exclude={"published_from", "published_to"})
            out[f"{sensor}:{index}"] = query_key(sensor, basis)
    return out


def _fit(good: float, bad: float, prior_mean: float, strength: float) -> Beta:
    return Beta(a=strength * prior_mean + good, b=strength * (1 - prior_mean) + bad)


def fit_posteriors(
    labels: Iterable[Label],
    *,
    strength: float,
    pooled_prior: float = 0.5,
    query_source: Mapping[str, str] | None = None,
) -> Posteriors:
    """Beta posteriors from weighted labels. Sources and countries shrink to the pooled rate;
    queries shrink to their source's posterior mean (`query_source` maps query key to source).
    """
    all_labels = list(labels)
    fit_labels = [
        lab
        for lab in all_labels
        if lab.rating in (FeedbackRating.GOOD, FeedbackRating.NOT_RELEVANT)
    ]
    good = sum(lab.weight for lab in fit_labels if lab.rating is FeedbackRating.GOOD)
    bad = sum(lab.weight for lab in fit_labels if lab.rating is FeedbackRating.NOT_RELEVANT)
    pooled = _fit(good, bad, pooled_prior, strength)

    tallies: dict[str, dict[str, list[float]]] = {"source": {}, "country": {}, "query": {}}
    for lab in fit_labels:
        hit = 1.0 if lab.rating is FeedbackRating.GOOD else 0.0
        keys = {
            "source": set(lab.sources),
            "country": {lab.country} if lab.country else set(),
            "query": set(lab.queries),
        }
        for kind, found in keys.items():
            for key in found:
                g_b = tallies[kind].setdefault(key, [0.0, 0.0])
                g_b[0] += lab.weight * hit
                g_b[1] += lab.weight * (1 - hit)

    post = Posteriors(pooled=pooled)
    for kind in ("source", "country"):
        post.yields[kind] = {
            k: _fit(g, b, pooled.mean, strength) for k, (g, b) in sorted(tallies[kind].items())
        }
        post.counts[kind] = {k: g + b for k, (g, b) in tallies[kind].items()}
    mapping = query_source or {}
    post.yields["query"] = {}
    for k, (g, b) in sorted(tallies["query"].items()):
        parent = post.yields["source"].get(mapping.get(k, ""), pooled).mean
        post.yields["query"][k] = _fit(g, b, parent, strength)
    post.counts["query"] = {k: g + b for k, (g, b) in tallies["query"].items()}

    wrong: dict[str, list[float]] = {}
    for lab in all_labels:
        for src in lab.sources:
            w_r = wrong.setdefault(src, [0.0, 0.0])
            if lab.rating is FeedbackRating.WRONG_FACTS:
                w_r[1] += lab.weight
            elif lab.rating is not FeedbackRating.LATER:
                w_r[0] += lab.weight
    post.reliability = {k: _fit(ok, bad_, 0.9, strength) for k, (ok, bad_) in sorted(wrong.items())}
    return post


def trust_region(new: Beta, old: Beta | None, max_relative_move: float) -> Beta:
    """Limit one version's move of the mean to `max_relative_move` of the old mean, keeping
    the new evidence count."""
    if old is None:
        return new
    low, high = old.mean * (1 - max_relative_move), old.mean * (1 + max_relative_move)
    mean = min(max(new.mean, low), min(high, 0.999))
    mean = max(mean, 0.001)
    return Beta(a=mean * new.n, b=(1 - mean) * new.n)


def thompson_shares(
    beliefs: Mapping[str, Beta],
    k: int,
    *,
    floor: float,
    rng: random.Random,
    draws: int = 200,
) -> dict[str, float]:
    """The probability that each key is selected by `choose_queries` (Monte Carlo)."""
    keys = sorted(beliefs)
    if not keys:
        return {}
    chosen = dict.fromkeys(keys, 0)
    for _ in range(draws):
        for key in _one_choice(beliefs, keys, k, floor, rng):
            chosen[key] += 1
    return {key: max(chosen[key] / draws, 1.0 / draws) for key in keys}


def _one_choice(
    beliefs: Mapping[str, Beta], keys: Sequence[str], k: int, floor: float, rng: random.Random
) -> list[str]:
    scored = sorted(keys, key=lambda key: (-beliefs[key].draw(rng), key))
    top = scored[:k]
    rest = [key for key in scored[k:] if rng.random() < floor]
    return sorted(top + rest)


def choose_queries(
    beliefs: Mapping[str, Beta],
    k: int,
    *,
    floor: float,
    rng: random.Random,
    draws: int = 200,
) -> tuple[list[str], dict[str, float]]:
    """One Thompson choice of at least `k` keys (every other key still has `floor` chance),
    with the selection probability of every key for the decision log."""
    keys = sorted(beliefs)
    if len(keys) <= k:
        return keys, dict.fromkeys(keys, 1.0)
    shares = thompson_shares(beliefs, k, floor=floor, rng=random.Random(rng.random()), draws=draws)
    return _one_choice(beliefs, keys, k, floor, rng), shares


def exploration_pick(eligible: int, rng: random.Random) -> tuple[int, float] | None:
    """A uniformly random index among `eligible` leads below the cut, with its propensity."""
    if eligible <= 0:
        return None
    return rng.randrange(eligible), 1.0 / eligible


def learned_score(post: Posteriors | None, sources: Iterable[str], country: str | None) -> float:
    """Tie-break score of a lead: the mean learned yield of its sources and its country.
    0.5 (neutral) with no strategy."""
    if post is None:
        return 0.5
    parts = [post.mean("source", s) for s in sorted(set(sources))]
    if country:
        parts.append(post.mean("country", country))
    return sum(parts) / len(parts) if parts else post.pooled.mean


def pause_suggestions(
    post: Posteriors,
    *,
    query_source: Mapping[str, str],
    min_labels: float,
    threshold: float,
    rng: random.Random,
    draws: int = 2000,
) -> list[str]:
    """Queries whose good-rate is below their parent's with probability > `threshold`, and
    with at least `min_labels` labelled leads. Paused, never deleted."""
    out: list[str] = []
    for key, belief in sorted(post.yields.get("query", {}).items()):
        if post.counts.get("query", {}).get(key, 0.0) < min_labels:
            continue
        parent = post.yields.get("source", {}).get(query_source.get(key, ""), post.pooled).mean
        below = sum(1 for _ in range(draws) if belief.draw(rng) < parent) / draws
        if below > threshold:
            out.append(key)
    return out
