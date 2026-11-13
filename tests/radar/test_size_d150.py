"""D150: size from a company's own sentences; the plan's table of 20 sentences, with negatives."""

from __future__ import annotations

import pytest

from northvaine.radar.size import best_size, size_facts

CASES = [
    # (sentence, expected tier, expected words) ; tier 0 = no size fact
    ("We operate 24 branches across the country.", 3, "24 branches"),
    ("With over 300 employees we serve the trade.", 3, "300 employees"),
    ("More than 1,200 staff work in our depots.", 3, "1,200 staff"),
    ("Visit one of our 15 showrooms.", 3, "15 showrooms"),
    ("We have 5 retail stores in the region.", 2, "5 stores"),
    ("Our 3 warehouses hold stock for next-day delivery.", 2, "3 warehouses"),
    ("A team of 80 people.", 2, "80 people"),
    ("We now have 2 offices.", 1, "2 offices"),
    ("Around 35 employees.", 1, "35 employees"),
    ("A family business with 400+ team members.", 3, "400+ team members"),
    ("Nearly 60 distribution centres worldwide.", 3, "60 distribution centres"),
    # negatives: years, ratings, percentages, prices, product counts, a single place
    ("Over 100 years of experience in the trade.", 0, None),
    ("Rated 5 stars by our customers.", 0, None),
    ("Save 20% on all orders this month.", 0, None),
    ("Prices from 499 pounds.", 0, None),
    ("Choose from over 500 products in stock.", 0, None),
    ("Our 1 showroom is open daily.", 0, None),
    ("Established in 1985 in Leeds.", 0, None),
    ("Call 0800 123 456 for a quote.", 0, None),
    ("We delivered 40 projects last year.", 0, None),
]


@pytest.mark.parametrize(("sentence", "tier", "words"), CASES)
def test_the_size_table(sentence: str, tier: int, words: str | None) -> None:
    facts = size_facts(sentence)
    if tier == 0:
        assert facts == []
    else:
        assert facts and facts[0].tier == tier and facts[0].words == words
        assert facts[0].sentence == sentence  # the quote is the page's own sentence


def test_the_strongest_fact_over_several_pages_wins() -> None:
    best = best_size(["We have 2 offices.", "Home page.", "Our 12 branches stock everything."])
    assert best is not None and best.tier == 3 and best.words == "12 branches"
    assert best_size(["Nothing about size here."]) is None
