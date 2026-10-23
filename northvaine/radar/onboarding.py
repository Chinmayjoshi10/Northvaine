"""Onboarding, "Build my radar" (D105): website (+ optional catalogue) -> proposed answers -> the
person confirms them -> a client spec the radar runs on. Nothing about any industry is written
here: every word and code comes from the client's own text or the person's answers.

Trust rules:
- website and catalogue text are untrusted: contacts are stripped, text aimed at AI systems is
  removed (D85), and the text is fenced in the prompt;
- a proposed product word is kept only when it appears in that text (checked by code), so the
  radar searches for the client's own words;
- country codes must be ISO 3166-1 alpha-2; product codes must be digit strings of the right
  length (customs codes are also checked against the UK tariff by the API before they are shown);
- the person sees and can change every answer; nothing runs before they confirm.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from northvaine.brain.budget import RunContext
from northvaine.brain.fencing import Untrusted
from northvaine.brain.llm import complete_json
from northvaine.brain.prompts import load_prompt
from northvaine.core.models import ModelTier, NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import _iso3166
from northvaine.radar.discover import neutralise_steering, strip_contacts
from northvaine.radar.models import ClientSpec

__all__ = [
    "CatalogueRead",
    "IntermediaryRole",
    "OnboardingAnswers",
    "Proposal",
    "build_client_spec",
    "clean_text",
    "client_id_for",
    "intermediary_roles",
    "propose",
    "read_catalogue",
    "verify_proposal",
]

_HS = re.compile(r"^\d{6}$")
_CPV = re.compile(r"^\d{8}$")
_ROLES_FILE = Path(__file__).resolve().parent.parent / "data" / "intermediary_roles.json"


class IntermediaryRole(NorthvaineModel):
    """A kind of firm that moves, clears or stores other people's goods, with its official
    activity codes (UK SIC 2007). Offered as a pre-ticked "not a buyer" option (D114)."""

    key: str
    label: str
    sic: list[str]


@lru_cache(maxsize=1)
def intermediary_roles() -> tuple[IntermediaryRole, ...]:
    raw = json.loads(_ROLES_FILE.read_text(encoding="utf-8"))
    return tuple(IntermediaryRole.model_validate(r) for r in raw)


class ProposalOut(NorthvaineModel):
    """The model's raw proposal (checked by `verify_proposal` before anyone sees it)."""

    offer: str = Field(max_length=600)
    offer_terms: list[str] = Field(default_factory=list, max_length=20)
    related_terms: list[str] = Field(default_factory=list, max_length=10)
    markets: list[str] = Field(default_factory=list, max_length=30)
    buyer_roles: list[str] = Field(default_factory=list, max_length=8)
    need_triggers: list[str] = Field(default_factory=list, max_length=8)
    priority_lines: list[str] = Field(default_factory=list, max_length=6)
    not_buyers: list[str] = Field(default_factory=list, max_length=4)
    hs_codes: list[str] = Field(default_factory=list, max_length=8)
    cpv_codes: list[str] = Field(default_factory=list, max_length=6)
    search_phrases: list[str] = Field(default_factory=list, max_length=4)


class Proposal(ProposalOut):
    """What the person is shown: only checked items. `dropped` says what was removed and why."""

    dropped: list[str] = Field(default_factory=list)


class OnboardingAnswers(NorthvaineModel):
    """The person's confirmed answers: the only input to the client spec."""

    company: str = Field(min_length=1, max_length=200)
    website: str = Field(min_length=3, max_length=300)
    offer: str = Field(min_length=10, max_length=600)
    offer_terms: list[str] = Field(min_length=1, max_length=30)
    related_terms: list[str] = Field(default_factory=list, max_length=15)
    markets: list[str] = Field(min_length=1, max_length=30)
    buyer_roles: list[str] = Field(min_length=1, max_length=12)
    # Projects or events that make a customer need the client (one per line in the form)
    need_triggers: list[str] = Field(default_factory=list, max_length=8)
    # Product lines, most important first; each becomes a catalogue line in the spec
    priority_lines: list[str] = Field(default_factory=list, max_length=6)
    not_buyers: list[str] = Field(default_factory=list, max_length=8)
    not_buyer_roles: list[str] = Field(
        default_factory=lambda: [r.key for r in intermediary_roles()], max_length=10
    )
    hs_codes: list[str] = Field(default_factory=list, max_length=12)
    cpv_codes: list[str] = Field(default_factory=list, max_length=10)
    search_phrases: list[str] = Field(default_factory=list, max_length=6)
    existing_customers: list[str] = Field(default_factory=list, max_length=200)
    # D116: who the client sells to; new onboarding defaults to both end buyers and distributors
    channel: Literal["direct", "distributors", "both"] = "both"

    @field_validator("not_buyer_roles")
    @classmethod
    def _known_roles(cls, keys: list[str]) -> list[str]:
        known = {r.key for r in intermediary_roles()}
        bad = [k for k in keys if k not in known]
        if bad:
            raise ValueError(f"unknown not_buyer_roles: {', '.join(bad)}")
        return list(dict.fromkeys(keys))


class CatalogueRead(NorthvaineModel):
    pages: int
    chars: int
    text: str
    readable: bool  # False when the catalogue is mostly images (little text per page)


def clean_text(text: str, settings: Settings | None = None, limit: int = 15_000) -> str:
    """Untrusted page or catalogue text, made safe to show a model: contacts stripped, steering
    removed, whitespace collapsed, cut to `limit` characters."""
    settings = settings or get_settings()
    text, _ = neutralise_steering(strip_contacts(text), settings)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def read_catalogue(data: bytes, settings: Settings | None = None) -> CatalogueRead:
    """Text of a PDF catalogue (first 150 pages). A catalogue made of images yields little text;
    `readable` says so, and the radar then relies on the answers."""
    from pypdf import PdfReader  # lazy: only onboarding needs it

    reader = PdfReader(io.BytesIO(data))
    pages = reader.pages[:150]
    raw = "\n".join((page.extract_text() or "") for page in pages)
    text = clean_text(raw, settings, limit=30_000)
    readable = len(pages) > 0 and len(text) / max(len(pages), 1) >= 200
    return CatalogueRead(pages=len(reader.pages), chars=len(text), text=text, readable=readable)


def _found(term: str, haystack: str) -> bool:
    return bool(term.strip()) and term.strip().casefold() in haystack


def verify_proposal(out: ProposalOut, source_text: str) -> Proposal:
    """Keep only what code can check: product words that appear in the client's own text,
    valid country codes, well-formed product codes."""
    haystack = source_text.casefold()
    countries = _iso3166()
    dropped: list[str] = []
    terms = []
    for term in dict.fromkeys(t.strip() for t in out.offer_terms):
        if _found(term, haystack):
            terms.append(term)
        elif term:
            dropped.append(f"'{term}' is not written on the site or in the catalogue")
    markets = [m.upper() for m in dict.fromkeys(out.markets) if m.upper() in countries]
    hs = [c for c in dict.fromkeys(out.hs_codes) if _HS.match(c)]
    cpv = [c for c in dict.fromkeys(out.cpv_codes) if _CPV.match(c)]
    return Proposal(
        offer=out.offer.strip(),
        offer_terms=terms,
        related_terms=[t.strip() for t in out.related_terms if t.strip()],
        markets=markets,
        buyer_roles=[r.strip() for r in out.buyer_roles if r.strip()],
        need_triggers=[r.strip() for r in out.need_triggers if r.strip()],
        priority_lines=[r.strip() for r in out.priority_lines if r.strip()],
        not_buyers=[r.strip() for r in out.not_buyers if r.strip()],
        hs_codes=hs,
        cpv_codes=cpv,
        search_phrases=[q.strip() for q in out.search_phrases if q.strip()],
        dropped=dropped,
    )


async def propose(
    website_text: str,
    catalogue_text: str,
    *,
    run: RunContext,
    settings: Settings | None = None,
    session: Any = None,
) -> Proposal:
    """One model call over the cleaned texts, then the code checks."""
    settings = settings or get_settings()
    result = await complete_json(
        tier=ModelTier.MID,
        prompt=load_prompt("onboarding_propose", version=2),
        variables={
            "website_text": Untrusted(website_text),
            "catalogue_text": Untrusted(catalogue_text or "(none)"),
        },
        output_model=ProposalOut,
        purpose="onboarding_propose",
        run=run,
        session=session,
        max_tokens=1500,
    )
    return verify_proposal(result.value, website_text + "\n" + catalogue_text)


def client_id_for(website: str) -> str:
    """A readable client id from the website's domain: 'https://www.example.co.uk/x' ->
    'example_co_uk'."""
    host = urlsplit(website if "//" in website else f"https://{website}").hostname or website
    host = host.lower().removeprefix("www.")
    slug = re.sub(r"[^a-z0-9]+", "_", host).strip("_")
    return slug[:48] or "client"


def _catalogue_lines(answers: OnboardingAnswers) -> list[dict[str, Any]]:
    """One catalogue line per priority line, in the person's order. Its terms are the line itself
    plus the offer terms that share a word prefix with one of the line's words, either way round
    ("bench" and "benches"), case-insensitive, words of 3+ letters."""
    lines = []
    for name in dict.fromkeys(n.strip() for n in answers.priority_lines if n.strip()):
        words = name.casefold().split()
        terms = [name]
        for term in answers.offer_terms:
            if any(
                min(len(tw), len(w)) >= 3 and (tw.startswith(w) or w.startswith(tw))
                for tw in term.casefold().split()
                for w in words
            ):
                terms.append(term)
        lines.append({"name": name, "terms": list(dict.fromkeys(terms)), "codes": []})
    return lines


def build_client_spec(
    answers: OnboardingAnswers, *, client_id: str, today: date, settings: Settings | None = None
) -> ClientSpec:
    """The client spec from confirmed answers. Queries per market and source; windows end today
    (the run shifts them to its own date)."""
    settings = settings or get_settings()
    markets = [m.upper() for m in answers.markets]
    hs = [f"hs:{c}" for c in answers.hs_codes]
    cpv = [f"cpv:{c}" for c in answers.cpv_codes]
    ted_markets = [m for m in markets if m in settings.onboarding_ted_countries][:6]
    sensors: dict[str, list[dict[str, Any]]] = {}
    if "GB" in markets and hs:
        sensors["hmrc"] = [
            {
                "kinds": ["imports_recorded"],
                "codes": hs[:8],
                "countries": ["GB"],
                "published_from": date(today.year, 1, 1).isoformat(),
                "max_results": 20,
            }
        ]
    if "GB" in markets and cpv:
        sensors["fts"] = [
            {
                "kinds": ["tender_published", "contract_awarded"],
                "codes": cpv[:6],
                "countries": ["GB"],
                "published_from": (today - timedelta(days=60)).isoformat(),
                "published_to": today.isoformat(),
                "max_results": 20,
            }
        ]
    if ted_markets and cpv:
        sensors["ted"] = [
            {
                "kinds": ["tender_published"],
                "codes": cpv[:6],
                "countries": ted_markets,
                "published_from": (today - timedelta(days=45)).isoformat(),
                "published_to": today.isoformat(),
                "max_results": 10,
            },
            {
                "kinds": ["contract_awarded"],
                "codes": cpv[:6],
                "countries": ted_markets,
                "published_from": (today - timedelta(days=120)).isoformat(),
                "published_to": today.isoformat(),
                "max_results": 10,
            },
        ]
    if answers.search_phrases:
        sensors["tavily"] = [
            {
                "text": phrase,
                "languages": ["en"],
                "countries": [market],
                "published_from": (today - timedelta(days=90)).isoformat(),
                "published_to": today.isoformat(),
                "max_results": 5,
            }
            for phrase in answers.search_phrases[:3]
            for market in markets[:2]
        ][:6]
    chosen = set(answers.not_buyer_roles)
    not_buyer_codes = sorted(
        {f"sic:{code}" for role in intermediary_roles() if role.key in chosen for code in role.sic}
    )
    return ClientSpec.model_validate(
        {
            "id": client_id,
            "name": answers.company,
            "offer": answers.offer,
            "markets": markets,
            "sensors": sensors,
            "offer_terms": answers.offer_terms,
            "related_terms": answers.related_terms,
            "buyer_roles": answers.buyer_roles,
            "need_triggers": answers.need_triggers,
            "catalogue_lines": _catalogue_lines(answers),
            "not_buyers": answers.not_buyers,
            "not_buyer_codes": not_buyer_codes,
            "product_codes": [*hs, *cpv],
            "existing_customers": answers.existing_customers,
            "channel": answers.channel,
        }
    )
