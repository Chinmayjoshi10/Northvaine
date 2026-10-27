"""D140: a first radar reads news of the client's own triggers in every market."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from northvaine.api.onboarding import QUICK_PROFILE
from northvaine.core.settings import Settings
from northvaine.radar.intent import market_news_queries

TODAY = date(2026, 10, 28)


def _spec(triggers: list[str], markets: list[str]) -> SimpleNamespace:
    return SimpleNamespace(need_triggers=triggers, markets=markets)


def test_each_market_gets_its_trigger_as_dated_news_without_the_product_word() -> None:
    spec = _spec(["new hospitals", "new hotels", "office refits"], ["GB", "US"])
    found = market_news_queries(spec, TODAY, 90, per_market=1)
    assert [q.text for q in found] == ["new hospitals United Kingdom", "new hotels United States"]
    assert [q.countries for q in found] == [["GB"], ["US"]]
    assert all(q.published_from == date(2026, 7, 30) and q.published_to == TODAY for q in found)


def test_every_market_is_searched_once_before_any_twice_and_the_set_is_capped() -> None:
    spec = _spec(["a projects", "b projects", "c projects"], ["GB", "US", "DE", "AE"])
    found = market_news_queries(spec, TODAY, 90, per_market=2, limit=6)
    assert [q.countries[0] for q in found] == ["GB", "US", "DE", "AE", "GB", "US"]
    gb = [q.text for q in found if q.countries == ["GB"]]
    assert len(set(gb)) == 2  # two different triggers in one market


def test_no_triggers_or_no_markets_means_no_news_searches() -> None:
    assert market_news_queries(_spec([], ["GB"]), TODAY, 90, 2) == []
    assert market_news_queries(_spec(["new hotels"], []), TODAY, 90, 2) == []
    assert market_news_queries(_spec(["new hotels"], ["GB"]), TODAY, 90, 0) == []


def test_only_the_first_radar_reads_market_news_by_default() -> None:
    assert Settings(_env_file=None).radar_market_news_per_market == 0
    assert QUICK_PROFILE["radar_market_news_per_market"] >= 1
    assert QUICK_PROFILE["radar_intent_per_market"] == 2
    assert QUICK_PROFILE["radar_intent_days"] == 180
    assert QUICK_PROFILE["radar_partner_all_markets"] is True
    assert Settings(_env_file=None).radar_partner_all_markets is False


def test_a_first_radar_searches_for_distributors_in_markets_with_import_records_too() -> None:
    from northvaine.radar.intent import partner_queries
    from northvaine.radar.models import ClientSpec

    spec = ClientSpec.model_validate(
        {
            "id": "demo",
            "offer": "Products",
            "markets": ["GB", "US"],
            "offer_terms": ["products"],
            "buyer_roles": ["distributors"],
            "catalogue_lines": [],
            "sensors": {
                "hmrc": [{"kinds": ["imports_recorded"], "codes": ["hs:6802"], "countries": ["GB"]}]
            },
            "channel": "both",
        }
    )
    assert [q.countries for q in partner_queries(spec, TODAY)] == [["US"]]
    assert [q.countries for q in partner_queries(spec, TODAY, all_markets=True)] == [["GB"], ["US"]]


def test_a_first_radar_stays_small_on_the_free_server() -> None:
    from northvaine.api.onboarding import QUICK_MAX_MARKETS

    assert QUICK_MAX_MARKETS == 6
    assert QUICK_PROFILE["radar_gate_concurrency"] <= 4
    assert QUICK_PROFILE["radar_fit_concurrency"] <= 3
    assert QUICK_PROFILE["fetch_max_bytes"] <= 2_000_000
    Settings(_env_file=None).model_copy(update=QUICK_PROFILE)  # every key is a real setting
    assert set(QUICK_PROFILE) <= set(Settings.model_fields)
