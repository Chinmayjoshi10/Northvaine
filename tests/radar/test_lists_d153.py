"""D153: dealers named on peer brands' stockist pages."""

from __future__ import annotations

from datetime import UTC, datetime

from northvaine.core.settings import Settings
from northvaine.radar.lists import dealer_accounts, list_links, listed_dealers
from northvaine.radar.models import ClientSpec, UpgradedPage

SETTINGS = Settings(_env_file=None)
WORDS = ("stockist", "dealer", "where-to-buy")


def test_only_the_peers_own_list_pages_are_followed() -> None:
    links = [
        "https://acme.example/products",
        "https://acme.example/stockists",
        "https://shop.acme.example/dealer-locator",
        "https://other.example/stockists",
        "https://acme.example/where-to-buy/north",
    ]
    assert list_links(links, "acme.example", WORDS, limit=5) == [
        "https://acme.example/stockists",
        "https://shop.acme.example/dealer-locator",
        "https://acme.example/where-to-buy/north",
    ]
    assert len(list_links(links, "acme.example", WORDS, limit=1)) == 1


def test_multi_brand_dealers_first_branded_showrooms_and_social_sites_out() -> None:
    pages = {
        "acme.example": [
            [
                "https://www.tileshop.example/",
                "https://acmeworld.example/",  # acme's own branded showroom
                "https://facebook.com/acme",
                "https://solo.example/",
                "https://acme.example/contact",  # the brand itself
            ]
        ],
        "zeta.example": [["https://tileshop.example/branch", "https://zeta.example/"]],
    }
    out = listed_dealers(pages, denied=("solo.example",))
    assert [(d.domain, d.brands) for d in out] == [
        ("tileshop.example", ("acme.example", "zeta.example"))
    ]


class FakeFetcher:
    def __init__(self, pages: dict[str, list[str]]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    async def fetch(self, url: str) -> UpgradedPage:
        self.asked.append(url)
        links = self.pages.get(url)
        return UpgradedPage(
            lead_url=url,
            final_url=url,
            status=200 if links is not None else 404,
            fetched_at=datetime(2026, 11, 15, tzinfo=UTC),
            title=None,
            text="page" if links is not None else None,
            refused=None if links is not None else "http_404",
            links=links or [],
        )


async def test_dealers_become_target_accounts_with_a_country() -> None:
    spec = ClientSpec.model_validate(
        {
            "id": "demo",
            "offer": "Widgets",
            "markets": ["IN"],
            "offer_terms": ["widgets"],
            "product_codes": [],
            "sensors": {},
            "peer_sites": ["https://www.acme.example", "zeta.example"],
        }
    )
    fetcher = FakeFetcher(
        {
            "https://acme.example/": ["https://acme.example/dealers"],
            "https://acme.example/dealers": ["https://shopone.in/", "https://shoptwo.example/"],
            "https://zeta.example/": ["https://zeta.example/stockists"],
            "https://zeta.example/stockists": ["https://shopone.in/about"],
        }
    )
    accounts, listed, notes = await dealer_accounts(spec, fetcher, SETTINGS)
    # shopone.in: listed by both brands; shoptwo.example takes the client's only market
    assert [(a.name, a.country) for a in accounts] == [
        ("shopone.in", "IN"),
        ("shoptwo.example", "IN"),
    ]
    assert listed["shopone.in"].brands == ("acme.example", "zeta.example")
    assert notes[-1].endswith("2 dealer(s) to check, 1 listed by more than one brand")


async def test_no_peer_sites_means_nothing_is_fetched() -> None:
    spec = ClientSpec.model_validate(
        {"id": "d", "offer": "W", "markets": ["IN"], "offer_terms": ["w"], "sensors": {}}
    )
    fetcher = FakeFetcher({})
    assert await dealer_accounts(spec, fetcher, SETTINGS) == ([], {}, [])
    assert fetcher.asked == []


# --- D154: a stockist page that names the dealer is the proof -------------------------------


def test_the_line_naming_a_dealer_is_found_by_its_web_address() -> None:
    from northvaine.radar.lists import mention_line, name_token

    assert name_token("beersltd.co.uk") == "beers"
    text = "Find a stockist\nBeers Ltd - Truro\nE H Smith Builders Merchants\nWe love beers"
    assert mention_line(text, "beersltd.co.uk") == "Beers Ltd - Truro"
    assert mention_line(text, "ehsmith.co.uk") == "E H Smith Builders Merchants"
    assert mention_line(text, "unknown.co.uk") is None
    assert mention_line(text, "abc.co.uk") is None  # too short to tell


def test_a_named_dealer_becomes_a_candidate_quoting_the_page_and_passes_the_floor() -> None:
    from northvaine.radar.lists import Mention
    from northvaine.radar.models import TargetAccount
    from northvaine.radar.opportunity import hold_reason
    from northvaine.radar.partners import listed_candidate
    from tests.radar.test_fit import entry

    text = "Our stockists\nBeers Ltd - Truro, Cornwall\nOther Merchants"
    account = TargetAccount(name="beersltd.co.uk", country="GB", website="https://beersltd.co.uk/")
    made = listed_candidate(
        account,
        [
            Mention(
                "acme.example",
                "https://acme.example/stockists",
                text,
                "Beers Ltd - Truro, Cornwall",
            )
        ],
        datetime(2026, 11, 15, tzinfo=UTC),
        SETTINGS,
    )
    assert made is not None
    candidate, (doc, result) = made
    assert candidate.name == "Beers Ltd" and candidate.listed_by == ["acme.example"]
    claim = candidate.claims[0]
    assert claim.source_quote in doc.text and claim.url == "https://acme.example/stockists"
    assert result.checks[0].quote_offset == doc.text.index(claim.source_quote)
    # a quote that is not on the page is never a claim
    assert listed_candidate(account, [Mention("a", "u", text, "Not there")], None, SETTINGS) is None
    # the floor: a stockist listing in a client market is proof, whatever the evidence level
    spec = ClientSpec.model_validate(
        {"id": "d", "offer": "W", "markets": ["GB"], "offer_terms": ["w"], "sensors": {}}
    )
    e = entry("unresolved", candidate.stream).model_copy(
        update={"candidate": candidate, "evidence_level": "no_evidence", "requirement": "inferred"}
    )
    assert hold_reason(e, spec) is None
    other = e.model_copy(update={"candidate": candidate.model_copy(update={"country": "FR"})})
    assert hold_reason(other, spec) is not None  # still in the client's markets only
