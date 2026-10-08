"""Learning loop v0 maths (D89): no database, seeded randomness."""

from __future__ import annotations

import random

from northvaine.core.models import FeedbackRating, LabelSource
from northvaine.radar.learning import (
    Beta,
    Label,
    choose_queries,
    exploration_pick,
    fit_posteriors,
    learned_score,
    pause_suggestions,
    query_key,
    thompson_shares,
    trust_region,
)

G, N, W, L = (
    FeedbackRating.GOOD,
    FeedbackRating.NOT_RELEVANT,
    FeedbackRating.WRONG_FACTS,
    FeedbackRating.LATER,
)


def lab(rating: FeedbackRating, *, q: str = "q1", src: str = "ted", country: str = "FR") -> Label:
    return Label(
        rating=rating,
        weight=1.0,
        source=LabelSource.OWNER,
        queries=(q,),
        sources=(src,),
        country=country,
    )


def test_query_key_is_stable_and_ignores_position() -> None:
    assert query_key("ted", "plaza works") == query_key("ted", "plaza works")
    assert query_key("ted", "plaza works") != query_key("fts", "plaza works")
    assert query_key("ted", "a").startswith("ted:")


def test_good_and_not_relevant_move_yields_in_opposite_directions() -> None:
    post = fit_posteriors([lab(G, country="FR")] * 4 + [lab(N, country="DE")] * 4, strength=10)
    assert post.mean("country", "FR") > post.pooled.mean > post.mean("country", "DE")


def test_wrong_facts_and_later_never_move_fit() -> None:
    base = fit_posteriors([lab(G), lab(N)], strength=10)
    noisy = fit_posteriors([lab(G), lab(N), lab(W), lab(W), lab(L), lab(L)], strength=10)
    assert noisy.mean("source", "ted") == base.mean("source", "ted")
    assert noisy.pooled == base.pooled
    # wrong facts lower source reliability only
    assert noisy.reliability["ted"].mean < base.reliability["ted"].mean


def test_a_query_shrinks_to_its_source_not_to_the_pool() -> None:
    labels = [lab(G, q="a", src="ted")] * 8 + [lab(N, q="b", src="tavily")] * 8
    labels.append(lab(G, q="new", src="ted"))
    post = fit_posteriors(labels, strength=10, query_source={"a": "ted", "new": "ted"})
    # one label on "new", but it borrows its source's high rate
    assert post.mean("query", "new") > post.pooled.mean


def test_few_labels_move_little() -> None:
    post = fit_posteriors([lab(G)], strength=10)
    assert abs(post.mean("source", "ted") - post.pooled.mean) < 0.1


def test_trust_region_limits_one_version_move() -> None:
    old = Beta(5, 5)  # mean 0.5
    new = Beta(19, 1)  # mean 0.95
    limited = trust_region(new, old, 0.25)
    assert abs(limited.mean - 0.625) < 1e-9
    assert abs(limited.n - new.n) < 1e-9
    assert trust_region(new, None, 0.25) == new


def test_thompson_prefers_the_better_query_but_never_starves_one() -> None:
    beliefs = {"good": Beta(18, 2), "bad": Beta(2, 18), "mid": Beta(5, 5)}
    shares = thompson_shares(beliefs, 1, floor=0.1, rng=random.Random(7), draws=500)
    assert shares["good"] > shares["mid"] > shares["bad"]
    assert shares["bad"] >= 0.05  # the exploration floor keeps it alive


def test_choose_queries_is_seeded_and_logs_propensities() -> None:
    beliefs = {f"q{i}": Beta(1 + i, 5) for i in range(6)}
    first = choose_queries(beliefs, 3, floor=0.1, rng=random.Random(1))
    again = choose_queries(beliefs, 3, floor=0.1, rng=random.Random(1))
    assert first == again
    chosen, props = first
    assert len(chosen) >= 3
    assert set(props) == set(beliefs)
    assert all(0 < p <= 1 for p in props.values())
    small, props_small = choose_queries({"x": Beta(1, 1)}, 3, floor=0.1, rng=random.Random(1))
    assert small == ["x"] and props_small == {"x": 1.0}


def test_exploration_pick_is_uniform_with_propensity() -> None:
    assert exploration_pick(0, random.Random(1)) is None
    picks = [exploration_pick(4, random.Random(seed)) for seed in range(400)]
    assert all(p is not None and p[1] == 0.25 for p in picks)
    seen = {p[0] for p in picks if p is not None}
    assert seen == {0, 1, 2, 3}


def test_learned_score_is_neutral_without_a_strategy() -> None:
    assert learned_score(None, ["ted"], "FR") == 0.5
    post = fit_posteriors([lab(G, country="FR")] * 6, strength=10)
    assert learned_score(post, ["ted"], "FR") > post.pooled.mean - 1e-9


def test_pause_needs_enough_labels_and_strong_evidence() -> None:
    labels = [lab(G, q="keep", src="ted")] * 10 + [lab(N, q="drop", src="ted")] * 10
    mapping = {"keep": "ted", "drop": "ted"}
    post = fit_posteriors(labels, strength=10, query_source=mapping)
    paused = pause_suggestions(
        post, query_source=mapping, min_labels=8, threshold=0.9, rng=random.Random(3)
    )
    assert paused == ["drop"]
    few = fit_posteriors(labels[:3] + labels[10:13], strength=10, query_source=mapping)
    assert (
        pause_suggestions(
            few, query_source=mapping, min_labels=8, threshold=0.9, rng=random.Random(3)
        )
        == []
    )
