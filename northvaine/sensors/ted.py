"""TED Search API v3 sensor (M3). The request builder is frozen here; parsing is T3.4's.

Confirmed shapes: docs/integrations/ted-search-api-v3-*.md and the PF1-PF3 pre-flight.
`query.text` and non-cpv codes are ignored by TED in M3. Only fields in TED_SAFE_FIELDS are
requested, so no contact data, person names or internet addresses are ever fetched.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from northvaine.core.models import EventType, SourceTier
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import iso2_to_iso3
from northvaine.sensors.base import SensorDocument, SensorQuery, SensorResult

if TYPE_CHECKING:  # httpx is only needed by T3.4's implementation
    import httpx

TED_SAFE_FIELDS: tuple[str, ...] = (
    "publication-number",
    "notice-type",
    "notice-subtype",
    "notice-version",
    "notice-identifier",
    "procedure-identifier",
    "publication-date",
    "deadline-receipt-request",
    "winner-decision-date",
    "buyer-name",
    "buyer-country",
    "winner-name",
    "winner-country",
    "classification-cpv",
    "notice-title",
    "estimated-value-lot",
    "total-value",
)

# Generic EventType -> TED's own notice types. No client or industry word lives here (rule #1).
TED_KIND_TO_NOTICE_TYPES: dict[EventType, tuple[str, ...]] = {
    EventType.TENDER_PUBLISHED: ("cn-standard",),
    EventType.CONTRACT_AWARDED: ("can-standard",),
}

TED_MAX_LIMIT = 250


def _clause(field: str, values: Sequence[str]) -> str:
    if len(values) == 1:
        return f"{field}={values[0]}"
    return f"{field} IN ({' '.join(values)})"


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def build_request(
    query: SensorQuery,
    *,
    as_of: datetime | None = None,
    page: int = 1,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """The TED search body for a generic query (PLAN.md, canonical TED request).

    Clauses joined by AND: notice types, cpv codes, buyer countries (alpha-3), then the
    publication-date bounds as yyyyMMdd. With `as_of`, the upper bound is
    min(published_to, as_of UTC date - ted_availability_lag_days). Raises ValueError when no
    kind maps to a TED notice type.
    """
    settings = settings or get_settings()
    notice_types = _unique(
        [t for kind in query.kinds for t in TED_KIND_TO_NOTICE_TYPES.get(kind, ())]
    )
    if not notice_types:
        raise ValueError("no query kind maps to a TED notice type")
    clauses = [_clause("notice-type", notice_types)]
    cpv = _unique([c.split(":", 1)[1] for c in query.codes if c.startswith("cpv:")])
    if cpv:
        clauses.append(_clause("classification-cpv", cpv))
    countries = _unique([iso2_to_iso3(c) for c in query.countries])
    if countries:
        clauses.append(_clause("buyer-country", countries))
    if query.published_from is not None:
        clauses.append(f"publication-date>={query.published_from:%Y%m%d}")
    upper: date | None = query.published_to
    if as_of is not None:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        cutoff = as_of.astimezone(UTC).date() - timedelta(days=settings.ted_availability_lag_days)
        upper = cutoff if upper is None else min(upper, cutoff)
    if upper is not None:
        clauses.append(f"publication-date<={upper:%Y%m%d}")
    return {
        "query": " AND ".join(clauses),
        "fields": list(TED_SAFE_FIELDS),
        "limit": min(TED_MAX_LIMIT, query.max_results),
        "page": page,
    }


def render_notice_text(record: dict[str, Any]) -> str:
    """Deterministic plain-text rendering of a PII-free search record (D39). T3.4."""
    raise NotImplementedError("T3.4")


def parse_notice(
    record: dict[str, Any], *, fetched_at: datetime, settings: Settings | None = None
) -> SensorDocument:
    """One TED search record to a SensorDocument with D36 availability and date flags. T3.4."""
    raise NotImplementedError("T3.4")


class TedSensor:
    """TED notices as documents. Enumerable: the pricing window is a complete list. T3.4."""

    name: ClassVar[str] = "ted"
    tier: ClassVar[SourceTier] = SourceTier.OFFICIAL
    enumerable: ClassVar[bool] = True

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
        sleep: Any = None,
    ) -> None:
        raise NotImplementedError("T3.4")

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        raise NotImplementedError("T3.4")
