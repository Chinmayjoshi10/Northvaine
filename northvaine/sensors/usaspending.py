"""USAspending contract-award sensor: US federal prime contract awards as documents (D90).

Confirmed shapes: the official API contract (usaspending-api repo, `api_contracts/contracts/v2/
search/spending_by_award.md` and `search_filters.md`) and a live keyless probe on 2026-10-09,
recorded in tests/fixtures/sensors/usaspending/. The API needs no key; US federal data is public.

What this sensor does and does not do:
- It reads awards only: `kinds` must include `contract_awarded`. Open US tenders are a different
  source (SAM.gov) and are not handled here.
- Window: `time_period` with `date_type: new_awards_only`, so only awards whose base transaction
  falls in the window are listed (later modifications of old awards are not new awards). `codes`
  with the `naics:` and `psc:` schemes map to the API filters; other schemes (`cpv:`) are ignored
  and, if they are the only codes, nothing is fetched (an unfiltered search would be noise).
  `text` maps to `keywords`. `countries` must include US: the awarding side is always federal.
- Only the fields in USASPENDING_FIELDS are requested. Recipient and place-of-performance
  addresses, contacts and identifiers of people are never asked for, rendered or stored.
- Recipients that are natural persons are withheld (D76): names carrying a marker from settings
  and person-shaped names ("SURNAME, GIVEN") become a stable placeholder.
- `Published` is the date the record was last modified on USAspending, so a later amendment
  never leaks into a replay; the award decision date is the base obligation date.
- Output lines follow the TED/FTS rendering so radar/structured.py reuses its evidence path.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import quote

from northvaine.core.models import EventType, SourceTier
from northvaine.core.settings import Settings, get_settings
from northvaine.sensors.base import (
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
from northvaine.sensors.ted import withhold_natural_persons

if TYPE_CHECKING:
    import httpx

USASPENDING_AWARD_URL = "https://www.usaspending.gov/award/{award_id}"
USASPENDING_MAX_LIMIT = 100
USASPENDING_COUNTRY = "US"
USASPENDING_SORT = "Base Obligation Date"
META_SCHEMA_VER = 1

# Everything the sensor ever asks for. No address, location object, contact or person field.
USASPENDING_FIELDS: tuple[str, ...] = (
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Description",
    "Start Date",
    "End Date",
    "Base Obligation Date",
    "Last Modified Date",
    "NAICS",
    "PSC",
    "Contract Award Type",
    "Place of Performance Country Code",
    "Place of Performance State Code",
    "generated_internal_id",
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w+])\+?\d[\d\s.\-()]{7,}\d(?![\w])")
_ID = re.compile(r"^[A-Za-z0-9_.\-]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NAICS = re.compile(r"^\d{2,6}$")
_PSC = re.compile(r"^[A-Za-z0-9]{1,4}$")
_ALPHA = re.compile(r"^[A-Za-z][A-Za-z'.\-]*$")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        out = _EMAIL.sub("[email removed]", " ".join(value.split()))
        return _PHONE.sub("[phone removed]", out)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _day(value: Any) -> str | None:
    """The leading YYYY-MM-DD of a date or date-time string, else None."""
    if isinstance(value, str) and _DATE.match(value.strip()):
        return value.strip()[:10]
    return None


# ----------------------------------------------------------------------------- request


def build_request(
    query: SensorQuery,
    *,
    as_of: datetime | None = None,
    page: int = 1,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """The JSON body for a generic query. Raises ValueError when `contract_awarded` is not asked
    for or `as_of` is naive. The window's end is min(published_to, as_of date - lag), so nothing
    modified on or after the as_of day is requested; without a start it is `default_window_days`
    before the end."""
    settings = settings or get_settings()
    if EventType.CONTRACT_AWARDED not in query.kinds:
        raise ValueError("USAspending lists contract awards only")
    upper: date | None = query.published_to
    if as_of is not None:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        cutoff = as_of.astimezone(UTC).date() - timedelta(
            days=settings.usaspending_availability_lag_days
        )
        upper = cutoff if upper is None else min(upper, cutoff)
    if upper is None:
        upper = datetime.now(UTC).date()
    lower = query.published_from or upper - timedelta(days=settings.usaspending_default_window_days)
    filters: dict[str, Any] = {
        "award_type_codes": list(settings.usaspending_award_type_codes),
        "time_period": [
            {
                "start_date": lower.isoformat(),
                "end_date": max(lower, upper).isoformat(),
                "date_type": "new_awards_only",
            }
        ],
    }
    naics, psc = _codes(query)
    if naics:
        filters["naics_codes"] = naics
    if psc:
        filters["psc_codes"] = psc
    if query.text and query.text.strip():
        filters["keywords"] = [" ".join(query.text.split())]
    return {
        "filters": filters,
        "fields": list(USASPENDING_FIELDS),
        "limit": min(USASPENDING_MAX_LIMIT, query.max_results),
        "page": page,
        "sort": USASPENDING_SORT,
        "order": "desc",
        "spending_level": "awards",
    }


def _codes(query: SensorQuery) -> tuple[list[str], list[str]]:
    """(NAICS, PSC) values from `naics:` and `psc:` codes, malformed ones dropped."""
    naics: list[str] = []
    psc: list[str] = []
    for code in query.codes:
        scheme, _, value = code.partition(":")
        value = value.strip()
        if scheme == "naics" and _NAICS.match(value):
            naics.append(value)
        elif scheme == "psc" and _PSC.match(value):
            psc.append(value.upper())
    return _unique(naics), _unique(psc)


# ----------------------------------------------------------------------------- privacy


def _looks_like_person(name: str, settings: Settings) -> bool:
    """`SURNAME, GIVEN [M]` or `GIVEN M SURNAME` made only of name-like words, none of them a
    legal form. Conservative on purpose: a plain two-word company name is not caught."""
    forms = {f.casefold() for f in settings.radar_legal_forms}
    if "," in name:
        left, _, right = name.partition(",")
        words = left.split() + right.split()
        shaped = len(left.split()) in (1, 2) and len(right.split()) in (1, 2)
    else:
        words = name.split()
        shaped = len(words) in (2, 3) and any(len(w.strip(".")) == 1 for w in words[1:-1])
    if not shaped or not words or len(words) > 4:
        return False
    cleaned = [w.strip(".,") for w in words]
    if any(w.casefold() in forms for w in cleaned):
        return False
    return all(_ALPHA.match(w) for w in cleaned)


def _winner_name(raw: Any, settings: Settings) -> str | None:
    """The recipient as shown, a placeholder for a natural person, None when it names no one."""
    name = _text(raw)
    if not name:
        return None
    if any(m.casefold() in name.casefold() for m in settings.usaspending_unnamed_recipient_markers):
        return None
    markers = (*settings.ted_natural_person_markers, *settings.usaspending_natural_person_markers)
    cfg = settings.model_copy(update={"ted_natural_person_markers": markers})
    safe = withhold_natural_persons({"winner-name": [name]}, cfg)["winner-name"][0]
    if (
        safe == name
        and settings.usaspending_withhold_person_shaped_names
        and _looks_like_person(name, settings)
    ):
        # Same placeholder form as the markers path: stable and not reversible.
        only_this = settings.model_copy(update={"ted_natural_person_markers": (name,)})
        safe = withhold_natural_persons({"winner-name": [name]}, only_this)["winner-name"][0]
    return safe


# ----------------------------------------------------------------------------- reading


def _money(amount: float, currency: str | None) -> str:
    return f"{amount:.2f} {currency}" if currency else f"{amount:.2f}"


def _code(value: Any) -> str | None:
    """NAICS and PSC come as {"code", "description"}; only the code is kept."""
    code = _dict(value).get("code") if isinstance(value, dict) else value
    return str(code).strip() if code not in (None, "") else None


def _extract(record: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Every value the document needs, read once, so text and meta cannot disagree."""
    award_id = _text(record.get("Award ID"))
    generated = record.get("generated_internal_id")
    generated = str(generated) if isinstance(generated, str) and _ID.match(generated) else None
    agency = _text(record.get("Awarding Agency"))
    sub_agency = _text(record.get("Awarding Sub Agency"))
    # The sub-agency is the office that buys, so it comes first (it becomes the buyer subject).
    buyers = _unique([n for n in (sub_agency, agency) if n])

    name = _winner_name(record.get("Recipient Name"), settings)
    winners = [{"name": name, "country": None}] if name else []

    amount = _number(record.get("Award Amount"))
    title = _text(record.get("Description"))
    if title and len(title) > settings.usaspending_title_max_chars:
        title = title[: settings.usaspending_title_max_chars].rstrip() + "..."

    signed = _day(record.get("Base Obligation Date"))
    modified = _day(record.get("Last Modified Date"))
    state = _text(record.get("Place of Performance State Code"))
    country = _text(record.get("Place of Performance Country Code"))
    place = ", ".join(p for p in (state, country) if p) or None
    return {
        "id": award_id,
        "generated_id": generated,
        "award_type": _text(record.get("Contract Award Type")),
        "raw_publication": modified or signed,
        "title": title,
        "buyers": buyers,
        "winners": winners,
        "naics": [c for c in [_code(record.get("NAICS"))] if c],
        "psc": [c for c in [_code(record.get("PSC"))] if c],
        "raw_decisions": [signed] if signed else [],
        "raw_start": _day(record.get("Start Date")),
        "raw_end": _day(record.get("End Date")),
        "total": amount if amount and amount > 0 else None,
        "place": place,
    }


def _render(x: dict[str, Any]) -> str:
    lines: list[str] = []
    if x["id"]:
        lines.append(f"Notice: {x['id']}" + (f" ({x['award_type']})" if x["award_type"] else ""))
    if x["generated_id"]:
        lines.append(f"Procedure: {x['generated_id']}")
    if x["raw_publication"]:
        lines.append(f"Published: {x['raw_publication']}")
    if x["title"]:
        lines.append(f"Title [eng]: {x['title']}")
    if x["buyers"]:
        lines.append(f"Buyer [eng]: {'; '.join(x['buyers'])}")
        lines.append(f"Buyer country: {USASPENDING_COUNTRY}")
    if x["winners"]:
        lines.append(f"Winner [eng]: {'; '.join(w['name'] for w in x['winners'])}")
    if x["naics"]:
        lines.append(f"NAICS: {', '.join(x['naics'])}")
    if x["psc"]:
        lines.append(f"PSC: {', '.join(x['psc'])}")
    lines.extend(f"Winner decision date: {d}" for d in x["raw_decisions"])
    if x["raw_start"]:
        lines.append(f"Contract start: {x['raw_start']}")
    if x["raw_end"]:
        lines.append(f"Contract end: {x['raw_end']}")
    if x["place"]:
        lines.append(f"Place of performance: {x['place']}")
    if x["total"]:
        lines.append(f"Total value: {_money(x['total'], 'USD')}")
    return "\n".join(lines)


def render_award_text(record: dict[str, Any], *, settings: Settings | None = None) -> str:
    """Deterministic plain-text rendering of one award (D39). Absent fields leave no line."""
    return _render(_extract(record, settings or get_settings()))


def parse_award(
    record: dict[str, Any], *, fetched_at: datetime, settings: Settings | None = None
) -> SensorDocument:
    """One search result to a SensorDocument with D36 availability and D38 date flags.

    Raises ValueError when the award has no usable `generated_internal_id` (it names the public
    page and the dedupe key)."""
    settings = settings or get_settings()
    x = _extract(record, settings)
    if x["generated_id"] is None:
        raise ValueError("USAspending award has no usable generated_internal_id")
    generated = x["generated_id"]

    raw_publication = x["raw_publication"]
    publication = parse_date(raw_publication) if raw_publication else None
    decisions = [parse_date(v) for v in x["raw_decisions"]]
    flags = validate_notice_dates(
        publication, [], decisions, extreme_lag_days=settings.ted_extreme_lag_days
    )
    meta: dict[str, Any] = {
        "schema_ver": META_SCHEMA_VER,
        "notice_kind": EventType.CONTRACT_AWARDED.value,
        "notice_type": x["award_type"],
        "notice_subtype": None,
        "notice_version": None,
        "notice_identifier": x["id"] or generated,
        "ocid": generated,
        "buyers": x["buyers"],
        "buyer_countries": [USASPENDING_COUNTRY] if x["buyers"] else [],
        "winners": x["winners"],
        "cpv_codes": [],
        "naics_codes": x["naics"],
        "psc_codes": x["psc"],
        "deadlines": [],
        "winner_decision_dates": [d.isoformat() for d in dict.fromkeys(d for d in decisions if d)],
        "contract_signed_dates": [],
        "estimated_values": [],
        "value": x["total"],
        "currency": "USD" if x["total"] else None,
        "place_of_performance": x["place"],
        "raw_dates": {
            "publication": raw_publication,
            "deadlines": [],
            "winner_decisions": x["raw_decisions"],
            "contract_signed": [],
        },
        "languages": ["eng"],
        "notes": [],
    }
    text = _render(x)
    available_at = (
        available_at_for_publication(
            publication, lag_days=settings.usaspending_availability_lag_days
        )
        if publication is not None
        else None
    )
    return SensorDocument(
        source=UsaspendingSensor.name,
        tier=UsaspendingSensor.tier,
        url=USASPENDING_AWARD_URL.format(award_id=quote(generated, safe="_-.")),
        title=x["title"],
        text=text,
        content_hash=content_hash(text),
        language="en",
        published_on=publication,
        fetched_at=fetched_at,
        available_at=available_at,
        external_id=generated,
        group_key=generated,
        meta=meta,
        date_flags=flags,
    )


# ----------------------------------------------------------------------------- the sensor


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class UsaspendingSensor:
    """US federal contract awards as documents. Enumerable: a date window is a complete list."""

    name: ClassVar[str] = "usaspending"
    tier: ClassVar[SourceTier] = SourceTier.OFFICIAL
    enumerable: ClassVar[bool] = True

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        min_interval_seconds: float | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._sleep = sleep or asyncio.sleep
        self._min_interval = (
            self._settings.usaspending_min_interval_seconds
            if min_interval_seconds is None
            else min_interval_seconds
        )
        self._last_call: float | None = None

    def _new_client(self) -> httpx.AsyncClient:
        import httpx  # lazy: importing this module needs no network library

        return httpx.AsyncClient(timeout=self._settings.fetch_timeout_seconds)

    async def _pace(self) -> None:
        if self._last_call is not None:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await self._sleep(wait)
        self._last_call = time.monotonic()

    async def _post(self, client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
        await self._pace()
        response = await client.post(self._settings.usaspending_api_url, json=body)
        if response.status_code in (429, 503):
            raise SensorRateLimited(
                f"USAspending rate limit or outage (HTTP {response.status_code})",
                retry_after=_retry_after(response),
            )
        if response.status_code >= 400:
            # The body is never echoed: it may carry anything. Status only.
            raise SensorError(f"USAspending returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SensorError("USAspending returned a response that is not JSON") from None
        if not isinstance(data, dict):
            raise SensorError("USAspending returned an unexpected response shape")
        return data

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        """Read pages from `cursor` (a page number as text) until `max_results` documents, the
        last page, or `usaspending_max_pages`. `next_cursor` continues."""
        if query.countries and USASPENDING_COUNTRY not in query.countries:
            return SensorResult(
                enumerable=self.enumerable,
                notes=["USAspending covers US federal awards only: no US in query countries"],
            )
        if query.codes and not any(c.startswith(("naics:", "psc:")) for c in query.codes):
            return SensorResult(
                enumerable=self.enumerable,
                notes=["USAspending takes naics: and psc: codes only; no usable code in query"],
            )
        page = 1
        if cursor:
            if not cursor.isdigit() or int(cursor) < 1:
                raise ValueError("cursor must be a page number")
            page = int(cursor)
        # Validate before any network use (raises ValueError for unmappable queries).
        build_request(query, as_of=as_of, page=page, settings=self._settings)
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
        seen: set[str] = set()
        docs: list[SensorDocument] = []
        dropped_late = dropped_undated = skipped = 0
        truncated = cut = False
        next_cursor: str | None = None
        for _ in range(self._settings.usaspending_max_pages):
            body = build_request(query, as_of=as_of, page=page, settings=self._settings)
            data = await self._post(client, body)
            for record in _list(data.get("results")):
                record = _dict(record)
                key = str(record.get("generated_internal_id"))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    doc = parse_award(record, fetched_at=fetched_at, settings=self._settings)
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
            has_next = bool(_dict(data.get("page_metadata")).get("hasNext"))
            page += 1
            if len(docs) >= query.max_results:
                cut = len(docs) > query.max_results
                del docs[query.max_results :]
                truncated = cut or has_next
                next_cursor = None if cut or not has_next else str(page)
                break
            if not has_next:
                break
        else:
            truncated = True  # page cap reached with more pages behind it
            next_cursor = str(page)
        notes: list[str] = []
        if cut:
            notes.append("page cut at max_results; the rest of that page is not returned")
        if dropped_late:
            notes.append(f"dropped {dropped_late} award(s) with available_at after as_of")
        if dropped_undated:
            notes.append(f"dropped {dropped_undated} award(s) with no date under as_of")
        if skipped:
            notes.append(f"skipped {skipped} award(s) with no usable id")
        return SensorResult(
            documents=docs,
            next_cursor=next_cursor,
            truncated=truncated,
            enumerable=self.enumerable,
            notes=notes,
        )
