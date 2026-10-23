"""D126: intent searches are written from the client's own answers, per market."""

from __future__ import annotations

from datetime import date

from northvaine.radar.intent import intent_queries
from northvaine.radar.models import ClientSpec

TODAY = date(2026, 10, 24)


def _spec(**extra: object) -> ClientSpec:
    base = {
        "id": "demo",
        "offer": "Commercial refrigeration cabinets and cold rooms",
        "markets": ["GB", "AE", "DE"],
        "offer_terms": ["refrigerated cabinets", "cold rooms"],
        "buyer_roles": ["catering equipment distributor", "kitchen fit-out contractor"],
        "need_triggers": ["new restaurant opening", "hotel kitchen refurbishment"],
        "catalogue_lines": [{"name": "Blast chillers", "terms": ["blast chillers"], "codes": []}],
        "sensors": {},
        "channel": "both",
    }
    base.update(extra)
    return ClientSpec.model_validate(base)


def test_every_market_gets_a_project_and_a_partner_search_in_the_clients_words() -> None:
    queries = intent_queries(_spec(), TODAY, 90)
    assert len(queries) == 6
    assert [q.countries for q in queries] == [["GB"], ["GB"], ["AE"], ["AE"], ["DE"], ["DE"]]
    texts = [q.text or "" for q in queries]
    assert all("refrigerated cabinets" in t for t in texts)  # the broadest own words
    assert "new restaurant opening" in texts[0] and "hotel kitchen refurbishment" in texts[2]
    assert "United Arab Emirates" in texts[2]
    # change searches only for channel partners, one change word per market
    assert all("catering equipment distributor" in t for t in texts[1::2])
    assert "kitchen fit-out contractor" not in " ".join(texts[1::2])
    assert "expansion" in texts[1] and "opens new showroom" in texts[3]
    assert all(q.published_from == date(2026, 7, 26) and q.published_to == TODAY for q in queries)


def test_a_direct_seller_gets_no_partner_search_and_old_specs_still_work() -> None:
    direct = intent_queries(_spec(channel="direct"), TODAY, 90)
    assert len(direct) == 3
    old = intent_queries(_spec(need_triggers=[], catalogue_lines=[]), TODAY, 90)
    assert old and all("new " in (q.text or "") for q in old[::2])  # role-based project search
    assert intent_queries(_spec(markets=[]), TODAY, 90) == []


def test_one_search_per_market_alternates_project_and_partner_by_day() -> None:
    today = intent_queries(_spec(), TODAY, 90, per_market=1)
    tomorrow = intent_queries(_spec(), date(2026, 10, 25), 90, per_market=1)
    assert len(today) == len(tomorrow) == 3
    for a, b in zip(today, tomorrow, strict=True):
        assert a.countries == b.countries and a.text != b.text  # the other question each day
