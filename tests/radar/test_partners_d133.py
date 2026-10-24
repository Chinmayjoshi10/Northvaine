"""D133: web-found partners abroad - report pages skipped, a company's own site names it."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from northvaine.core.models import EvidenceDocument
from northvaine.core.settings import Settings
from northvaine.radar.discover import _is_report_page
from northvaine.radar.entities import site_owner
from northvaine.radar.models import RadarStream
from northvaine.radar.opportunity import assess
from tests.radar.test_fit import entry
from tests.radar.test_opportunity_d125 import SPEC, TODAY, _fit, _with

CFG = Settings(_env_file=None)


def _doc(title: str, url: str, text: str) -> EvidenceDocument:
    return EvidenceDocument(
        id=uuid4(),
        source_name="tavily",
        url=url,
        title=title,
        text=text,
        available_at=datetime(2026, 10, 1),
    )


def test_market_report_and_top_ten_pages_are_skipped_but_company_pages_are_not() -> None:
    assert _is_report_page("Construction Ornamental Stone Market Size & Forecast 2030")
    assert _is_report_page("Top 10 Companies in Global Natural Stone Slab Market")
    assert not _is_report_page("Tile and Marble Installation in Saudi Arabia | AAKCM")
    assert not _is_report_page(None)


def test_a_company_own_site_names_the_company_only_when_domain_and_text_agree() -> None:
    page = _doc(
        "Tile and Marble Installation in Saudi Arabia | AAKCM",
        "https://aakcm.com/en_sa/services/tile-marble-stone-installation",
        "AAKCM installs marble and natural stone for villas and hotels across the Kingdom.",
    )
    owner = site_owner(page, CFG)
    assert owner is not None and owner.name == "AAKCM"
    other = _doc(
        "Tiles & natural stone in Vienna | Schefer GmbH",
        "https://www.steineundfliesen.at/en",
        "Schefer GmbH",
    )
    assert site_owner(other, CFG) is None  # the domain does not carry the name: no guess
    news = _doc("Hotel opens | Gulf News", "https://gulfnews.com/a", "A hotel opens.")
    assert site_owner(news, CFG) is None  # "Gulf News" never appears in the text as written


def test_a_reseller_found_abroad_is_a_partner_and_a_relationship_on_fit() -> None:
    web = _fit(
        _with(
            entry("supplier", RadarStream.ANNOUNCEMENT), key="SA:aakcm", country="SA", name="AAKCM"
        )
    )
    web = web.model_copy(update={"site_role": "resells"})
    o = assess(web, TODAY, SPEC)
    assert (o.play, o.label) == ("partner", "relationship")
