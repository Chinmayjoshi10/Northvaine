"""TED Search API v3 sensor (M3). The request builder is frozen; parsing and the sensor are T3.4's.

Confirmed shapes: docs/integrations/ted-search-api-v3-*.md and the PF1-PF3 pre-flight.
`query.text` and non-cpv codes are ignored by TED in M3. Only fields in TED_SAFE_FIELDS are
requested, so no contact data, person names or internet addresses are ever fetched.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from northvaine.core.models import EventType, SourceTier
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import iso2_to_iso3
from northvaine.sensors.base import (
    DateFlag,
    SensorDocument,
    SensorError,
    SensorQuery,
    SensorRateLimited,
    SensorResult,
    content_hash,
)
from northvaine.sensors.dates import (
    available_at_for_publication,
    parse_date,
    validate_notice_dates,
)

if TYPE_CHECKING:
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


META_SCHEMA_VER = 1
NOTICE_URL = "https://ted.europa.eu/en/notice/{publication_number}/html"

_NOTICE_TYPE_TO_KIND: dict[str, EventType] = {
    notice_type: kind
    for kind, notice_types in TED_KIND_TO_NOTICE_TYPES.items()
    for notice_type in notice_types
}


# ----------------------------------------------------------------------------- record readers
# A TED record omits fields it has no value for, and a field may be a scalar, a list or a
# {language: value} map. These helpers read all of that without assuming any of it.


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _unique_strings(value: Any) -> list[str]:
    """Non-empty strings in first-seen order, duplicates removed (TED repeats values per lot)."""
    seen = [str(v).strip() for v in _as_list(value) if v is not None and str(v).strip()]
    return list(dict.fromkeys(seen))


def _by_language(value: Any) -> dict[str, list[str]]:
    """A multilingual field as {lang: [strings]}, languages sorted, values de-duplicated."""
    if not isinstance(value, dict):
        return {}
    result = {lang: _unique_strings(items) for lang, items in value.items()}
    return {lang: result[lang] for lang in sorted(result) if result[lang]}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _winners(record: dict[str, Any], preferred: str | None) -> list[dict[str, str | None]]:
    """Winners as {name, country}. Names pair with countries by position when the lists are the
    same length; one shared country applies to all; otherwise the country is left unstated."""
    raw_names = record.get("winner-name")
    if not isinstance(raw_names, dict):
        return []
    names_by_lang = _by_language(raw_names)
    lang = preferred if preferred in names_by_lang else next(iter(names_by_lang), None)
    if lang is None:
        return []
    names = [str(n).strip() for n in _as_list(raw_names.get(lang)) if str(n).strip()]
    countries = [str(c) for c in _as_list(record.get("winner-country")) if c]
    unique_countries = list(dict.fromkeys(countries))
    pairs: list[tuple[str, str | None]] = []
    for i, name in enumerate(names):
        if len(countries) == len(names):
            country: str | None = countries[i]
        elif len(unique_countries) == 1:
            country = unique_countries[0]
        else:
            country = None
        pairs.append((name, country))
    return [{"name": n, "country": c} for n, c in dict.fromkeys(pairs)]


def render_notice_text(record: dict[str, Any]) -> str:
    """Deterministic plain-text rendering of a PII-free search record (D39).

    The same record always gives byte-identical text: languages are sorted, repeated values
    are removed, absent fields leave no line. This is what M4's quote checks match against.
    """
    lines: list[str] = []
    number = record.get("publication-number")
    kind = " ".join(str(v) for v in (record.get("notice-type"), record.get("notice-subtype")) if v)
    if number:
        lines.append(f"Notice: {number}" + (f" ({kind})" if kind else ""))
    if record.get("notice-version") is not None:
        lines.append(f"Version: {record['notice-version']}")
    if record.get("procedure-identifier"):
        lines.append(f"Procedure: {record['procedure-identifier']}")
    if record.get("publication-date"):
        lines.append(f"Published: {record['publication-date']}")
    titles = record.get("notice-title")
    if isinstance(titles, dict):
        for lang in sorted(titles):
            if titles[lang]:
                lines.append(f"Title [{lang}]: {str(titles[lang]).strip()}")
    for lang, names in _by_language(record.get("buyer-name")).items():
        lines.append(f"Buyer [{lang}]: {'; '.join(names)}")
    if countries := _unique_strings(record.get("buyer-country")):
        lines.append(f"Buyer country: {', '.join(countries)}")
    for lang, names in _by_language(record.get("winner-name")).items():
        lines.append(f"Winner [{lang}]: {'; '.join(names)}")
    if countries := _unique_strings(record.get("winner-country")):
        lines.append(f"Winner country: {', '.join(countries)}")
    if cpv := _unique_strings(record.get("classification-cpv")):
        lines.append(f"CPV: {', '.join(cpv)}")
    if nature := _unique_strings(record.get("contract-nature")):
        lines.append(f"Contract nature: {', '.join(nature)}")  # D94
    for deadline in _unique_strings(record.get("deadline-receipt-request")):
        lines.append(f"Deadline: {deadline}")
    for decision in _unique_strings(record.get("winner-decision-date")):
        lines.append(f"Winner decision date: {decision}")
    for estimate in _unique_strings(record.get("estimated-value-lot")):
        lines.append(f"Estimated value (lot): {estimate}")
    total = _number(record.get("total-value"))
    if total:  # 0 means "not stated" on TED (PF1), so it is not rendered
        lines.append(f"Total value: {total:.2f}")
    return "\n".join(lines)


NATURAL_PERSON_PREFIX = "[natural person, name withheld"
_NAME_FIELDS = ("buyer-name", "winner-name")


def withhold_natural_persons(record: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """A copy of `record` whose buyer and winner names carrying a natural-person legal form
    (`ted_natural_person_markers`) are replaced by a stable placeholder (D76). Idempotent."""
    patterns = [
        re.compile(r"(?<!\w)" + re.escape(m) + r"(?!\w)", re.IGNORECASE)
        for m in settings.ted_natural_person_markers
    ]

    def fix(value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith(NATURAL_PERSON_PREFIX) or not any(
                p.search(value) for p in patterns
            ):
                return value
            tag = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
            return f"{NATURAL_PERSON_PREFIX} {tag}]"
        if isinstance(value, list):
            return [fix(v) for v in value]
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        return value

    out = dict(record)
    for field in _NAME_FIELDS:
        if field in out:
            out[field] = fix(out[field])
    return out


def parse_notice(
    record: dict[str, Any], *, fetched_at: datetime, settings: Settings | None = None
) -> SensorDocument:
    """One TED search record to a SensorDocument with D36 availability and date flags.

    `available_at` comes only from `publication-date`. Dates are flagged, never corrected (D29).
    Raises ValueError when the record has no publication-number.
    """
    settings = settings or get_settings()
    record = withhold_natural_persons(record, settings)
    number = record.get("publication-number")
    if not number:
        raise ValueError("TED record has no publication-number")
    number = str(number)

    notice_type = record.get("notice-type")
    kind = _NOTICE_TYPE_TO_KIND.get(str(notice_type)) if notice_type else None
    version = record.get("notice-version")

    raw_publication = record.get("publication-date")
    publication = parse_date(raw_publication) if isinstance(raw_publication, str) else None
    raw_deadlines = _unique_strings(record.get("deadline-receipt-request"))
    raw_decisions = _unique_strings(record.get("winner-decision-date"))
    deadlines = [parse_date(v) for v in raw_deadlines]
    decisions = [parse_date(v) for v in raw_decisions]
    flags = validate_notice_dates(
        publication, deadlines, decisions, extreme_lag_days=settings.ted_extreme_lag_days
    )
    if raw_publication and publication is None and DateFlag.UNPARSEABLE not in flags:
        flags.insert(0, DateFlag.UNPARSEABLE)

    buyers_by_lang = _by_language(record.get("buyer-name"))
    preferred = next(iter(buyers_by_lang), None)
    raw_titles = record.get("notice-title")
    titles: dict[str, Any] = raw_titles if isinstance(raw_titles, dict) else {}
    title_lang = preferred if preferred and titles.get(preferred) else None
    if title_lang is None:
        title_lang = next((lang for lang in sorted(titles) if titles[lang]), None)
    title = str(titles[title_lang]).strip() if title_lang else None

    total = _number(record.get("total-value"))
    notes: list[str] = []
    if total == 0:
        notes.append("total_value_zero_read_as_not_stated")
    if isinstance(version, int) and version > 1:
        # PF2: search returns only the latest version, dated by the change.
        notes.append("changed_notice_original_window_lost")
    winners_by_lang = _by_language(record.get("winner-name"))
    languages = sorted(set(titles) | set(buyers_by_lang) | set(winners_by_lang))

    meta: dict[str, Any] = {
        "schema_ver": META_SCHEMA_VER,
        "notice_kind": kind.value if kind else None,
        "notice_type": notice_type,
        "notice_subtype": record.get("notice-subtype"),
        "notice_version": version,
        "notice_identifier": record.get("notice-identifier"),
        "buyers": next(iter(buyers_by_lang.values()), []),
        "buyer_countries": _unique_strings(record.get("buyer-country")),
        "winners": _winners(record, preferred),
        "cpv_codes": _unique_strings(record.get("classification-cpv")),
        "contract_nature": _unique_strings(record.get("contract-nature")),
        "deadlines": [d.isoformat() for d in dict.fromkeys(d for d in deadlines if d)],
        "winner_decision_dates": [d.isoformat() for d in dict.fromkeys(d for d in decisions if d)],
        "estimated_values": _unique_strings(record.get("estimated-value-lot")),
        "value": total if total else None,
        "raw_dates": {
            "publication": raw_publication,
            "deadlines": raw_deadlines,
            "winner_decisions": raw_decisions,
        },
        "languages": languages,
        "notes": notes,
    }
    text = render_notice_text(record)
    available_at = (
        available_at_for_publication(publication, lag_days=settings.ted_availability_lag_days)
        if publication is not None
        else None
    )
    return SensorDocument(
        source=TedSensor.name,
        tier=TedSensor.tier,
        url=NOTICE_URL.format(publication_number=number),
        title=title,
        text=text,
        content_hash=content_hash(text),
        language=None,
        published_on=publication,
        fetched_at=fetched_at,
        available_at=available_at,
        external_id=number,
        group_key=str(record["procedure-identifier"])
        if record.get("procedure-identifier")
        else None,
        meta=meta,
        date_flags=flags,
    )


# ----------------------------------------------------------------------------- the sensor


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP-date form: treated as unstated


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"TED returned HTTP {response.status_code} (not JSON)"
    error = body.get("error") if isinstance(body, dict) else None
    kind = error.get("type") if isinstance(error, dict) else None
    message = body.get("message") if isinstance(body, dict) else None
    return f"TED error {kind or 'unknown'}: {message or response.status_code}"


class TedSensor:
    """TED notices as documents. Enumerable: the pricing window is a complete list."""

    name: ClassVar[str] = "ted"
    tier: ClassVar[SourceTier] = SourceTier.OFFICIAL
    enumerable: ClassVar[bool] = True

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._sleep = sleep or asyncio.sleep
        self._last_call: float | None = None

    def _new_client(self) -> httpx.AsyncClient:
        import httpx  # lazy: importing this module needs no network library

        return httpx.AsyncClient(timeout=self._settings.fetch_timeout_seconds)

    async def _pace(self) -> None:
        """Wait so that calls from this sensor are at least ted_min_interval_seconds apart."""
        interval = self._settings.ted_min_interval_seconds
        if self._last_call is not None:
            wait = interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await self._sleep(wait)
        self._last_call = time.monotonic()

    async def _post(self, client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
        await self._pace()
        response = await client.post(self._settings.ted_api_url, json=body)
        if response.status_code == 429:
            # nginx answers with HTML and usually no Retry-After: never parse the body.
            raise SensorRateLimited("TED rate limit (HTTP 429)", retry_after=_retry_after(response))
        if response.status_code >= 400:
            raise SensorError(_error_text(response))
        data = response.json()
        if not isinstance(data, dict):
            raise SensorError("TED returned an unexpected response shape")
        return data

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        """Fetch pages (PAGE_NUMBER mode) from `cursor` (a page number) until an empty page,
        `totalNoticeCount` reached, or `max_results`. `next_cursor` is the next page number."""
        try:
            page = int(cursor) if cursor else 1
        except ValueError:
            raise ValueError(f"cursor {cursor!r} is not a page number") from None
        if page < 1:
            raise ValueError("cursor must be a page number >= 1")
        client = self._client or self._new_client()
        try:
            return await self._search(client, query, as_of, page)
        finally:
            if self._client is None:
                await client.aclose()

    async def _search(
        self, client: httpx.AsyncClient, query: SensorQuery, as_of: datetime | None, page: int
    ) -> SensorResult:
        fetched_at = datetime.now(UTC)
        limit = min(TED_MAX_LIMIT, query.max_results)
        consumed = (page - 1) * limit  # records on pages the caller already read
        keys: set[tuple[Any, Any]] = set()
        docs: list[SensorDocument] = []
        raw_seen = dropped_late = dropped_undated = skipped = 0
        truncated = False
        cut = False
        next_cursor: str | None = None
        while True:
            body = build_request(query, as_of=as_of, page=page, settings=self._settings)
            data = await self._post(client, body)
            notices = [n for n in _as_list(data.get("notices")) if isinstance(n, dict)]
            if not notices:
                break
            total = data.get("totalNoticeCount")
            raw_seen += len(notices)
            for record in notices:
                key = (record.get("publication-number"), record.get("notice-version"))
                if key in keys:
                    continue
                keys.add(key)
                try:
                    doc = parse_notice(record, fetched_at=fetched_at, settings=self._settings)
                except ValueError:
                    skipped += 1
                    continue
                if as_of is not None:
                    if doc.available_at is None:
                        dropped_undated += 1
                        continue
                    if doc.available_at > as_of:
                        dropped_late += 1
                        continue
                docs.append(doc)
            reached_total = isinstance(total, int) and consumed + raw_seen >= total
            if len(docs) >= query.max_results:
                cut = len(docs) > query.max_results
                del docs[query.max_results :]
                truncated = cut or not reached_total
                if not cut and not reached_total:
                    next_cursor = str(page + 1)
                break
            if reached_total:
                break
            page += 1
        notes: list[str] = []
        if cut:
            notes.append("page cut at max_results; the rest of that page is not returned")
        if dropped_late:
            notes.append(f"dropped {dropped_late} notice(s) with available_at after as_of")
        if dropped_undated:
            notes.append(
                f"dropped {dropped_undated} notice(s) with no publication-date under as_of"
            )
        if skipped:
            notes.append(f"skipped {skipped} record(s) with no publication-number")
        return SensorResult(
            documents=docs,
            next_cursor=next_cursor,
            truncated=truncated,
            enumerable=self.enumerable,
            notes=notes,
        )
