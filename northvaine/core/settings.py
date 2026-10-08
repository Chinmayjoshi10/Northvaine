"""Typed settings read from the environment and an optional `.env` file.

Nothing here needs a database URL or an API key at import. Secrets are SecretStr, so they
never appear in repr, logs or JSON dumps. Model ids, the Nebius base URL, EMBED_DIM and the
daily and total budgets have no defaults: they are confirmed in milestone 2 (docs/integrations/).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """A required setting is missing or invalid; message names the variable."""


class Settings(BaseSettings):
    """Application settings. Env vars win over `.env`; unknown keys are ignored."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        case_sensitive=False,
    )

    # database
    database_url: SecretStr | None = None
    test_database_url: SecretStr | None = None
    db_pool_mode: Literal["session", "transaction"] = "session"
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_echo: bool = False
    # "reuse" by default (T2.1b): one migrated database per process with a TRUNCATE between
    # tests, instead of a migration cycle per test. "database" still works where the role has
    # CREATEDB and full per-test isolation is wanted.
    test_db_isolation: Literal["database", "reuse"] = "reuse"

    # LLM + sensors (values confirmed in M2; no defaults, no guesses)
    nebius_api_key: SecretStr | None = None
    nebius_base_url: str | None = None
    model_fast: str | None = None
    model_mid: str | None = None
    model_deep: str | None = None
    model_embed: str | None = None
    embed_dim: int | None = Field(default=None, ge=1)
    tavily_api_key: SecretStr | None = None

    # sensors (M3). Safe fetch, TED and Tavily. No setting touches the network at import.
    fetch_timeout_seconds: float = Field(default=15.0, gt=0)
    fetch_max_bytes: int = Field(default=5_000_000, ge=1)
    fetch_max_redirects: int = Field(default=5, ge=0)
    fetch_user_agent: str = "NorthvaineBot/0.1 (+https://github.com/northvaine; public pages only)"
    fetch_deny_hosts: list[str] = Field(
        default_factory=lambda: ["linkedin.com", "facebook.com", "instagram.com", "x.com"]
    )
    ted_api_url: str = "https://api.ted.europa.eu/v3/notices/search"
    ted_min_interval_seconds: float = Field(default=1.5, ge=0)
    ted_availability_lag_days: int = 1
    ted_extreme_lag_days: int = Field(default=365, ge=1)
    # Legal forms whose holder is a natural person: such buyer and winner names are withheld
    # at parse time, before anything stores or shows them (D76). Legal terms, not industry words.
    ted_natural_person_markers: tuple[str, ...] = (
        "e.K.",
        "e. K.",
        "e.Kfm.",
        "e.Kfr.",
        "Inhaber",
        "Inh.",
        "GbR",
        "Einzelunternehmen",
        "EIRL",
        "Entreprise individuelle",
    )
    tavily_api_url: str = "https://api.tavily.com"
    tavily_max_calls_per_run: int = Field(default=20, ge=1)
    sensor_max_results: int = Field(default=250, ge=1)

    # money caps (brain/budget.py checks all four before every call). DAILY_BUDGET_USD and
    # TOTAL_BUDGET_USD have no default: calls refuse to run until the founder sets both
    # (DECISIONS D1). RUN_BUDGET_USD and MAX_CALL_COST_USD get conservative defaults, since a
    # run cap with no default would block every run.
    daily_budget_usd: Decimal | None = None
    total_budget_usd: Decimal | None = None
    run_budget_usd: Decimal = Field(default=Decimal("0.20"), gt=0)
    max_call_cost_usd: Decimal = Field(default=Decimal("0.05"), gt=0)

    # LLM call behaviour
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)

    # evidence ledger (M4, D45-D51). Thresholds and rules are data, never literals in radar/.
    quote_min_chars: int = Field(default=20, ge=1)
    quote_match_min_ratio: float = Field(default=0.95, gt=0, le=1)
    extract_max_doc_chars: int = Field(default=12000, ge=1)
    extract_max_claims: int = Field(default=8, ge=1)
    extract_max_tokens: int = Field(default=3000, ge=1)  # 1500 truncated long pages (D73)
    support_max_tokens: int = Field(default=600, ge=1)
    concept_match_min_cosine: float = Field(default=0.80, gt=0, le=1)
    event_cluster_min_cosine: float = Field(default=0.85, gt=0, le=1)
    event_cluster_window_days: int = Field(default=30, ge=1)
    extract_excluded_event_types: tuple[str, ...] = (
        "reorder_due",
        "quote_stale",
        "inbound_question",
    )
    evidence_source_rules: dict[str, str] = Field(
        default_factory=lambda: {
            "ted": "structured",
            "fts": "structured",
            "usaspending": "structured",
            "website": "full_text",
            "tavily": "raw_only",
        }
    )

    # radar (M5, D57-D66). Paths, caps, windows and the legal-form list are data, not literals.
    radar_clients_dir: str = "tests/fixtures/clients"
    radar_reports_dir: str = "reports/radar"
    radar_fixtures_dir: str = "tests/fixtures/radar"
    radar_max_lead_upgrades: int = Field(default=15, ge=1)
    radar_max_gate_candidates: int = Field(default=40, ge=1)
    radar_brief_entries: int = Field(default=10, ge=1)
    radar_tender_window_days: int = Field(default=30, ge=1)  # D27
    radar_tender_lookback_days: int = Field(default=45, ge=1)  # D71
    radar_enumerable_max_results: int = Field(default=100, ge=1)  # D71
    radar_recent_days: int = Field(default=90, ge=1)
    radar_stream_by_event: dict[str, str] = Field(
        default_factory=lambda: {"tender_published": "tender", "contract_awarded": "award"}
    )
    radar_enumerable_sources: tuple[str, ...] = ("ted", "fts", "usaspending")
    radar_legal_forms: tuple[str, ...] = (
        "ltd", "limited", "plc", "llc", "llp", "lp", "inc", "incorporated", "corp",
        "corporation", "co", "company", "gmbh", "ag", "kg", "ug", "sa", "sas", "sarl",
        "srl", "spa", "bv", "nv", "ab", "as", "oy", "aps", "sp z o o", "sl", "slu", "oyj",
        "asa", "se", "pty", "pte", "ou",
    )  # fmt: skip
    gate_max_tokens: int = Field(default=700, ge=1)
    skeptic_max_tokens: int = Field(default=600, ge=1)
    radar_run_budget_usd: Decimal = Field(default=Decimal("1.00"), gt=0)
    # M5.1 brief quality (T5.8, D80). Everything here is generic language, never industry words.
    radar_brief_main_entries: int = Field(default=5, ge=1)
    # Sources can never steer the system (CLAUDE.md #10, D85): sentences in fetched text that
    # address AI systems or ask to be ranked, rated or marked are removed before any model sees
    # them. Generic language patterns (regular expressions, case-insensitive), never industry
    # words.
    radar_steering_patterns: tuple[str, ...] = (
        r"\bignore\b[^.!?\n]{0,30}\b(?:instructions?|prompts?|rules?)\b",
        r"\b(?:system|developer)\s+(?:prompt|message|instructions?)\b",
        r"\b(?:as|you are)\s+an?\s+(?:ai|artificial intelligence|language model|llm|assistant|"
        r"chatbot|bot)\b",
        r"\bnote\s+(?:to|for)\s+(?:ai|ais|llms?|language models?|assistants?|crawlers?|bots?)\b",
        r"\b(?:ai|ais|llms?|chatgpt|claude|gpt|gemini|nemotron|assistants?|crawlers?|bots?|"
        r"agents?)\b[^.!?\n]{0,40}\b(?:must|should|shall|need to|are instructed to|"
        r"are required to)\b",
        r"\b(?:rank|rate|score|mark|list|flag|tag|classify|label|put)\s+(?:us|me|this\s+"
        r"(?:company|page|site|supplier|business|firm)|our\s+(?:company|firm|business))\b"
        r"[^.!?\n]{0,40}\b(?:highest|first|top|best|#?\s?1|number\s+one|priority|hot|"
        r"qualified|buyer|lead)\b",
        r"\b(?:give|assign|award)\s+(?:us|me|this\s+(?:company|page|supplier))\s+(?:the\s+)?"
        r"(?:highest|top|best|maximum|max)\s+(?:rank|rating|score|priority)\b",
    )
    # Likely bidders for open tenders (D81): who won similar awards in the same country.
    radar_bidder_lookback_days: int = Field(default=365, ge=30)
    radar_bidder_max: int = Field(default=5, ge=1)
    radar_bidder_max_queries: int = Field(default=8, ge=0)
    radar_bidder_max_codes: int = Field(default=6, ge=1)
    radar_bidder_max_results: int = Field(default=50, ge=1)
    radar_min_days_left: int = Field(default=5, ge=0)
    radar_offer_term_min_chars: int = Field(default=4, ge=2)
    radar_offer_stopwords: tuple[str, ...] = (
        "a", "an", "and", "or", "the", "of", "for", "to", "in", "into", "on", "at", "by",
        "with", "from", "across", "over", "under", "our", "their", "its", "we", "they",
        "selling", "sells", "sell", "seller", "sellers", "supplier", "suppliers", "supply",
        "supplies", "maker", "makers", "manufacturer", "manufacturers", "producer",
        "producers", "provider", "providers", "company", "companies", "business",
        "businesses", "brand", "brands", "client", "clients", "customer", "customers",
        "product", "products", "service", "services", "goods", "range", "ranges", "overseas",
        "international", "global", "local", "private", "public", "based", "other", "various",
        "including", "such", "also", "more", "most", "high", "quality", "new",
    )  # fmt: skip
    radar_buyer_note_by_stream: dict[str, str] = Field(
        default_factory=lambda: {
            "tender": (
                "The organisation named runs this tender. The goods or materials are often "
                "bought by the contractor that wins it, so reach likely bidders now and check "
                "the specification."
            ),
            "award": (
                "The winner named here carries out the contract and buys what it needs for it."
            ),
            "announcement": (
                "The organisation named is acting on its own plans and is the likely buyer."
            ),
        }
    )
    # A first message tests a hypothesis, never claims a need (COLLAB, WOS field test, D80).
    radar_opening_question_by_stream: dict[str, str] = Field(
        default_factory=lambda: {
            "award": (
                "Congratulations on the contract. Would extra capacity or a complementary range "
                "help you deliver it?"
            ),
            "announcement": (
                "As you plan this, would another supplier option or cover for supply risk be "
                "useful?"
            ),
        }
    )
    radar_action_by_stream: dict[str, str] = Field(
        default_factory=lambda: {
            "tender": (
                "Before the deadline: find the likely bidders and offer them a quote they can "
                "price into their bid."
            ),
            "award": "Introduce yourself to the winner while it plans its purchases.",
            "announcement": (
                "Contact the organisation, or the people designing its project, before "
                "suppliers are chosen."
            ),
        }
    )

    # queue
    job_lease_seconds: int = Field(default=300, ge=1)
    job_max_attempts: int = Field(default=5, ge=1)
    job_backoff_base_seconds: float = 30.0
    job_backoff_max_seconds: float = 3600.0

    # USAspending contract awards (D90). Keyless public API; all of it is data, not code.
    usaspending_api_url: str = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    usaspending_min_interval_seconds: float = Field(default=1.0, ge=0)
    usaspending_max_pages: int = Field(default=10, ge=1)
    # Federal award type codes for contracts (definitive, delivery orders, purchase orders...).
    usaspending_award_type_codes: tuple[str, ...] = ("A", "B", "C", "D")
    # An award is counted as knowable this many days after its last modification, so a replay
    # never sees a later amendment (D36).
    usaspending_availability_lag_days: int = Field(default=3, ge=1)
    usaspending_default_window_days: int = Field(default=45, ge=1)  # when a query has no start
    usaspending_title_max_chars: int = Field(default=300, ge=20)
    # Recipient names carrying these markers are natural persons or redacted: withheld (D76, D90).
    # Added to ted_natural_person_markers; matched as whole words, case-insensitive.
    usaspending_natural_person_markers: tuple[str, ...] = (
        "REDACTED DUE TO PII",
        "SOLE PROPRIETOR",
        "SOLE PROPRIETORSHIP",
        "INDIVIDUAL",
        "D/B/A",
        "DBA",
    )
    # Recipient values that name no one company: no winner line is rendered for them.
    usaspending_unnamed_recipient_markers: tuple[str, ...] = (
        "MULTIPLE RECIPIENTS",
        "MISCELLANEOUS FOREIGN AWARDEES",
    )
    # "SURNAME, GIVEN" or "GIVEN M SURNAME" with no legal form (radar_legal_forms) is a person.
    usaspending_withhold_person_shaped_names: bool = True

    @field_validator("evidence_source_rules")
    @classmethod
    def _rules_are_known(cls, value: dict[str, str]) -> dict[str, str]:
        for source, rule in value.items():
            if rule not in {"structured", "full_text", "raw_only"}:
                raise ValueError(
                    f"evidence_source_rules[{source!r}] must be structured, full_text or raw_only"
                )
        return value

    @field_validator("radar_stream_by_event")
    @classmethod
    def _streams_are_known(cls, value: dict[str, str]) -> dict[str, str]:
        for event, stream in value.items():
            if stream not in {"tender", "award", "announcement"}:
                raise ValueError(
                    f"radar_stream_by_event[{event!r}] must be tender, award or announcement"
                )
        return value

    @field_validator("radar_enumerable_sources")
    @classmethod
    def _enumerable_sources_not_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("radar_enumerable_sources must not be empty")
        return value

    @field_validator("ted_availability_lag_days")
    @classmethod
    def _lag_at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("ted_availability_lag_days must be >= 1")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings. Tests reset it with `get_settings.cache_clear()`."""
    return Settings()


def require_database_url(settings: Settings | None = None) -> str:
    """Return DATABASE_URL as a plain string, or raise ConfigError if it is not set."""
    value = (settings or get_settings()).database_url
    if value is None or not value.get_secret_value():
        raise ConfigError("DATABASE_URL is not set (see .env.example)")
    return value.get_secret_value()


def require_test_database_url(settings: Settings | None = None) -> str:
    """Return TEST_DATABASE_URL as a plain string, or raise ConfigError if it is not set."""
    value = (settings or get_settings()).test_database_url
    if value is None or not value.get_secret_value():
        raise ConfigError("TEST_DATABASE_URL is not set (see .env.example)")
    return value.get_secret_value()
