"""Sensor contracts (T3.0a): models, validation, protocol, errors and skeleton shapes.

Skeleton tests check names, parameters and async-ness only; they never assert that a stub raises.
"""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from northvaine.core.models import EventType, SourceTier
from northvaine.sensors import base
from northvaine.sensors.base import (
    DateFlag,
    FetchBlocked,
    LeakageError,
    ReplayUnsupported,
    RobotsDisallowed,
    Sensor,
    SensorDocument,
    SensorError,
    SensorQuery,
    SensorRateLimited,
    SensorResult,
    content_hash,
)

D = date(2026, 4, 1)


def doc(**overrides: object) -> SensorDocument:
    fields: dict[str, object] = {
        "source": "ted",
        "tier": SourceTier.OFFICIAL,
        "url": "https://example.org/n/1",
        "text": "notice text",
        "content_hash": content_hash("notice text"),
        "fetched_at": datetime(2026, 4, 1, 14, 0, tzinfo=UTC),
        "published_on": D,
    }
    fields.update(overrides)
    return SensorDocument(**fields)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- SensorQuery


def test_query_defaults_and_valid_values() -> None:
    q = SensorQuery(
        kinds=[EventType.TENDER_PUBLISHED],
        codes=["cpv:45233000", "naics:238990"],
        countries=["DE", "GB"],
        languages=["en", "de"],
        published_from=date(2026, 1, 1),
        published_to=date(2026, 2, 1),
        max_results=10,
    )
    assert q.schema_ver == 1


@pytest.mark.parametrize("code", ["45233000", "cpv:", ":123", "CPV:123", "cpv:12 3"])
def test_query_rejects_a_bad_code_scheme(code: str) -> None:
    with pytest.raises(ValidationError):
        SensorQuery(codes=[code])


@pytest.mark.parametrize("country", ["de", "DEU", "ZZ", "", "G"])
def test_query_rejects_a_non_iso2_country(country: str) -> None:
    with pytest.raises(ValidationError):
        SensorQuery(countries=[country])


@pytest.mark.parametrize("language", ["EN", "eng", "zz", "e", ""])
def test_query_rejects_a_non_iso639_1_language(language: str) -> None:
    with pytest.raises(ValidationError):
        SensorQuery(languages=[language])


def test_query_rejects_published_from_after_published_to() -> None:
    with pytest.raises(ValidationError):
        SensorQuery(published_from=date(2026, 3, 2), published_to=date(2026, 3, 1))
    SensorQuery(published_from=date(2026, 3, 1), published_to=date(2026, 3, 1))


@pytest.mark.parametrize("n", [0, -1, 251, 10_000])
def test_query_rejects_max_results_outside_the_limit(n: int) -> None:
    with pytest.raises(ValidationError):
        SensorQuery(max_results=n)


@pytest.mark.parametrize("n", [1, 250])
def test_query_accepts_max_results_at_the_edges(n: int) -> None:
    assert SensorQuery(max_results=n).max_results == n


def test_query_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SensorQuery(nonsense=1)  # type: ignore[call-arg]


# ----------------------------------------------------------------------------- SensorDocument


def test_naive_fetched_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        doc(fetched_at=datetime(2026, 4, 1, 14, 0))


def test_naive_available_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        doc(available_at=datetime(2026, 4, 2, 0, 0))


@pytest.mark.parametrize("tier", [SourceTier.COMPANY, SourceTier.REPORTED])
def test_company_and_reported_available_after_fetched_is_rejected(tier: SourceTier) -> None:
    fetched = datetime(2026, 4, 1, 14, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        doc(tier=tier, fetched_at=fetched, available_at=fetched + timedelta(seconds=1))


@pytest.mark.parametrize("tier", [SourceTier.COMPANY, SourceTier.REPORTED])
def test_company_and_reported_available_at_fetched_at_is_valid(tier: SourceTier) -> None:
    fetched = datetime(2026, 4, 1, 14, 0, tzinfo=UTC)
    assert doc(tier=tier, fetched_at=fetched, available_at=fetched).available_at == fetched


def test_official_with_available_at_but_no_published_on_is_rejected() -> None:
    with pytest.raises(ValidationError):
        doc(published_on=None, available_at=datetime(2026, 4, 2, 0, 0, tzinfo=UTC))


def test_official_available_before_the_next_day_is_rejected() -> None:
    with pytest.raises(ValidationError):
        doc(available_at=datetime(2026, 4, 1, 23, 59, tzinfo=UTC))


def test_ted_notice_fetched_on_its_publication_day_is_valid() -> None:
    d = doc(
        published_on=D,
        fetched_at=datetime(2026, 4, 1, 14, 0, tzinfo=UTC),
        available_at=datetime(2026, 4, 2, 0, 0, tzinfo=UTC),
    )
    assert d.available_at > d.fetched_at


def test_official_available_exactly_at_next_midnight_utc_in_another_zone_is_valid() -> None:
    from datetime import timezone

    plus2 = timezone(timedelta(hours=2))
    assert doc(available_at=datetime(2026, 4, 2, 2, 0, tzinfo=plus2)).available_at is not None


@pytest.mark.parametrize("tier", list(SourceTier))
def test_available_at_none_is_accepted_for_any_tier(tier: SourceTier) -> None:
    assert doc(tier=tier, available_at=None).available_at is None


def test_date_flags_accept_only_date_flag_values() -> None:
    assert doc(date_flags=[DateFlag.EXTREME_LAG, "unparseable"]).date_flags == [
        DateFlag.EXTREME_LAG,
        DateFlag.UNPARSEABLE,
    ]
    with pytest.raises(ValidationError):
        doc(date_flags=["made_up"])


def test_date_flag_members() -> None:
    assert {f.value for f in DateFlag} == {
        "deadline_before_publication",
        "decision_after_publication",
        "extreme_lag",
        "missing_publication",
        "unparseable",
        "multiple_values",
        "claimed_date_untrusted",
    }


# ----------------------------------------------------------------------------- result, protocol


def test_result_carries_enumerable() -> None:
    r = SensorResult(enumerable=False)
    assert r.documents == [] and r.next_cursor is None and r.truncated is False and r.notes == []
    with pytest.raises(ValidationError):
        SensorResult()  # type: ignore[call-arg]


def test_a_conforming_class_satisfies_the_protocol() -> None:
    class Good:
        name = "x"
        tier = SourceTier.OFFICIAL
        enumerable = True

        async def search(self, query, *, as_of=None, cursor=None):
            return SensorResult(enumerable=True)

    assert isinstance(Good(), Sensor)
    assert not isinstance(object(), Sensor)


def test_error_hierarchy_and_rate_limit_payload() -> None:
    for cls in (FetchBlocked, RobotsDisallowed, SensorRateLimited, ReplayUnsupported, LeakageError):
        assert issubclass(cls, SensorError)
    assert SensorRateLimited(retry_after=3.5).retry_after == 3.5
    assert SensorRateLimited().retry_after is None
    assert base.ConfigError.__name__ == "ConfigError"


def test_content_hash_ignores_whitespace_differences_only() -> None:
    assert content_hash("a  b\n c") == content_hash("a b c")
    assert content_hash("a b c") != content_hash("a b d")
    assert len(content_hash("x")) == 64


# ----------------------------------------------------------------------------- skeleton shapes


def params(obj: object) -> list[str]:
    return list(inspect.signature(obj).parameters)  # type: ignore[arg-type]


def test_dates_signatures() -> None:
    from northvaine.sensors import dates

    assert params(dates.parse_date) == ["value"]
    assert params(dates.parse_datetime) == ["value"]
    assert params(dates.validate_notice_dates) == [
        "publication",
        "deadlines",
        "decisions",
        "extreme_lag_days",
    ]
    assert params(dates.available_at_for_publication) == ["d", "lag_days"]


def test_ted_signatures() -> None:
    from northvaine.sensors import ted

    assert params(ted.build_request) == ["query", "as_of", "page", "settings"]
    assert params(ted.render_notice_text) == ["record"]
    assert params(ted.parse_notice) == ["record", "fetched_at", "settings"]
    assert params(ted.TedSensor.__init__) == ["self", "client", "settings", "sleep"]
    assert inspect.iscoroutinefunction(ted.TedSensor.search)
    assert (ted.TedSensor.name, ted.TedSensor.tier, ted.TedSensor.enumerable) == (
        "ted",
        SourceTier.OFFICIAL,
        True,
    )


def test_tavily_signatures() -> None:
    from northvaine.sensors import tavily

    assert params(tavily.build_search_request) == ["query", "settings"]
    assert params(tavily.parse_result) == ["result", "fetched_at"]
    assert params(tavily.TavilySensor.__init__) == ["self", "client", "settings"]
    assert inspect.iscoroutinefunction(tavily.TavilySensor.search)
    assert tavily.TavilySensor.enumerable is False


def test_procedures_signatures() -> None:
    from northvaine.sensors import procedures

    assert params(procedures.group_by_procedure) == ["docs"]
    assert params(procedures.procedure_timeline) == ["docs"]
    assert set(procedures.ProcedureTimeline.model_fields) == {
        "group_key",
        "tender_published_on",
        "deadline",
        "winner_decision_on",
        "award_published_on",
        "tender_to_deadline_days",
        "deadline_to_decision_days",
        "decision_to_award_days",
        "flags",
    }


def test_fetch_signatures() -> None:
    from northvaine.sensors import fetch

    assert set(fetch.FetchedPage.model_fields) == {
        "url",
        "final_url",
        "status",
        "content_type",
        "text",
        "fetched_at",
    }
    assert params(fetch.is_public_ip) == ["addr"]
    assert params(fetch.host_denied) == ["host", "deny_hosts"]
    assert params(fetch.safe_fetch) == ["url", "client", "resolver", "settings"]
    assert inspect.iscoroutinefunction(fetch.safe_fetch)
    assert params(fetch.RobotsCache.allowed) == ["self", "url", "client", "resolver", "settings"]
    assert inspect.iscoroutinefunction(fetch.RobotsCache.allowed)


def test_html_text_signatures() -> None:
    from northvaine.sensors import html_text

    assert params(html_text.html_to_text) == ["html"]
    assert params(html_text.extract_links) == ["html", "base_url"]


def test_website_signatures() -> None:
    from northvaine.sensors import website

    cls = website.WebsiteSensor
    assert params(cls.__init__) == ["self", "client", "resolver", "settings"]
    assert params(cls.snapshot) == ["self", "url", "max_pages"]
    assert inspect.iscoroutinefunction(cls.snapshot)
    assert inspect.iscoroutinefunction(cls.search)
    assert cls.enumerable is False


def test_registry_signatures() -> None:
    from northvaine.sensors import registry

    assert registry.SENSOR_NAMES == ("ted", "tavily", "website", "fts", "usaspending")
    assert params(registry.get_sensor) == ["name", "client", "settings"]


def test_documents_signatures() -> None:
    from northvaine.core import documents

    assert set(documents.SaveResult.model_fields) == {"inserted", "unchanged"}
    assert params(documents.ensure_source) == ["session", "name", "tier"]
    assert params(documents.save_documents) == ["session", "docs", "workspace_id"]
    assert params(documents.documents_available_as_of) == [
        "session",
        "as_of",
        "source_names",
        "group_key",
        "limit",
    ]
    assert params(documents.assert_available) == ["docs", "as_of"]
    for fn in (
        documents.ensure_source,
        documents.save_documents,
        documents.documents_available_as_of,
    ):
        assert inspect.iscoroutinefunction(fn)
    assert not inspect.iscoroutinefunction(documents.assert_available)


MODULES = [
    "northvaine.sensors.base",
    "northvaine.sensors.dates",
    "northvaine.sensors.ted",
    "northvaine.sensors.tavily",
    "northvaine.sensors.procedures",
    "northvaine.sensors.fetch",
    "northvaine.sensors.html_text",
    "northvaine.sensors.website",
    "northvaine.sensors.registry",
    "northvaine.core.documents",
]


def test_every_module_imports(clean_settings: None) -> None:
    for name in MODULES:
        importlib.import_module(name)


def test_importing_the_modules_needs_no_env_and_no_network_client() -> None:
    """A clean interpreter with no env imports every module and httpx is never loaded."""
    code = (
        "import sys\n"
        + "".join(f"import {m}\n" for m in MODULES)
        + "assert 'httpx' not in sys.modules, 'httpx imported at module level'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={"PATH": "", "SYSTEMROOT": "C:\\Windows"} if sys.platform == "win32" else {},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
