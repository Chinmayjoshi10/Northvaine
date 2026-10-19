"""UK company register lookups (Companies House REST API, step 1b, D103).

Confirmed shapes (used in the 14-15 Oct field tests): `/search/companies?q=` lists matches with
`company_number` and `title`; `/company/{n}` gives `company_name`, `company_status`,
`date_of_creation`, `sic_codes` and `previous_company_names`; `/company/{n}/persons-with-
significant-control` lists controllers with `kind`, `name`, `notified_on` and `ceased_on`.
Auth is HTTP Basic with the API key as the user name and an empty password.

Timing reads (D111), for a company already found: `/company/{n}/charges` (per charge only
`created_on` and `status` are read; `items[].created_on`, `items[].status`) and
`/company/{n}/filing-history?category=address` (`items[].date`, `items[].type`; only the date of
the latest `AD01` registered-office change is kept, never the address). `persons_entitled` and any
other name are never read or stored.

Company-level only:
- a controller is named only when it is a company (a `corporate-entity-...` or `legal-person-...`
  kind); for a person, only the date a control change was notified is kept, never a name;
- officers, addresses of people and filing documents are never requested; the two timing reads
  above return only dates.

A lookup accepts only an exact match of the normalised name (legal form and spacing ignored), so a
similarly named company is never attached to a candidate.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import date
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any

from pydantic import Field

from northvaine.core.models import NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.sensors.base import ConfigError, SensorError, SensorRateLimited

if TYPE_CHECKING:
    import httpx

REGISTER_URL = "https://find-and-update.company-information.service.gov.uk/company/{number}"
META_SCHEMA_VER = 1
_LEGAL_FORMS = ("LIMITED", "LTD", "PLC", "LLP", "COMPANY", "CO")


@lru_cache(maxsize=1)
def sic_descriptions() -> dict[str, str]:
    """SIC 2007 code -> description, shipped as data (core/data/sic2007.json)."""
    text = resources.files("northvaine.core").joinpath("data/sic2007.json").read_text("utf-8")
    return dict(json.loads(text)["codes"])


def name_key(name: str) -> str:
    """Upper case, letters and digits only, a trailing legal form removed: 'Example Trading Ltd',
    'EXAMPLE TRADING LIMITED' and HMRC's split 'EXAMPLE TRADING LIMITE D' give the same key."""
    key = re.sub(r"[^A-Z0-9]", "", name.upper().replace("&", "AND"))
    for form in _LEGAL_FORMS:
        if key.endswith(form) and len(key) > len(form) + 2:
            return key[: -len(form)]
    return key


class Controller(NorthvaineModel):
    name: str
    since: date | None = None


class RegisterRecord(NorthvaineModel):
    number: str
    name: str
    status: str
    incorporated: date | None = None
    sic_codes: list[str] = Field(default_factory=list)
    previous_names: list[tuple[str, date | None]] = Field(default_factory=list)
    controllers: list[Controller] = Field(default_factory=list)  # companies only
    control_changed_on: date | None = None  # latest notification of any active controller
    charge_created_on: date | None = None  # D111: latest charge registered
    office_moved_on: date | None = None  # D111: latest registered-office change filed

    @property
    def url(self) -> str:
        return REGISTER_URL.format(number=self.number)


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def parse_record(profile: dict[str, Any], psc: dict[str, Any] | None) -> RegisterRecord:
    previous = [
        (str(p.get("name")), _date(p.get("ceased_on")))
        for p in profile.get("previous_company_names") or []
        if isinstance(p, dict) and p.get("name")
    ]
    controllers: list[Controller] = []
    notified: list[date] = []
    for item in (psc or {}).get("items") or []:
        if not isinstance(item, dict) or item.get("ceased_on") or item.get("ceased"):
            continue
        when = _date(item.get("notified_on"))
        if when is not None:
            notified.append(when)
        kind = str(item.get("kind") or "")
        if kind.startswith(("corporate-entity", "legal-person")) and item.get("name"):
            controllers.append(Controller(name=str(item["name"]), since=when))
    return RegisterRecord(
        number=str(profile.get("company_number") or ""),
        name=str(profile.get("company_name") or ""),
        status=str(profile.get("company_status") or "unknown"),
        incorporated=_date(profile.get("date_of_creation")),
        sic_codes=[str(c) for c in profile.get("sic_codes") or []],
        previous_names=previous,
        controllers=controllers,
        control_changed_on=max(notified) if notified else None,
    )


def parse_charges(data: dict[str, Any] | None) -> list[tuple[date, str]]:
    """(created_on, status) per charge. Nothing else is read: never `persons_entitled`."""
    out: list[tuple[date, str]] = []
    for item in (data or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        when = _date(item.get("created_on"))
        if when is not None:
            out.append((when, str(item.get("status") or "unknown")))
    return out


def parse_office_moves(data: dict[str, Any] | None) -> date | None:
    """The date of the latest registered-office change filing (type AD01); no address."""
    dates = [
        d
        for item in (data or {}).get("items") or []
        if isinstance(item, dict) and str(item.get("type") or "").upper() == "AD01"
        for d in [_date(item.get("date"))]
        if d is not None
    ]
    return max(dates) if dates else None


def render_register_text(record: RegisterRecord) -> str:
    """Deterministic lines (D39): what claims quote. Company-level facts only."""
    sic = sic_descriptions()
    lines = [f"Company: {record.name} ({record.number})", f"Status: {record.status}"]
    if record.incorporated:
        lines.append(f"Incorporated: {record.incorporated.isoformat()}")
    for code in record.sic_codes:
        about = sic.get(code)
        lines.append(f"Activity (SIC {code}): {about}" if about else f"Activity (SIC {code})")
    for old, until in record.previous_names:
        lines.append(f"Previous name: {old}" + (f" (until {until.isoformat()})" if until else ""))
    for c in record.controllers:
        lines.append(
            f"Controlled by: {c.name}" + (f" (since {c.since.isoformat()})" if c.since else "")
        )
    if record.control_changed_on:
        lines.append(f"Control last notified: {record.control_changed_on.isoformat()}")
    if record.charge_created_on:
        lines.append(f"Charge registered: {record.charge_created_on.isoformat()}")
    if record.office_moved_on:
        lines.append(f"Registered office changed: {record.office_moved_on.isoformat()}")
    return "\n".join(lines)


class CompaniesHouseClient:
    """Exact-name lookups against the register; pacing and errors like the other sensors."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        key = self._settings.companies_house_api_key
        if key is None or not key.get_secret_value():
            raise ConfigError("COMPANIES_HOUSE_API_KEY is not set")
        token = base64.b64encode(f"{key.get_secret_value()}:".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}"}
        self._client = client
        self._sleep = sleep or asyncio.sleep
        self._last: float | None = None

    async def _get(
        self, client: httpx.AsyncClient, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any] | None:
        min_gap = self._settings.companies_house_min_interval_seconds
        if self._last is not None:
            wait = min_gap - (time.monotonic() - self._last)
            if wait > 0:
                await self._sleep(wait)
        self._last = time.monotonic()
        response = await client.get(
            self._settings.companies_house_api_url + path, params=params, headers=self._headers
        )
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise SensorRateLimited("Companies House rate limit (HTTP 429)")
        if response.status_code >= 400:
            raise SensorError(f"Companies House returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SensorError("Companies House returned a response that is not JSON") from None
        return data if isinstance(data, dict) else None

    async def timing(self, record: RegisterRecord) -> tuple[RegisterRecord, list[str]]:
        """The record with `charge_created_on` and `office_moved_on` read (D111). A 404 means
        none; any other error is a note and leaves that field empty."""
        import httpx  # lazy: importing this module needs no network library

        client = self._client or httpx.AsyncClient(timeout=self._settings.fetch_timeout_seconds)
        notes: list[str] = []
        charge: date | None = None
        moved: date | None = None
        try:
            try:
                charges = parse_charges(
                    await self._get(client, f"/company/{record.number}/charges")
                )
                charge = max((d for d, _ in charges), default=None)
            except SensorError as exc:
                notes.append(f"charges not read for {record.number}: {exc}")
            try:
                history = await self._get(
                    client,
                    f"/company/{record.number}/filing-history",
                    {"category": "address", "items_per_page": "10"},
                )
                moved = parse_office_moves(history)
            except SensorError as exc:
                notes.append(f"address history not read for {record.number}: {exc}")
        finally:
            if self._client is None:
                await client.aclose()
        return record.model_copy(
            update={"charge_created_on": charge, "office_moved_on": moved}
        ), notes

    async def lookup(self, name: str) -> RegisterRecord | None:
        """The register record whose name matches `name` exactly once normalised, else None."""
        import httpx  # lazy: importing this module needs no network library

        client = self._client or httpx.AsyncClient(timeout=self._settings.fetch_timeout_seconds)
        try:
            found = await self._get(client, "/search/companies", {"q": name, "items_per_page": "5"})
            want = name_key(name)
            match = next(
                (
                    item
                    for item in (found or {}).get("items") or []
                    if isinstance(item, dict) and name_key(str(item.get("title") or "")) == want
                ),
                None,
            )
            if match is None or not match.get("company_number"):
                return None
            number = str(match["company_number"])
            profile = await self._get(client, f"/company/{number}")
            if profile is None:
                return None
            psc = await self._get(client, f"/company/{number}/persons-with-significant-control")
            return parse_record(profile, psc)
        finally:
            if self._client is None:
                await client.aclose()
