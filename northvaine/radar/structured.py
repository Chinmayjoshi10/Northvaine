"""Code-only evidence from structured official records (T4.3, D46).

No LLM. `source_quote` is one exact rendered line of `documents.text`; the statement is a generic
template over the same field. Field values come from `documents.meta` (schema_ver 1, written by
the sensor); the rendered lines are only searched for the quote, never re-parsed for facts.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from northvaine.core.models import ClaimDraft, EventDraft, EvidenceDocument, SubjectMention
from northvaine.core.settings import get_settings
from northvaine.core.standards import _iso3166
from northvaine.sensors.dates import parse_date

__all__ = ["structured_evidence"]

SCHEMA_VER = 1
EXTRACTED_BY = "code"
TENDER = "tender_published"
AWARD = "contract_awarded"


@lru_cache(maxsize=1)
def _iso3_to_iso2() -> dict[str, str]:
    return {alpha3.upper(): alpha2 for alpha2, (alpha3, _name) in _iso3166().items()}


def _iso2(code: Any) -> str | None:
    """A TED country code (ISO3) as ISO2; None when unknown. Two-letter codes pass if known."""
    if not isinstance(code, str):
        return None
    code = code.strip().upper()
    if len(code) == 2 and code in _iso3166():
        return code
    return _iso3_to_iso2().get(code)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v not in (None, "")]


def _find_line(lines: list[str], prefix: str, *needles: str) -> str | None:
    """The first rendered line starting with `prefix` that contains every needle."""
    for line in lines:
        if line.startswith(prefix) and all(n in line for n in needles):
            return line
    return None


def _statement(line: str) -> str:
    label, _, value = line.partition(": ")
    return f"The notice record states {label.lower()}: {value}"


class _Builder:
    """Collects claims, one per distinct rendered line, and hands out their indices."""

    def __init__(self) -> None:
        self.claims: list[ClaimDraft] = []
        self._index: dict[str, int] = {}

    def add(self, line: str | None, subject: SubjectMention | None = None) -> int | None:
        if line is None:
            return None
        if line not in self._index:
            self._index[line] = len(self.claims)
            self.claims.append(
                ClaimDraft(
                    statement=_statement(line),
                    source_quote=line,
                    subject=subject,
                    extracted_by=EXTRACTED_BY,
                )
            )
        return self._index[line]


def structured_evidence(
    doc: EvidenceDocument,
) -> tuple[list[ClaimDraft], list[EventDraft]] | None:
    """Claim and event drafts for a structured record, or None when the record is not understood."""
    rules = get_settings().evidence_source_rules
    if rules.get(doc.source_name) != "structured":
        return None
    meta = doc.meta
    if meta.get("schema_ver") != SCHEMA_VER:
        return None

    lines = doc.text.split("\n")
    build = _Builder()

    buyers = _strings(meta.get("buyers"))
    buyer_countries = _strings(meta.get("buyer_countries"))
    winners = [w for w in meta.get("winners") or [] if isinstance(w, dict) and w.get("name")]
    raw_dates = meta.get("raw_dates") if isinstance(meta.get("raw_dates"), dict) else {}

    buyer = (
        SubjectMention(
            name=buyers[0],
            country=_iso2(buyer_countries[0]) if len(buyer_countries) == 1 else None,
            role="buyer",
        )
        if buyers
        else None
    )

    published_line = _find_line(lines, "Published: ")
    buyer_line = _find_line(lines, "Buyer [", "; ".join(buyers)) if buyers else None
    buyer_country_line = _find_line(lines, "Buyer country: ") if buyer_countries else None
    cpv_line = _find_line(lines, "CPV: ") if meta.get("cpv_codes") else None
    value_line = _find_line(lines, "Total value: ") if meta.get("value") else None
    estimate_lines = [line for line in lines if line.startswith("Estimated value (lot): ")]
    deadline_lines = [line for line in lines if line.startswith("Deadline: ")]
    decision_lines = [line for line in lines if line.startswith("Winner decision date: ")]

    published = build.add(published_line)
    buyer_claim = build.add(buyer_line, buyer)
    buyer_country_claim = build.add(buyer_country_line)
    cpv_claim = build.add(cpv_line)
    value_claim = build.add(value_line)
    estimate_claims = [build.add(line) for line in estimate_lines]
    deadline_claims = [build.add(line) for line in deadline_lines]
    decision_claims = [build.add(line) for line in decision_lines]

    def present(*indices: int | None) -> list[int]:
        return [i for i in dict.fromkeys(indices) if i is not None]

    slots: dict[str, Any] = {}
    if cpv_codes := _strings(meta.get("cpv_codes")):
        slots["cpv_codes"] = ", ".join(cpv_codes)
    if buyers:
        slots["buyer_names"] = "; ".join(buyers)
    if buyer_countries:
        slots["buyer_countries"] = ", ".join(buyer_countries)
    if deadlines := _strings(meta.get("deadlines")):
        slots["deadlines"] = ", ".join(deadlines)
    if meta.get("value"):
        slots["value"] = f"{float(meta['value']):.2f}"
    if estimates := _strings(meta.get("estimated_values")):
        slots["estimated_values"] = ", ".join(estimates)

    publication_text = raw_dates.get("publication")
    publication = parse_date(publication_text) if isinstance(publication_text, str) else None
    group_key = doc.group_key
    kind = meta.get("notice_kind")
    events: list[EventDraft] = []

    if kind == TENDER:
        supporting = present(
            published,
            buyer_claim,
            buyer_country_claim,
            cpv_claim,
            value_claim,
            *estimate_claims,
            *deadline_claims,
        )
        if supporting:
            events.append(
                EventDraft(
                    event_type=TENDER,
                    claim_indices=supporting,
                    subject=buyer,
                    date_text=publication_text if publication else None,
                    occurred_on=publication,
                    group_key=group_key,
                    slots=dict(slots),
                )
            )
    elif kind == AWARD:
        # The first parseable decision date; its rendered line is the same position.
        raw_decisions = _strings(raw_dates.get("winner_decisions"))
        decided, decided_text, decided_claim = None, None, None
        for i, raw in enumerate(raw_decisions):
            if (decided := parse_date(raw)) is not None:
                decided_text = raw
                decided_claim = decision_claims[i] if i < len(decision_claims) else None
                break
        occurred = decided or publication
        date_text = decided_text if decided else (publication_text if publication else None)
        for winner in winners:
            name = str(winner["name"])
            country = winner.get("country")
            winner_subject = SubjectMention(name=name, country=_iso2(country), role="winner")
            winner_line = _find_line(lines, "Winner [", name)
            winner_claim = build.add(winner_line, winner_subject if len(winners) == 1 else None)
            country_claim = build.add(_find_line(lines, "Winner country: ")) if country else None
            supporting = present(
                winner_claim,
                country_claim,
                decided_claim,
                published,
                buyer_claim,
                cpv_claim,
                value_claim,
            )
            if winner_claim is None:
                continue  # no quotable winner line: nothing to ground the event
            winner_slots = dict(slots)
            winner_slots["winner_name"] = name
            if country:
                winner_slots["winner_country"] = str(country)
            events.append(
                EventDraft(
                    event_type=AWARD,
                    claim_indices=supporting,
                    subject=winner_subject,
                    date_text=date_text,
                    occurred_on=occurred,
                    group_key=group_key,
                    slots=winner_slots,
                )
            )

    return build.claims, events
