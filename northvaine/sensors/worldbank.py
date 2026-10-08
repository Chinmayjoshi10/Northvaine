"""World Bank procurement notices sensor (D91): open calls and contract awards as documents.

Confirmed by live keyless probes on 2026-10-09 (no official parameter reference exists; see
D91 and tests/fixtures/sensors/worldbank/README.md). The API is free and keyless. The dataset
"World Bank Procurement Notices" is published under CC BY 4.0: attribute the World Bank.

What this sensor does and does not do:
- Which notice types are read, and which event each one is, is data (`worldbank_notice_types`).
  Each wanted type is read as its own stream with `notice_type=`, newest first.
- The API has no date filter. Streams come newest first, so the window is applied here: a
  stream stops at the first page that ends before `published_from`. When the window ends long
  before the newest notice, the start is found by bisection on `os`, using one-row probes.
- `fl=` asks only for the fields in WORLDBANK_FIELDS. The `contact_*` fields (names, emails,
  phones, addresses) are never requested. The HTML `notice_text` is requested only for awards,
  and only the "Awarded ..." section is read. The text of an open call is never requested or
  rendered: contact names sit unlabelled inside it, so it cannot be cleaned reliably.
- Award winners and prices are not fields: they sit only in the HTML `notice_text`. They are
  read from the "Awarded ..." section with fixed patterns and written as rendered lines in the
  same format as TED and FTS (`Winner [..]`, `Total value:`...). Bidders who were evaluated or
  rejected, postal addresses and beneficial-owner tables are never read.
- Natural persons are withheld (D76): individual-consultant contracts are dropped, and names
  with a personal marker become a placeholder.
- Text fields come from a source that sometimes double-encodes UTF-8; `_repair` undoes that.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar

from northvaine.core.models import EventType, SourceTier
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import _iso3166
from northvaine.sensors.base import (
    DateFlag,
    SensorDocument,
    SensorError,
    SensorQuery,
    SensorRateLimited,
    SensorResult,
    content_hash,
)
from northvaine.sensors.dates import available_at_for_publication, validate_notice_dates
from northvaine.sensors.ted import NATURAL_PERSON_PREFIX, withhold_natural_persons

if TYPE_CHECKING:
    import httpx

# Only these fields are requested. No `contact_*` field is among them, so a contact name,
# email, phone or address never reaches this process.
WORLDBANK_FIELDS = (
    "id,notice_type,noticedate,notice_lang_name,submission_deadline_date,project_ctry_name,"
    "project_id,project_name,bid_reference_no,bid_description,procurement_group,"
    "procurement_method_code,procurement_method_name,contact_organization,contact_ctry_name"
)
WORLDBANK_AWARD_FIELDS = WORLDBANK_FIELDS + ",notice_text"  # winners and price live only here
WORLDBANK_MAX_OFFSET = 100_000  # the backend rejects `os` above this
WORLDBANK_SEEK_AFTER_DAYS = 2  # bisect to the window only when it ends this far before newest
META_SCHEMA_VER = 1
LICENCE = "CC BY 4.0"
_LANG3 = {"en": "eng", "fr": "fra", "es": "spa", "pt": "por", "ru": "rus", "ar": "ara", "zh": "zho"}
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_AWARDED = re.compile(
    r"<u><b>Awarded [A-Za-z]+\(s\):</b></u>(.*?)(?=<u><b>(?:Evaluated|Rejected)|\Z)", re.S
)
# A bidder block: bold "NAME (id)", optional address text with no further bold, then Country.
# Beneficial-owner blocks have no Country line before the next bold, so they never match.
_BIDDER = re.compile(r"<b>([^<]+?)\s*\((\d+)\)</b><br/>(?:(?!<b>).)*?Country:\s*([^<]*)<br/>", re.S)
_PRICE = re.compile(r"Signed Contract [Pp]rice(?:</b>)?<br/>\s*([A-Za-z]{3})\s+([\d.,]+)\s*<", re.S)
_DECISION = re.compile(r"Date Notification of Award Issued.{0,120}?(\d{4}/\d{2}/\d{2})", re.S)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


# ----------------------------------------------------------------------------- text helpers


def _repair(value: str) -> str:
    """Undo UTF-8 text that was decoded as cp1252 or latin-1 (the source does this to some
    fields). Text that is already correct is returned unchanged."""
    if not any(ord(c) > 127 for c in value):
        return value
    for codec in ("cp1252", "latin-1"):
        try:
            fixed = value.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        return fixed
    return value


def _text(value: Any) -> str | None:
    """One clean line: repaired, whitespace collapsed, emails removed. None when empty."""
    if not isinstance(value, str):
        return None
    text = " ".join(html.unescape(_repair(value)).split())
    return _EMAIL.sub("[email removed]", text) if text else None


def _fold(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name)
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold().strip()


@lru_cache(maxsize=1)
def _names_to_iso2() -> dict[str, str]:
    return {_fold(name): alpha2 for alpha2, (_a3, name) in _iso3166().items()}


def country_iso2(name: Any, settings: Settings) -> str | None:
    """ISO 3166-1 alpha-2 for a World Bank country name; None for regions and unknown names."""
    if not isinstance(name, str) or not name.strip():
        return None
    key = _fold(_repair(name))
    return settings.worldbank_country_aliases.get(key) or _names_to_iso2().get(key)


def _iso_date(raw: Any) -> str | None:
    """`07-Oct-2026`, `2026/08/20` or `2026-10-23T00:00:00Z` as `YYYY-MM-DD`; else None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if m := re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", text):
        month = _MONTHS.get(m.group(2).lower())
        parts = (int(m.group(3)), month, int(m.group(1)))
    elif m := re.match(r"(\d{4})[-/](\d{2})[-/](\d{2})", text):
        parts = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    else:
        return None
    try:
        return date(parts[0], parts[1] or 0, parts[2]).isoformat()
    except ValueError:
        return None


def _as_date(iso: str | None) -> date | None:
    return date.fromisoformat(iso) if iso else None


def _money(amount: float, currency: str | None) -> str:
    return f"{amount:.2f} {currency}" if currency else f"{amount:.2f}"


def _amount(text: str) -> float | None:
    if "," in text:
        if not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
            return None
        text = text.replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


# ----------------------------------------------------------------------------- award text


def parse_award_text(raw_html: str) -> dict[str, Any]:
    """Winners, price and decision date from a Contract Award `notice_text`.

    Only the "Awarded ..." section is read. Returns `winners` (name and country name),
    `prices` (every signed price as (amount, currency)) and `decision` (`YYYY-MM-DD`)."""
    result: dict[str, Any] = {"winners": [], "prices": [], "decision": None}
    if m := _DECISION.search(raw_html):
        result["decision"] = _iso_date(m.group(1))
    section = _AWARDED.search(raw_html)
    if section is None:
        return result
    body = section.group(1)
    seen: set[str] = set()
    for bidder in _BIDDER.finditer(body):
        name = _text(bidder.group(1))
        if name and name not in seen:
            seen.add(name)
            result["winners"].append({"name": name, "country_name": _text(bidder.group(3))})
    for price in _PRICE.finditer(body):
        amount = _amount(price.group(2))
        if amount is not None:
            result["prices"].append((amount, price.group(1).upper()))
    return result


# ----------------------------------------------------------------------------- extraction


def notice_kind(notice: dict[str, Any], settings: Settings) -> EventType | None:
    """The event kind of a notice from its type, per `worldbank_notice_types`."""
    value = settings.worldbank_notice_types.get(str(notice.get("notice_type") or ""))
    return EventType(value) if value else None


def is_skipped(notice: dict[str, Any], settings: Settings) -> bool:
    """Whether the contract's procurement method is on the skip list (a single named person)."""
    return str(notice.get("procurement_method_code") or "") in settings.worldbank_skip_method_codes


def _placeholder(name: str) -> str:
    """The stable stand-in for a withheld name, the same shape `withhold_natural_persons` makes."""
    tag = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{NATURAL_PERSON_PREFIX} {tag}]"


def _with_markers(settings: Settings) -> Settings:
    markers = tuple(
        dict.fromkeys(
            (*settings.ted_natural_person_markers, *settings.worldbank_natural_person_markers)
        )
    )
    return settings.model_copy(update={"ted_natural_person_markers": markers})


def _extract(notice: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Every value the document needs, read once, so text and meta cannot disagree."""
    kind = notice_kind(notice, settings)
    raw_html = notice.get("notice_text") if isinstance(notice.get("notice_text"), str) else ""
    language_name = _text(notice.get("notice_lang_name")) or ""
    language = settings.worldbank_language_codes.get(language_name)
    project_country_name = _text(notice.get("project_ctry_name"))

    buyers = [n for n in [_text(notice.get("contact_organization"))] if n]
    buyer_country = None
    if buyers:
        buyer_country = country_iso2(notice.get("contact_ctry_name"), settings) or country_iso2(
            project_country_name, settings
        )

    winners: list[dict[str, Any]] = []
    prices: list[tuple[float, str]] = []
    decision: str | None = None
    notes: list[str] = []
    if kind is EventType.CONTRACT_AWARDED:
        award = parse_award_text(raw_html)
        winners = [
            {"name": w["name"], "country": country_iso2(w["country_name"], settings)}
            for w in award["winners"]
        ]
        prices, decision = award["prices"], award["decision"]
        if not winners:
            notes.append("winner_not_found_in_notice_text")
        if len(prices) > 1:
            notes.append("multiple_contract_values_total_not_stated")

    # The TED helper works on these two field names; reuse it so the placeholder is the same
    # everywhere (D76), with this source's own markers added.
    safe = withhold_natural_persons(
        {"buyer-name": buyers, "winner-name": [w["name"] for w in winners]},
        _with_markers(settings),
    )
    withhold_all = str(notice.get("procurement_method_code") or "") in (
        settings.worldbank_withhold_winner_method_codes
    )
    for winner, name in zip(winners, safe["winner-name"], strict=True):
        winner["name"] = _placeholder(winner["name"]) if withhold_all else name

    deadline = _iso_date(notice.get("submission_deadline_date"))

    project_id = _text(notice.get("project_id"))
    reference = _text(notice.get("bid_reference_no"))
    return {
        "id": _text(notice.get("id")),
        "notice_type": _text(notice.get("notice_type")),
        "kind": kind,
        "raw_publication": notice.get("noticedate"),
        "publication": _iso_date(notice.get("noticedate")),
        "language": language,
        "title": _text(notice.get("bid_description")),
        "buyers": safe["buyer-name"],
        "buyer_country": buyer_country,
        "project_id": project_id,
        "project_name": _text(notice.get("project_name")),
        "project_country": project_country_name,
        "method_code": _text(notice.get("procurement_method_code")),
        "method_name": _text(notice.get("procurement_method_name")),
        "group": _text(notice.get("procurement_group")),
        "reference": reference,
        "winners": winners,
        "decision": decision,
        "deadline": deadline,
        "total": prices[0][0] if len(prices) == 1 else None,
        "currency": prices[0][1] if len(prices) == 1 else None,
        "group_key": f"{project_id}/{reference}" if project_id and reference else None,
        "notes": notes,
    }


def render_notice_text(notice: dict[str, Any], *, settings: Settings | None = None) -> str:
    """Deterministic plain-text rendering of one notice (D39), TED line formats where the
    meaning matches. The same notice always gives byte-identical text; absent fields leave no
    line."""
    return _render(_extract(notice, settings or get_settings()))


def _render(x: dict[str, Any]) -> str:
    lang = _LANG3.get(x["language"] or "", "und")
    lines: list[str] = []
    if x["id"]:
        lines.append(f"Notice: {x['id']}" + (f" ({x['notice_type']})" if x["notice_type"] else ""))
    if x["reference"]:
        lines.append(f"Procedure: {x['reference']}")
    if x["publication"]:
        lines.append(f"Published: {x['publication']}")
    if x["title"]:
        lines.append(f"Title [{lang}]: {x['title']}")
    if x["buyers"]:
        lines.append(f"Buyer [{lang}]: {'; '.join(x['buyers'])}")
    if x["buyer_country"]:
        lines.append(f"Buyer country: {x['buyer_country']}")
    if x["project_id"]:
        label = f"{x['project_id']} - {x['project_name']}" if x["project_name"] else x["project_id"]
        lines.append(f"Project: {label}")
    if x["project_country"]:
        lines.append(f"Project country: {x['project_country']}")
    if x["method_name"]:
        code = f" ({x['method_code']})" if x["method_code"] else ""
        lines.append(f"Procurement method: {x['method_name']}{code}")
    if x["group"]:
        lines.append(f"Procurement group: {x['group']}")
    if x["winners"]:
        lines.append(f"Winner [{lang}]: {'; '.join(w['name'] for w in x['winners'])}")
        countries = _unique([w["country"] for w in x["winners"] if w["country"]])
        if countries:
            lines.append(f"Winner country: {', '.join(countries)}")
    if x["deadline"]:
        lines.append(f"Deadline: {x['deadline']}")
    if x["decision"]:
        lines.append(f"Winner decision date: {x['decision']}")
    if x["total"]:
        lines.append(f"Total value: {_money(x['total'], x['currency'])}")
    return "\n".join(lines)


def parse_notice(
    notice: dict[str, Any], *, fetched_at: datetime, settings: Settings | None = None
) -> SensorDocument:
    """One procurement notice to a SensorDocument with D36 availability and D38 date flags.

    `available_at` comes only from `noticedate` (the official publication date), never from
    the deadline or the award date inside the text. Dates are flagged, never corrected.
    Raises ValueError when the notice has no id."""
    settings = settings or get_settings()
    if not _text(notice.get("id")):
        raise ValueError("World Bank notice has no id")
    x = _extract(notice, settings)
    notice_id = str(x["id"])

    publication = _as_date(x["publication"])
    deadlines = [_as_date(x["deadline"])] if x["deadline"] else []
    decisions = [_as_date(x["decision"])] if x["decision"] else []
    flags = validate_notice_dates(
        publication, deadlines, decisions, extreme_lag_days=settings.ted_extreme_lag_days
    )
    if notice.get("noticedate") and publication is None and DateFlag.UNPARSEABLE not in flags:
        flags.insert(0, DateFlag.UNPARSEABLE)

    kind: EventType | None = x["kind"]
    language = x["language"]
    meta: dict[str, Any] = {
        "schema_ver": META_SCHEMA_VER,
        "notice_kind": kind.value if kind else None,
        "notice_type": x["notice_type"],
        "notice_subtype": None,
        "notice_version": None,
        "notice_identifier": notice_id,
        "bid_reference": x["reference"],
        "project_id": x["project_id"],
        "project_name": x["project_name"],
        "project_country": x["project_country"],
        "procurement_method_code": x["method_code"],
        "procurement_group": x["group"],
        "buyers": x["buyers"],
        "buyer_countries": [x["buyer_country"]] if x["buyer_country"] else [],
        "winners": x["winners"],
        "cpv_codes": [],  # the source carries no CPV codes
        "deadlines": [x["deadline"]] if x["deadline"] else [],
        "winner_decision_dates": [x["decision"]] if x["decision"] else [],
        "estimated_values": [],
        "value": x["total"],
        "currency": x["currency"],
        "raw_dates": {
            "publication": x["publication"],
            "deadlines": [x["deadline"]] if x["deadline"] else [],
            "winner_decisions": [x["decision"]] if x["decision"] else [],
            "contract_signed": [],
        },
        "languages": [_LANG3.get(language or "", "und")],
        "licence": LICENCE,
        "notes": x["notes"],
    }
    text = _render(x)
    available_at = (
        available_at_for_publication(publication, lag_days=settings.ted_availability_lag_days)
        if publication is not None
        else None
    )
    return SensorDocument(
        source=WorldBankSensor.name,
        tier=WorldBankSensor.tier,
        url=settings.worldbank_notice_url.format(notice_id=notice_id),
        title=x["title"],
        text=text,
        content_hash=content_hash(text),
        language=language,
        published_on=publication,
        fetched_at=fetched_at,
        available_at=available_at,
        external_id=notice_id,
        group_key=x["group_key"],
        meta=meta,
        date_flags=flags,
    )


# ----------------------------------------------------------------------------- the request


def notice_types_for(query: SensorQuery, settings: Settings) -> list[str]:
    """The notice types to read for the query's kinds, in settings order."""
    wanted = {k.value for k in query.kinds}
    return [t for t, kind in settings.worldbank_notice_types.items() if kind in wanted]


def build_request(
    query: SensorQuery,
    notice_type: str,
    *,
    offset: int = 0,
    rows: int | None = None,
    fields: str | None = None,
    settings: Settings | None = None,
) -> dict[str, str]:
    """The query parameters for one page of one notice type. Order is stable.

    The API has no date filter, so none is sent. `text` becomes the API's own full-text
    `qterm`. Countries and codes are applied after the page is read."""
    settings = settings or get_settings()
    if notice_type not in settings.worldbank_notice_types:
        raise ValueError(f"notice type {notice_type!r} is not in worldbank_notice_types")
    if fields is None:
        is_award = settings.worldbank_notice_types[notice_type] == EventType.CONTRACT_AWARDED
        fields = WORLDBANK_AWARD_FIELDS if is_award else WORLDBANK_FIELDS
    params: dict[str, str] = {
        "format": "json",
        "rows": str(rows if rows is not None else settings.worldbank_page_size),
        "os": str(offset),
        "fl": fields,
        "notice_type": notice_type,
    }
    if query.text:
        params["qterm"] = query.text
    return params


def window_upper(query: SensorQuery, as_of: datetime | None, settings: Settings) -> date | None:
    """The last notice date wanted: min(published_to, as_of date minus the availability lag)."""
    upper = query.published_to
    if as_of is not None:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        cutoff = as_of.astimezone(UTC).date() - timedelta(days=settings.ted_availability_lag_days)
        upper = cutoff if upper is None else min(upper, cutoff)
    return upper


# ----------------------------------------------------------------------------- the sensor


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _parse_cursor(cursor: str | None) -> tuple[int, int]:
    """`<type index>:<offset>`; anything else is an error, never a silent restart."""
    if cursor is None:
        return 0, 0
    match = re.fullmatch(r"(\d+):(\d+)", cursor)
    if not match:
        raise ValueError(f"not a World Bank cursor: {cursor!r}")
    return int(match.group(1)), int(match.group(2))


class WorldBankSensor:
    """World Bank procurement notices as documents. Enumerable: a date window is a complete
    list, unless `truncated` says a cap was reached."""

    name: ClassVar[str] = "worldbank"
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
            self._settings.worldbank_min_interval_seconds
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

    async def _get(self, client: httpx.AsyncClient, params: dict[str, str]) -> dict[str, Any]:
        await self._pace()
        response = await client.get(self._settings.worldbank_api_url, params=params)
        if response.status_code in (429, 503):
            raise SensorRateLimited(
                f"World Bank rate limit or outage (HTTP {response.status_code})",
                retry_after=_retry_after(response),
            )
        if response.status_code >= 400:
            # The body is never echoed: it may carry anything. Status only.
            raise SensorError(f"World Bank returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SensorError("World Bank returned a response that is not JSON") from None
        if (
            not isinstance(data, dict)
            or "error" in data
            or not isinstance(data.get("procnotices"), list)
        ):
            raise SensorError("World Bank returned an unexpected response shape")
        return data

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        """Read each wanted notice type newest first, from `cursor` (`<type>:<offset>`), until
        `max_results` documents, the window start, the end of the stream, or the page cap.
        `next_cursor` continues exactly after the last notice returned."""
        types = notice_types_for(query, self._settings)
        if not types:
            raise ValueError("no query kind maps to a World Bank notice type")
        upper = window_upper(query, as_of, self._settings)  # validates as_of before any network
        _parse_cursor(cursor)
        if upper is not None and query.published_from is not None and query.published_from > upper:
            return SensorResult(
                enumerable=self.enumerable,
                notes=["window is empty: it starts after the last date that is available"],
            )
        client = self._client or self._new_client()
        try:
            return await self._search(client, query, types, as_of, cursor)
        finally:
            if self._client is None:
                await client.aclose()

    async def _seek(
        self, client: httpx.AsyncClient, query: SensorQuery, notice_type: str, upper: date
    ) -> tuple[int, int | None]:
        """(offset of the newest notice dated on or before `upper`, total). Streams are newest
        first, so the dates fall as the offset rises and bisection applies. Costs one-row
        probes. Offset 0 when the stream already starts inside the window."""

        async def probe(offset: int) -> tuple[date | None, int]:
            params = build_request(
                query, notice_type, offset=offset, rows=1, fields="id,noticedate",
                settings=self._settings,
            )  # fmt: skip
            data = await self._get(client, params)
            rows = _list(data["procnotices"])
            total = int(data.get("total") or 0)
            first = _as_date(_iso_date(_dict(rows[0]).get("noticedate"))) if rows else None
            return first, total

        newest, total = await probe(0)
        if newest is None or newest <= upper + timedelta(days=WORLDBANK_SEEK_AFTER_DAYS):
            return 0, total
        low, high = 0, min(total, WORLDBANK_MAX_OFFSET + 1)  # `low` is known newer than upper
        while high - low > 1:
            mid = (low + high) // 2
            found, _ = await probe(mid)
            if found is not None and found > upper:
                low = mid
            else:
                high = mid
        return high, total

    async def _search(
        self,
        client: httpx.AsyncClient,
        query: SensorQuery,
        types: list[str],
        as_of: datetime | None,
        cursor: str | None,
    ) -> SensorResult:
        settings = self._settings
        fetched_at = datetime.now(UTC)
        upper = window_upper(query, as_of, settings)
        lower = query.published_from
        start_type, start_offset = _parse_cursor(cursor)
        groups = {c.split(":", 1)[1].upper() for c in query.codes if c.startswith("wbgroup:")}
        countries = set(query.countries)

        seen: set[str] = set()
        docs: list[SensorDocument] = []
        counts = {
            "method": 0, "group": 0, "country": 0, "late": 0, "undated": 0, "bad": 0,
        }  # fmt: skip
        truncated = False
        next_cursor: str | None = None
        pages = 0
        for ti in range(start_type, len(types)):
            notice_type = types[ti]
            offset = start_offset if ti == start_type else 0
            if offset == 0 and upper is not None:
                offset, _ = await self._seek(client, query, notice_type, upper)
            while True:
                if pages >= settings.worldbank_max_pages or offset > WORLDBANK_MAX_OFFSET:
                    truncated, next_cursor = True, f"{ti}:{offset}"
                    break
                params = build_request(query, notice_type, offset=offset, settings=settings)
                data = await self._get(client, params)
                pages += 1
                rows = [_dict(r) for r in _list(data["procnotices"])]
                total = int(data.get("total") or 0)
                before_window = False
                for index, notice in enumerate(rows):
                    notice_id = str(notice.get("id"))
                    if notice_id in seen:
                        continue
                    seen.add(notice_id)
                    day = _as_date(_iso_date(notice.get("noticedate")))
                    if lower is not None and day is not None and day < lower:
                        before_window = True  # newest first: everything after is older
                        break
                    if is_skipped(notice, settings):
                        counts["method"] += 1
                        continue
                    if day is not None and upper is not None and day > upper:
                        counts["late"] += 1
                        continue
                    try:
                        doc = parse_notice(notice, fetched_at=fetched_at, settings=settings)
                    except ValueError:
                        counts["bad"] += 1
                        continue
                    if groups and (doc.meta["procurement_group"] or "").upper() not in groups:
                        counts["group"] += 1
                        continue
                    if (
                        countries
                        and country_iso2(notice.get("project_ctry_name"), settings) not in countries
                    ):
                        counts["country"] += 1
                        continue
                    if as_of is not None:
                        if doc.available_at is None:
                            counts["undated"] += 1
                            continue
                        if doc.available_at > as_of:
                            counts["late"] += 1
                            continue
                    docs.append(doc)
                    if len(docs) >= query.max_results:
                        rest = offset + index + 1
                        more = rest < min(total, WORLDBANK_MAX_OFFSET) or ti + 1 < len(types)
                        truncated = more
                        next_cursor = (
                            f"{ti}:{rest}" if rest < min(total, WORLDBANK_MAX_OFFSET)
                            else (f"{ti + 1}:0" if ti + 1 < len(types) else None)
                        )  # fmt: skip
                        return self._result(docs, counts, truncated, next_cursor)
                offset += len(rows)
                if before_window or not rows or offset >= min(total, WORLDBANK_MAX_OFFSET):
                    break
            if truncated:
                break
        return self._result(docs, counts, truncated, next_cursor)

    def _result(
        self,
        docs: list[SensorDocument],
        counts: dict[str, int],
        truncated: bool,
        next_cursor: str | None,
    ) -> SensorResult:
        notes: list[str] = []
        labels = {
            "method": "dropped {n} notice(s) for a skipped procurement method",
            "group": "dropped {n} notice(s) outside the wanted procurement groups",
            "country": "dropped {n} notice(s) outside the wanted countries",
            "late": "dropped {n} notice(s) outside the window or after as_of",
            "undated": "dropped {n} notice(s) with no date under as_of",
            "bad": "skipped {n} notice(s) with no id",
        }
        notes.extend(labels[k].format(n=n) for k, n in counts.items() if n)
        if truncated:
            notes.append("stopped at a cap; `next_cursor` continues")
        return SensorResult(
            documents=docs,
            next_cursor=next_cursor,
            truncated=truncated,
            enumerable=self.enumerable,
            notes=notes,
        )
