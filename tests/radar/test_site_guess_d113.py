"""D113: find a company's own site by guessing the domain from its registered name."""

from __future__ import annotations

from typing import Any

from northvaine.brain.replay import LEGACY_SETTINGS
from northvaine.core.settings import Settings
from northvaine.radar import fit as fit_module
from northvaine.radar.fit import company_fit, guess_hosts, guess_own_site
from northvaine.radar.models import RankedEntry, RegisterFacts
from northvaine.sensors.base import SensorResult
from tests.radar.test_fit import NOW, SPEC, FakeFetcher, FakeSensor, entry

CFG = Settings(_env_file=None)


def company(name: str, country: str | None = "GB", number: str | None = "00123456") -> RankedEntry:
    e = entry("importer_of_record")
    reg = RegisterFacts(number=number, name=name, status="active") if number else None
    c = e.candidate.model_copy(update={"name": name, "country": country, "company_register": reg})
    return e.model_copy(update={"candidate": c})


def test_guess_order_and_tlds_for_gb() -> None:
    c = company("Brightwell Quarry Marble Ltd").candidate
    assert guess_hosts(c, CFG) == [
        "brightwellquarrymarble.co.uk",
        "brightwellquarrymarble.com",
        "brightwellquarrymarble.uk",
        "brightwellquarry.co.uk",
        "brightwellquarry.com",
        "brightwellquarry.uk",
    ]


def test_other_countries_get_com_then_cc_and_cap_applies() -> None:
    c = company("Raffalli Wegner GmbH", country="DE").candidate
    cfg = Settings(_env_file=None, radar_site_guess_per_company=20)
    hosts = guess_hosts(c, cfg)
    assert hosts[:2] == ["raffalliwegner.com", "raffalliwegner.de"]
    assert "raffalli.de" in hosts and "raffalli-wegner.com" in hosts
    assert len(guess_hosts(c, CFG)) == 6
    assert len(set(hosts)) == len(hosts)


def test_a_short_single_word_is_not_guessed_alone() -> None:
    hosts = guess_hosts(company("Zeta Alpha Ltd").candidate, CFG)
    assert "zeta.com" not in hosts and "zetaalpha.com" in hosts


def test_no_guess_from_market_or_common_words() -> None:
    market = frozenset({"granite", "paving"})
    assert guess_hosts(company("Granite Paving Ltd").candidate, CFG, market) == []
    assert guess_hosts(company("Solutions Group Ltd").candidate, CFG, market) == []
    assert guess_hosts(company("Acme Granite Ltd").candidate, CFG, market) != []


async def test_registration_number_is_accepted_with_or_without_leading_zeros() -> None:
    c = company("Brightwell Quarry Marble Ltd").candidate
    for page in ("Company no. 00123456 registered in England", "Reg 123456, England"):
        fetcher = FakeFetcher({"https://brightwellquarrymarble.co.uk/": page})
        assert await guess_own_site(c, fetcher, CFG, frozenset()) == (
            "brightwellquarrymarble.co.uk",
            "registration number",
        )


async def test_registered_name_is_accepted_and_contact_page_checked_once() -> None:
    c = company("Brightwell Quarry Marble Ltd", number=None).candidate
    calls: list[str] = []

    class Counting(FakeFetcher):
        async def fetch(self, url: str) -> Any:
            calls.append(url)
            return await super().fetch(url)

    fetcher = Counting(
        {
            "https://brightwellquarrymarble.co.uk/": "Welcome to our shop.",
            "https://brightwellquarrymarble.co.uk/contact": "Brightwell Quarry Marble, Leeds.",
        }
    )
    found = await guess_own_site(c, fetcher, CFG, frozenset())
    assert found == ("brightwellquarrymarble.co.uk", "registered name")
    assert calls.count("https://brightwellquarrymarble.co.uk/contact") == 1


async def test_a_page_without_either_proof_is_rejected() -> None:
    c = company("Brightwell Quarry Marble Ltd").candidate
    pages = {f"https://{h}/": "Some other firm, Brightwell Quarry." for h in guess_hosts(c, CFG)}
    assert await guess_own_site(c, FakeFetcher(pages), CFG, frozenset()) is None


class Names(FakeSensor):
    def __init__(self) -> None:
        super().__init__([])

    async def search(self, query: Any) -> SensorResult:
        self.queries.append(query)
        return SensorResult(documents=[], notes=[], enumerable=False)


async def test_guessed_site_skips_tavily_and_tavily_covers_the_rest(monkeypatch: Any) -> None:
    sensor = Names()
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    names = ("Alpha Works Ltd", "Bravo Works Ltd", "Delta Works Ltd")
    entries = [company(n).model_copy(update={"rank": i + 1}) for i, n in enumerate(names)]
    fetcher = FakeFetcher(
        {
            "https://bravoworks.co.uk/": (
                "Registered number 123456. We cut granite worktops for builders every day."
            )
        }
    )
    cfg = Settings(_env_file=None, radar_fit_max_accounts=1)
    out, notes = await company_fit(
        entries, SPEC, http=None, fetcher=fetcher, as_of=NOW, settings=cfg
    )
    assert [e.candidate.name for e in out] == list(names)  # order kept
    assert out[1].company_site == "bravoworks.co.uk"
    assert out[1].site_proof == "registration number"
    assert out[1].fit_level == "stated"
    assert out[0].company_site is None and out[0].site_proof is None
    assert len(sensor.queries) == 1 and sensor.queries[0].text.startswith("Alpha Works")
    assert notes[-1] == "company fit: 1 sites found free, 0 by search, 2 not found"


async def test_legacy_zero_makes_no_guess_fetches(monkeypatch: Any) -> None:
    assert LEGACY_SETTINGS["radar_site_guess_max_companies"] == 0
    sensor = Names()
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    fetched: list[str] = []

    class Recording(FakeFetcher):
        async def fetch(self, url: str) -> Any:
            fetched.append(url)
            return await super().fetch(url)

    cfg = Settings(_env_file=None, radar_site_guess_max_companies=0)
    await company_fit(
        [company("Alpha Works Ltd")], SPEC, http=None, fetcher=Recording({}), as_of=NOW,
        settings=cfg,
    )  # fmt: skip
    assert fetched == [] and len(sensor.queries) == 1


async def test_the_about_page_can_prove_the_fit(monkeypatch: Any) -> None:
    sensor = Names()
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    fetcher = FakeFetcher(
        {
            # a home page that is only a menu, and an about page that says what it does
            "https://bravoworks.co.uk/": "Registered number 123456. Home Products Contact Us",
            "https://bravoworks.co.uk/about-us": (
                "We cut granite worktops for builders and installers every working day."
            ),
        }
    )
    out, _ = await company_fit(
        [company("Bravo Works Ltd")],
        SPEC,
        http=None,
        fetcher=fetcher,
        as_of=NOW,
        settings=Settings(_env_file=None),
    )
    assert out[0].fit_level == "stated"
    assert out[0].company_fit[0].url.endswith("/about-us")
