"""UK HMRC trade data sensor: who imports the client's product codes (D101, D102).

Source: `api.uktradeinfo.com`, HMRC's open, keyless OData API, published under the Open
Government Licence v3.0 (attribute: HM Revenue & Customs, uktradeinfo). Shapes confirmed on
14 Oct 2026 (docs/BUYER_INTENT_PLAN.md, "Data sources"):

- `/Commodity?$filter=Hs6Code eq '<6 digits>'&$expand=Imports($filter=MonthId ge ..;
  $expand=Trader)` lists, per 8-digit code and month, each importing trader (name, address,
  postcode). There is no country or supplier per trader. Names are suppressed when few
  companies import a code.
- The same call for the previous calendar year with `$select=TraderId,MonthId` marks new
  importers.

What this sensor does and does not do:
- `codes` with the `hs:` (6 or 8 digits) or `cn:` (8 digits) scheme are queried; other schemes,
  `text` and `languages` are ignored. `countries` must include GB or nothing is fetched.
- One document per trader per query: the months it imported each requested code in the window.
- **Company-level only.** A trader name without a legal form (`hmrc_company_markers`) may be a
  sole trader, so it is dropped before anything stores or renders it. Address lines other than
  the postcode are never rendered or stored.
- Traders at HMRC's own address for non-UK sellers (`hmrc_overseas_postcodes`) are dropped.
- Documents are ranked (most requested codes, then most months active) and capped at
  `max_results`, with `hmrc_new_importer_share` of the slots kept for importers new this year;
  new importers come first.
"""

from __future__ import annotations

import asyncio
import calendar
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

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

if TYPE_CHECKING:
    import httpx

HMRC_COUNTRY = "GB"
HMRC_MAX_PAGES = 20  # per call; one HS6 code is one to a few 8-digit commodities
META_SCHEMA_VER = 1
_CODE = re.compile(r"^(?:hs|cn):(\d{6}|\d{8})$")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return None


def requested_codes(query: SensorQuery) -> list[str]:
    """The 6- or 8-digit codes this sensor can query, in query order, without duplicates."""
    found: list[str] = []
    for code in query.codes:
        match = _CODE.match(code)
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return found


def month_id(day: date) -> int:
    return day.year * 100 + day.month


def month_label(mid: int) -> str:
    return f"{mid // 100:04d}-{mid % 100:02d}"


def month_end(mid: int) -> date:
    year, month = divmod(mid, 100)
    return date(year, month, calendar.monthrange(year, month)[1])


def month_published_on(mid: int, settings: Settings) -> date:
    """The assumed publication day of a month's importer list: the month end plus the lag."""
    return month_end(mid) + timedelta(days=settings.hmrc_availability_lag_days)


def month_available_at(mid: int, settings: Settings) -> datetime:
    """When a month's importer list counts as known (D36): the day after publication."""
    day = month_published_on(mid, settings) + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def window(
    query: SensorQuery, *, as_of: datetime | None, settings: Settings
) -> tuple[int, int | None]:
    """(first MonthId, last MonthId or None) for the query. Default start: January of the
    as_of (or current) year. With `as_of`, the last month is the latest one already public."""
    if as_of is not None and as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    today = (as_of or datetime.now(UTC)).astimezone(UTC).date()
    start = query.published_from or date(today.year, 1, 1)
    last: int | None = month_id(query.published_to) if query.published_to else None
    if as_of is not None:
        # the newest month whose availability is not after as_of
        probe = date(today.year, today.month, 1)
        while month_available_at(month_id(probe), settings) > as_of:
            probe = (probe - timedelta(days=1)).replace(day=1)
        last = month_id(probe) if last is None else min(last, month_id(probe))
    return month_id(start), last


def build_params(code: str, first: int, last: int | None, *, previous: bool) -> dict[str, str]:
    """OData parameters for one code. `previous` asks only for trader ids and months."""
    field_name = "Hs6Code" if len(code) == 6 else "Cn8Code"
    months = f"MonthId ge {first}" + (f" and MonthId le {last}" if last is not None else "")
    inner = "$select=TraderId,MonthId" if previous else "$expand=Trader"
    return {
        "$filter": f"{field_name} eq '{code}'",
        "$expand": f"Imports($filter={months};{inner})",
    }


# ----------------------------------------------------------------------------- traders


@dataclass
class _Trader:
    trader_id: int
    name: str
    postcode: str | None
    # cn8 -> months imported in the window
    months: dict[str, set[int]] = field(default_factory=dict)
    # the requested codes (6 or 8 digits) it imported
    families: set[str] = field(default_factory=set)
    seen_last_year: bool = False


def _is_company(name: str, settings: Settings) -> bool:
    """A legal form as a whole word, or at the end once spaces are removed: the register
    sometimes splits a word ("TRADING LIMITE D")."""
    words = re.findall(r"[a-z0-9]+", name.casefold())
    joined = "".join(words)
    markers = [m.casefold() for m in settings.hmrc_company_markers]
    return any(m in words for m in markers) or any(
        joined.endswith(m) for m in markers if len(m) >= 3
    )


def _family(cn8: str, codes: list[str]) -> str | None:
    return next((c for c in codes if cn8.startswith(c)), None)


def render_trader_text(trader: _Trader, descriptions: dict[str, str], previous_year: int) -> str:
    """Deterministic plain-text rendering (D39): the lines claims quote."""
    lines = [f"Importer: {trader.name}"]
    if trader.postcode:
        lines.append(f"Postcode: {trader.postcode}")
    for cn8 in sorted(trader.months):
        months = ", ".join(month_label(m) for m in sorted(trader.months[cn8]))
        about = f" ({descriptions[cn8]})" if descriptions.get(cn8) else ""
        lines.append(f"Commodity {cn8}{about}: imported in {months}")
    if trader.seen_last_year:
        lines.append(f"Also recorded importing these codes in {previous_year}")
    else:
        lines.append(f"Not recorded as importing these codes in {previous_year}")
    return "\n".join(lines)


def trader_document(
    trader: _Trader,
    descriptions: dict[str, str],
    *,
    previous_year: int,
    fetched_at: datetime,
    settings: Settings,
) -> SensorDocument:
    all_months = sorted(set().union(*trader.months.values()))
    first, last = all_months[0], all_months[-1]
    text = render_trader_text(trader, descriptions, previous_year)
    available_at = month_available_at(last, settings)
    meta: dict[str, Any] = {
        "schema_ver": META_SCHEMA_VER,
        "record_kind": EventType.IMPORTS_RECORDED.value,
        "trader_id": trader.trader_id,
        "importer": trader.name,
        "postcode": trader.postcode,
        "country": HMRC_COUNTRY,
        "codes": sorted(trader.months),
        "families": sorted(trader.families),
        "months": [month_label(m) for m in all_months],
        "first_month": month_label(first),
        "last_month": month_label(last),
        "months_active": len(all_months),
        "previous_year": previous_year,
        "new_this_year": not trader.seen_last_year,
    }
    return SensorDocument(
        source=HmrcSensor.name,
        tier=HmrcSensor.tier,
        url=f"{settings.hmrc_api_url}/Trader({trader.trader_id})",
        title=f"{trader.name}: UK import records",
        text=text,
        content_hash=content_hash(text),
        language="en",
        published_on=month_published_on(last, settings),
        fetched_at=fetched_at,
        available_at=available_at,
        external_id=f"{trader.trader_id}:{month_label(first)}:{month_label(last)}",
        group_key=f"hmrc:{trader.trader_id}",
        meta=meta,
        date_flags=[],
    )


def _rank_key(t: _Trader) -> tuple[int, int, str]:
    months = len(set().union(*t.months.values()))
    return (-len(t.families), -months, t.name)


def select(traders: list[_Trader], cap: int, new_share: float) -> list[_Trader]:
    """Up to `cap` traders: the best new importers in their share of the slots, the best
    established ones in the rest, any unused slots filled from the other group. New first."""
    new = sorted((t for t in traders if not t.seen_last_year), key=_rank_key)
    old = sorted((t for t in traders if t.seen_last_year), key=_rank_key)
    n_new = min(len(new), round(cap * new_share))
    n_old = min(len(old), cap - n_new)
    n_new = min(len(new), cap - n_old)
    return new[:n_new] + old[:n_old]


# ----------------------------------------------------------------------------- the sensor


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class HmrcSensor:
    """UK importers of the client's product codes. Enumerable: the register lists every importer
    whose name HMRC does not suppress."""

    name: ClassVar[str] = "hmrc"
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
            self._settings.hmrc_min_interval_seconds
            if min_interval_seconds is None
            else min_interval_seconds
        )
        self._last_call: float | None = None

    def _new_client(self) -> httpx.AsyncClient:
        import httpx  # lazy: importing this module needs no network library

        # a busy code returns about a megabyte; allow more than a page fetch
        return httpx.AsyncClient(timeout=max(self._settings.fetch_timeout_seconds, 120.0))

    async def _pace(self) -> None:
        if self._last_call is not None:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await self._sleep(wait)
        self._last_call = time.monotonic()

    async def _get_all(
        self, client: httpx.AsyncClient, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Every commodity row of one call, following `@odata.nextLink`."""
        url: str | None = f"{self._settings.hmrc_api_url}/Commodity"
        rows: list[dict[str, Any]] = []
        for _ in range(HMRC_MAX_PAGES):
            if url is None:
                return rows
            await self._pace()
            response = await client.get(url, params=params)
            if response.status_code in (429, 503):
                raise SensorRateLimited(
                    f"HMRC rate limit or outage (HTTP {response.status_code})",
                    retry_after=_retry_after(response),
                )
            if response.status_code >= 400:
                raise SensorError(f"HMRC returned HTTP {response.status_code}")
            try:
                data = response.json()
            except ValueError:
                raise SensorError("HMRC returned a response that is not JSON") from None
            if not isinstance(data, dict):
                raise SensorError("HMRC returned an unexpected response shape")
            rows.extend(_dict(r) for r in _list(data.get("value")))
            link = data.get("@odata.nextLink")
            url, params = (link, {}) if isinstance(link, str) else (None, {})
        raise SensorError(f"HMRC paging exceeded {HMRC_MAX_PAGES} pages")

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        """All importers of the query's codes in the window, ranked and capped. No cursor: one
        call returns the whole register for a code, so `cursor` is ignored."""
        if query.countries and HMRC_COUNTRY not in query.countries:
            return SensorResult(
                enumerable=self.enumerable,
                notes=["HMRC covers UK imports only: no GB in query countries"],
            )
        if query.kinds and EventType.IMPORTS_RECORDED not in query.kinds:
            return SensorResult(
                enumerable=self.enumerable, notes=["no imports_recorded kind in the query"]
            )
        codes = requested_codes(query)
        if not codes:
            return SensorResult(
                enumerable=self.enumerable, notes=["no hs: or cn: code in the query"]
            )
        first, last = window(query, as_of=as_of, settings=self._settings)
        if last is not None and last < first:
            return SensorResult(
                enumerable=self.enumerable, notes=["no published month inside the window"]
            )
        client = self._client or self._new_client()
        try:
            return await self._search(client, query, codes, first, last, as_of)
        finally:
            if self._client is None:
                await client.aclose()

    async def _search(
        self,
        client: httpx.AsyncClient,
        query: SensorQuery,
        codes: list[str],
        first: int,
        last: int | None,
        as_of: datetime | None,
    ) -> SensorResult:
        settings = self._settings
        fetched_at = datetime.now(UTC)
        previous_year = first // 100 - 1
        overseas = {p.replace(" ", "").upper() for p in settings.hmrc_overseas_postcodes}
        traders: dict[int, _Trader] = {}
        descriptions: dict[str, str] = {}
        dropped_person = dropped_overseas = dropped_late = 0
        person_ids: set[int] = set()

        for code in codes:
            for row in await self._get_all(client, build_params(code, first, last, previous=False)):
                cn8 = str(row.get("Cn8Code") or row.get("CommodityId") or "")
                if not cn8:
                    continue
                if about := _text(row.get("Cn8LongDescription")):
                    descriptions.setdefault(cn8, about)
                for item in _list(row.get("Imports")):
                    item = _dict(item)
                    mid, tid = item.get("MonthId"), item.get("TraderId")
                    if not isinstance(mid, int) or not isinstance(tid, int):
                        continue
                    if as_of is not None and month_available_at(mid, settings) > as_of:
                        dropped_late += 1
                        continue
                    trader = traders.get(tid)
                    if trader is None:
                        info = _dict(item.get("Trader"))
                        name = _text(info.get("CompanyName"))
                        postcode = _text(info.get("PostCode"))
                        if postcode and postcode.replace(" ", "").upper() in overseas:
                            dropped_overseas += 1
                            continue
                        if name is None or not _is_company(name, settings):
                            if tid not in person_ids:
                                person_ids.add(tid)
                                dropped_person += 1
                            continue
                        trader = traders[tid] = _Trader(tid, name, postcode)
                    trader.months.setdefault(cn8, set()).add(mid)
                    trader.families.add(_family(cn8, codes) or code)

        if traders:
            prev_first, prev_last = previous_year * 100 + 1, previous_year * 100 + 12
            for code in codes:
                params = build_params(code, prev_first, prev_last, previous=True)
                for row in await self._get_all(client, params):
                    for item in _list(row.get("Imports")):
                        tid = _dict(item).get("TraderId")
                        if isinstance(tid, int) and tid in traders:
                            traders[tid].seen_last_year = True

        ranked = select(list(traders.values()), query.max_results, settings.hmrc_new_importer_share)
        truncated = len(traders) > query.max_results
        docs = [
            trader_document(
                t,
                descriptions,
                previous_year=previous_year,
                fetched_at=fetched_at,
                settings=settings,
            )
            for t in ranked
        ]
        notes: list[str] = [
            f"{len(traders)} importer(s) of {', '.join(codes)} from {month_label(first)}"
            + (f" to {month_label(last)}" if last is not None else "")
        ]
        if truncated:
            new = sum(not t.seen_last_year for t in ranked)
            notes.append(
                f"kept {len(ranked)}: {new} new this year and {len(ranked) - new} established, "
                "each ranked by codes and months"
            )
        if dropped_person:
            notes.append(f"dropped {dropped_person} trader(s) with no company legal form")
        if dropped_overseas:
            notes.append(f"dropped {dropped_overseas} import line(s) of non-UK sellers")
        if dropped_late:
            notes.append(f"dropped {dropped_late} import line(s) published after as_of")
        return SensorResult(
            documents=docs, truncated=truncated, enumerable=self.enumerable, notes=notes
        )
