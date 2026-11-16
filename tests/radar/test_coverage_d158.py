"""D158: where a radar has official buyer records, said before and after a run."""

from __future__ import annotations

from northvaine.radar.coverage import coverage, coverage_line
from northvaine.radar.models import ClientSpec


def _spec(markets: list[str], sensors: dict) -> ClientSpec:
    return ClientSpec.model_validate(
        {"id": "d", "offer": "W", "markets": markets, "offer_terms": ["w"], "sensors": sensors}
    )


def _q(*countries: str) -> dict:
    return {"schema_ver": 1, "kinds": [], "codes": [], "countries": list(countries)}


def test_official_records_and_web_only_markets_are_told_apart() -> None:
    spec = _spec(
        ["US", "GB", "DE", "FR"],
        {"hmrc": [_q("GB")], "ted": [_q("DE", "FR")], "tavily": [_q("US"), _q("GB")]},
    )
    official, web_only = coverage(spec)
    assert official == {
        "GB": ["import records", "company register"],
        "DE": ["EU public contracts"],
        "FR": ["EU public contracts"],
    }
    assert web_only == ["US"]  # web search is not an official record
    assert coverage_line(spec) == (
        "Official buyer records: GB (import records, company register); "
        "DE, FR (EU public contracts). "
        "Company websites and news only: US, so expect fewer proven leads there."
    )


def test_a_market_with_records_only_says_so_and_no_markets_says_nothing() -> None:
    only = _spec(["GB"], {"hmrc": [_q("GB")], "fts": [_q("GB")]})
    line = coverage_line(only)
    assert line is not None and "websites and news only" not in line
    assert coverage_line(_spec([], {})) is None
