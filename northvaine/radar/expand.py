"""Local-language searches, proposed for approval (D93).

One fast-tier call per client proposes web searches and "what we sell" words in the languages
of its markets. Code then checks every item:
- the language and country were asked for;
- the item is a sensible length and has no web address;
- no text is aimed at AI systems (D85);
- it is not a duplicate.

A person approves the proposal, which never changes a client spec by itself. Searching in the
buyer's own language finds buyers who never write in English
(docs/research/lead_quality_techniques.md item 4).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from northvaine.brain.budget import RunContext
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import load_prompt
from northvaine.core.models import ModelTier, NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.discover import neutralise_steering
from northvaine.radar.models import ClientSpec
from northvaine.sensors.base import SensorQuery

__all__ = ["ExpansionProposal", "QueryExpansion", "Target", "expand_queries", "parse_targets"]

_URL = re.compile(r"https?://|www\.|\.[a-z]{2,4}/", re.IGNORECASE)
_TARGET = re.compile(r"^(?P<lang>[a-z]{2}):(?P<country>[A-Z]{2})$")


class Target(NorthvaineModel):
    language: str = Field(pattern=r"^[a-z]{2}$")  # ISO 639-1
    country: str = Field(pattern=r"^[A-Z]{2}$")  # ISO 3166-1 alpha-2


def parse_targets(text: str) -> list[Target]:
    """`"de:DE,fr:FR"` -> targets; raises ValueError on anything else."""
    out: list[Target] = []
    for part in (p.strip() for p in text.split(",") if p.strip()):
        match = _TARGET.match(part)
        if match is None:
            raise ValueError(f"target {part!r} must look like 'de:DE'")
        out.append(Target(language=match["lang"], country=match["country"]))
    return out


class _ProposedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str
    country: str
    text: str


class _ProposedTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str
    term: str


class QueryExpansion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[_ProposedQuery] = Field(max_length=12)
    offer_terms: list[_ProposedTerm] = Field(max_length=30)


class ExpansionProposal(NorthvaineModel):
    """For a person to approve: what to add to the client spec, and what code dropped."""

    client: str
    status: Literal["proposal"] = "proposal"
    sensor: str
    queries_to_add: list[SensorQuery]
    offer_terms_to_add: list[str]
    dropped: list[str]
    cost_usd: str


def _clean(text: str) -> str:
    return " ".join(text.replace('"', " ").split())


async def expand_queries(
    spec: ClientSpec,
    targets: list[Target],
    *,
    run: RunContext,
    sensor: str = "tavily",
    session: object = None,
    settings: Settings | None = None,
) -> ExpansionProposal:
    """Ask once, then keep only what code accepts. The model never edits the spec."""
    cfg = settings or get_settings()
    from northvaine.brain.llm import complete_json  # keeps the SDK out of module import

    existing = spec.sensors.get(sensor, [])
    template = existing[0] if existing else SensorQuery()
    lines = [f"{','.join(q.countries) or '-'} | {q.text}" for q in existing if q.text]
    result = await complete_json(
        tier=ModelTier.FAST,
        prompt=load_prompt("query_expand"),
        variables={
            "offer": spec.offer,
            "offer_terms": Untrusted(", ".join(spec.offer_terms) or "(none yet)"),
            "queries": Untrusted("\n".join(lines) or "(none yet)"),
            "targets": "\n".join(f"{t.language} ({t.country})" for t in targets),
        },
        output_model=QueryExpansion,
        purpose="query_expand",
        run=run,
        session=session,
        max_tokens=cfg.query_expand_max_tokens,
    )
    wanted = {(t.language, t.country) for t in targets}
    languages = {t.language for t in targets}
    seen_queries = {(q.text or "").casefold() for q in existing}
    seen_terms = {t.casefold() for t in spec.offer_terms}
    queries: list[SensorQuery] = []
    terms: list[str] = []
    dropped: list[str] = []

    def problem(text: str, low: int, high: int) -> str | None:
        if not low <= len(text) <= high:
            return "length"
        if _URL.search(text):
            return "web address"
        if neutralise_steering(text, cfg)[1]:
            return "text aimed at AI systems"
        return None

    for item in result.value.queries:
        text = _clean(item.text)
        why = problem(text, 3, 200)
        if (item.language, item.country) not in wanted:
            why = why or "language or country not asked for"
        if text.casefold() in seen_queries:
            why = why or "duplicate"
        if why:
            dropped.append(f"query {text!r}: {why}")
            continue
        seen_queries.add(text.casefold())
        queries.append(
            template.model_copy(
                update={"text": text, "countries": [item.country], "languages": [item.language]}
            )
        )
    for item in result.value.offer_terms:
        term = _clean(item.term)
        why = problem(term, 3, 60)
        if item.language not in languages:
            why = why or "language not asked for"
        if term.casefold() in seen_terms:
            why = why or "duplicate"
        if why:
            dropped.append(f"term {term!r}: {why}")
            continue
        seen_terms.add(term.casefold())
        terms.append(term)
    return ExpansionProposal(
        client=spec.id,
        sensor=sensor,
        queries_to_add=queries,
        offer_terms_to_add=terms,
        dropped=dropped,
        cost_usd=str(result.cost_usd),
    )
