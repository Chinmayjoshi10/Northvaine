"""Sensor contracts (M3, DECISIONS D35-D41): the generic query, the document shape, the
protocol every sensor implements and the errors they raise.

Nothing here touches the network or reads the environment at import, and httpx is not imported.
Client values (codes, countries, words) are data in a `SensorQuery`, never literals in code.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

from northvaine.core.models import EventType, NorthvaineModel, SourceTier
from northvaine.core.settings import ConfigError, get_settings
from northvaine.core.standards import iso2_to_iso3

__all__ = [
    "ConfigError",
    "DateFlag",
    "FetchBlocked",
    "LeakageError",
    "ReplayUnsupported",
    "RobotsDisallowed",
    "Sensor",
    "SensorDocument",
    "SensorError",
    "SensorQuery",
    "SensorRateLimited",
    "SensorResult",
    "content_hash",
]

_CODE_RE = re.compile(r"^[a-z0-9]+:[A-Za-z0-9.\-]+$")
# ISO 639-1 is a fixed list of two-letter codes.
_ISO639_1 = frozenset(
    [
        "aa",
        "ab",
        "ae",
        "af",
        "ak",
        "am",
        "an",
        "ar",
        "as",
        "av",
        "ay",
        "az",
        "ba",
        "be",
        "bg",
        "bh",
        "bi",
        "bm",
        "bn",
        "bo",
        "br",
        "bs",
        "ca",
        "ce",
        "ch",
        "co",
        "cr",
        "cs",
        "cu",
        "cv",
        "cy",
        "da",
        "de",
        "dv",
        "dz",
        "ee",
        "el",
        "en",
        "eo",
        "es",
        "et",
        "eu",
        "fa",
        "ff",
        "fi",
        "fj",
        "fo",
        "fr",
        "fy",
        "ga",
        "gd",
        "gl",
        "gn",
        "gu",
        "gv",
        "ha",
        "he",
        "hi",
        "ho",
        "hr",
        "ht",
        "hu",
        "hy",
        "hz",
        "ia",
        "id",
        "ie",
        "ig",
        "ii",
        "ik",
        "io",
        "is",
        "it",
        "iu",
        "ja",
        "jv",
        "ka",
        "kg",
        "ki",
        "kj",
        "kk",
        "kl",
        "km",
        "kn",
        "ko",
        "kr",
        "ks",
        "ku",
        "kv",
        "kw",
        "ky",
        "la",
        "lb",
        "lg",
        "li",
        "ln",
        "lo",
        "lt",
        "lu",
        "lv",
        "mg",
        "mh",
        "mi",
        "mk",
        "ml",
        "mn",
        "mr",
        "ms",
        "mt",
        "my",
        "na",
        "nb",
        "nd",
        "ne",
        "ng",
        "nl",
        "nn",
        "no",
        "nr",
        "nv",
        "ny",
        "oc",
        "oj",
        "om",
        "or",
        "os",
        "pa",
        "pi",
        "pl",
        "ps",
        "pt",
        "qu",
        "rm",
        "rn",
        "ro",
        "ru",
        "rw",
        "sa",
        "sc",
        "sd",
        "se",
        "sg",
        "si",
        "sk",
        "sl",
        "sm",
        "sn",
        "so",
        "sq",
        "sr",
        "ss",
        "st",
        "su",
        "sv",
        "sw",
        "ta",
        "te",
        "tg",
        "th",
        "ti",
        "tk",
        "tl",
        "tn",
        "to",
        "tr",
        "ts",
        "tt",
        "tw",
        "ty",
        "ug",
        "uk",
        "ur",
        "uz",
        "ve",
        "vi",
        "vo",
        "wa",
        "wo",
        "xh",
        "yi",
        "yo",
        "za",
        "zh",
        "zu",
    ]
)


class DateFlag(StrEnum):
    """Why a date on a document is not fully trusted (D38). Flagged, never corrected."""

    DEADLINE_BEFORE_PUBLICATION = "deadline_before_publication"
    DECISION_AFTER_PUBLICATION = "decision_after_publication"
    EXTREME_LAG = "extreme_lag"
    MISSING_PUBLICATION = "missing_publication"
    UNPARSEABLE = "unparseable"
    MULTIPLE_VALUES = "multiple_values"
    CLAIMED_DATE_UNTRUSTED = "claimed_date_untrusted"


class SensorQuery(NorthvaineModel):
    """A generic request every sensor maps into its own vocabulary (D35)."""

    schema_ver: int = 1
    kinds: list[EventType] = Field(default_factory=list)
    codes: list[str] = Field(default_factory=list)  # scheme-prefixed, e.g. 'cpv:12345678'
    countries: list[str] = Field(default_factory=list)  # ISO 3166-1 alpha-2
    languages: list[str] = Field(default_factory=list)  # ISO 639-1
    text: str | None = None
    # Restrict a web search to these registrable domains (D96); sensors without it ignore it.
    domains: list[str] = Field(default_factory=list)
    published_from: date | None = None
    published_to: date | None = None
    max_results: int = Field(default=50, ge=1)

    @field_validator("codes")
    @classmethod
    def _codes_have_a_scheme(cls, value: list[str]) -> list[str]:
        for code in value:
            if not _CODE_RE.match(code):
                raise ValueError(f"code {code!r} must look like 'scheme:value'")
        return value

    @field_validator("countries")
    @classmethod
    def _countries_are_iso2(cls, value: list[str]) -> list[str]:
        for code in value:
            if code != code.upper() or len(code) != 2:
                raise ValueError(f"country {code!r} is not an ISO 3166-1 alpha-2 code")
            try:
                iso2_to_iso3(code)
            except KeyError:
                raise ValueError(f"country {code!r} is not an ISO 3166-1 alpha-2 code") from None
        return value

    @field_validator("languages")
    @classmethod
    def _languages_are_iso639_1(cls, value: list[str]) -> list[str]:
        for code in value:
            if code not in _ISO639_1:
                raise ValueError(f"language {code!r} is not an ISO 639-1 code")
        return value

    @model_validator(mode="after")
    def _check_range_and_size(self) -> SensorQuery:
        if (
            self.published_from is not None
            and self.published_to is not None
            and self.published_from > self.published_to
        ):
            raise ValueError("published_from must not be after published_to")
        limit = get_settings().sensor_max_results
        if not 1 <= self.max_results <= limit:
            raise ValueError(f"max_results must be between 1 and {limit}")
        return self


class SensorDocument(NorthvaineModel):
    """One snapshot a sensor produced. `available_at` is when it was knowable (replay gate)."""

    source: str
    tier: SourceTier
    url: str
    title: str | None = None
    text: str
    content_hash: str
    language: str | None = None
    published_on: date | None = None
    fetched_at: datetime
    available_at: datetime | None = None
    external_id: str | None = None
    group_key: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    date_flags: list[DateFlag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_availability(self) -> SensorDocument:
        if self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        if self.available_at is None:
            return self
        if self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        if self.tier is SourceTier.OFFICIAL:
            # An official register publishes on a known day; the document may be fetched before
            # it is "available" (a notice fetched on its publication day).
            if self.published_on is None:
                raise ValueError("official tier with available_at needs published_on")
            earliest = datetime.combine(self.published_on + timedelta(days=1), time.min, tzinfo=UTC)
            if self.available_at < earliest:
                raise ValueError(
                    "official available_at must be at or after 00:00 UTC of published_on + 1 day"
                )
        elif self.available_at > self.fetched_at:
            raise ValueError("available_at must not be later than fetched_at")
        return self


class SensorResult(NorthvaineModel):
    documents: list[SensorDocument] = Field(default_factory=list)
    next_cursor: str | None = None
    truncated: bool = False
    enumerable: bool
    notes: list[str] = Field(default_factory=list)


@runtime_checkable
class Sensor(Protocol):
    """What every sensor offers. `enumerable` says whether recall can be measured (D41)."""

    name: ClassVar[str]
    tier: ClassVar[SourceTier]
    enumerable: ClassVar[bool]

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult: ...


class SensorError(RuntimeError):
    """Base class of everything a sensor raises on purpose."""


class FetchBlocked(SensorError):
    """A URL was refused before or while fetching (private address, deny list, scheme...)."""


class RobotsDisallowed(SensorError):
    """robots.txt forbids fetching the URL."""


class SensorRateLimited(SensorError):
    """The provider said slow down. `retry_after` is in seconds, or None when unstated."""

    def __init__(self, message: str = "rate limited", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ReplayUnsupported(SensorError):
    """The sensor cannot honour the requested `as_of` (live web sources, ARCHITECTURE 23)."""


class LeakageError(SensorError):
    """A document that was not yet available at `as_of` reached a replay."""


def content_hash(text: str) -> str:
    """sha256 hex of the whitespace-normalized text: unchanged content hashes the same."""
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
