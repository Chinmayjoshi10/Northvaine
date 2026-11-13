"""D149: a company's country from its own web address and its own verified words."""

from __future__ import annotations

from northvaine.radar.country import (
    country_from_host,
    country_from_text,
    country_of,
    resolve_countries,
)
from northvaine.radar.models import ClientSpec, FitEvidence, RadarStream
from tests.radar.test_fit import entry

SPEC = ClientSpec.model_validate(
    {
        "id": "demo",
        "offer": "Widgets",
        "markets": ["GB", "US"],
        "offer_terms": ["widgets"],
        "product_codes": [],
        "sensors": {},
    }
)


def test_a_country_ending_names_the_country_but_a_generic_one_does_not() -> None:
    assert country_from_host("https://www.example.co.uk/about") == "GB"
    assert country_from_host("example.fr") == "FR"
    assert country_from_host("shop.example.in") == "IN"
    for generic in ("example.com", "example.io", "example.ai", "example.co", None, ""):
        assert country_from_host(generic) is None


def test_postal_addresses_and_one_named_market_in_its_own_words() -> None:
    assert country_from_text(["Visit us at 1 High Street, Leeds LS1 4AP"], ["US"]) == (
        "GB",
        "a UK postcode on its own site",
    )
    assert country_from_text(["Suite 200, Dallas, TX 75201"], ["GB"])[0] == "US"
    assert country_from_text(["Serving customers across the UK since 1990"], ["GB", "US"]) == (
        "GB",
        "its own site names the country",
    )
    # two markets named: it does not say where the company is
    assert country_from_text(["We ship to the UK and the USA"], ["GB", "US"]) is None
    # a word inside another word, or no market at all, says nothing
    assert country_from_text(["Our ukulele range"], ["GB"]) is None
    assert country_from_text(["WIN 46204 prizes"], ["GB"]) is None


def _site_entry(site: str | None, quote: str = "We stock widgets."):
    e = entry("unresolved", RadarStream.ANNOUNCEMENT)
    fits = (
        [
            FitEvidence(
                url=f"https://{site}/", quote=quote, term="widgets", level="stated", fingerprint="f"
            )
        ]
        if site
        else []
    )
    return e.model_copy(
        update={
            "company_site": site,
            "company_fit": fits,
            "candidate": e.candidate.model_copy(update={"country": None}),
        }
    )


def test_the_web_address_wins_and_the_reason_says_where_it_came_from() -> None:
    assert country_of(_site_entry("dealer.co.uk"), ["GB", "US"]) == ("GB", "its web address")
    found = country_of(_site_entry("dealer.com", "Offices in Austin, TX 78701"), ["GB", "US"])
    assert found == ("US", "a US address on its own site")
    [resolved] = resolve_countries([_site_entry("dealer.co.uk")], SPEC)
    assert resolved.candidate.country == "GB"
    assert resolved.rank_reasons[-1] == "Country: GB, from its web address"


def test_a_known_country_is_never_changed_and_an_unknown_one_stays_unknown() -> None:
    known = entry("importer_of_record")  # its record says FR
    assert resolve_countries([known], SPEC)[0] is known
    unknown = _site_entry(None)
    assert resolve_countries([unknown], SPEC)[0].candidate.country is None
