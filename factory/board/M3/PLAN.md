# Milestone 3 plan: lens-agnostic sensors and replay-safe `documents`

status: **approved** (orchestrator, 4 Oct 2026, per founder delegation; PF1-PF3 run 4 Oct, no contradictions; PF4 pending TAVILY_API_KEY)
date: 2026-10-04
baseline: `main` at c270dc6 (gate green: 415 passed, 22 deselected; migration head 0003).
`northvaine/sensors/` holds only an empty `__init__.py`. No document persistence code exists;
`httpx` is a dev-only dependency; `TAVILY_API_KEY` is not in `.env`; `sources.name` has no
unique key.
research:
- `docs/integrations/ted-search-api-v3-request-response-contract-beyond-what-the-2026-10-03-probe-confirmed-.md` (TED note)
- `docs/integrations/tavily-api-search-extract-not-yet-in-docs-integrations.md` (Tavily note)
- `docs/integrations/uk-find-a-tender-ocds-api-only-if-the-founder-picks-a-uk-market-sample-client-.md` (FTS note, conditional)
- `docs/integrations/signal-availability-probe-2026-10-03.md`

## Goal

Lens-agnostic sensors that turn public sources into replay-safe `documents` snapshots with a
trusted `available_at`:

- **TED Search API v3** is the primary sensor. Contract notices (`cn-standard`) are the
  enumerable pricing window; award notices (`can-standard`) are account intelligence. Notices
  join on `procedure-identifier`; messy dates are validated and flagged, never trusted or
  corrected (D27-D29).
- **Tavily** is the second sensor: the specification/announcement stream, which cannot be
  enumerated (D30).
- **Safe fetch** and a **website snapshot sensor** come with it (rules #7, #9).
- Everything is proven with **recorded** fixtures for 2-3 very different sample clients, with
  **no code change between them** (D33). Nothing is built on planning.data.gov.uk (D32).

## Preconditions for approving this board

1. **Founder confirms the 2-3 sample clients** (question Q1). T3.1 writes their specs and their
   industry words into `factory/banned_terms.txt`; it cannot start without them.
2. **Orchestrator pre-flight, before wave 0** (results appended to the TED/Tavily notes with the
   date and redacted raw responses):

| # | Probe | Cost | Settles |
|---|---|---|---|
| PF1 | one TED search requesting exactly `TED_SAFE_FIELDS` (list below), 1.5 s pacing | free | every field name is accepted (a bad one gives 400 listing all 1830); the shape of `notice-version`, `notice-identifier`, `notice-subtype`, `total-value` |
| PF2 | one TED search for a notice with `notice-version` > 1 (or `notice-type=can-modif`) | free | whether search returns all versions or only the latest, and which `publication-date` a change notice carries (replay-leak risk, D36) |
| PF3 | one TED query with a single-value `IN (x)` and one with `buyer-country IN (AAA BBB)` | free | the canonical query grammar T3.0a freezes (single value uses `=`; multi uses `IN`) |
| PF4 | one Tavily `/search` with the T3.0a body (`topic=general`, `include_published_date=true`, `country="<lowercase english name>"`) | 1 credit, needs `TAVILY_API_KEY` | the real `published_date` format and share, and that the country name form is accepted |

   If PF1-PF3 contradict the frozen request shape below, the architect revises T3.0a before
   approval. PF4 is skipped (and T3.5 blocks) if the founder does not add the key.
3. **Mechanical check (FACTORY §2 rule 9)** on the T3.0a branch: `pytest -m "not live and not db"`
   and every failure is in a T3.0a-owned file.
4. The orchestrator writes D35-D44 (below) into `docs/DECISIONS.md` and the parked items into
   `docs/LATER.md` before wave 1. No ticket writes those files.

## Waves

| Wave | Tickets | Why here |
|---|---|---|
| - | pre-flight PF1-PF4, DECISIONS/LATER entries | gates the build |
| 0 | **T3.0a** contracts (models, migration 0004, settings, pure request builders, `parse_date`, ISO tables, skeletons) · **T3.0b** record/replay transport | disjoint writes; T3.0b is self-contained |
| 1 | **T3.1** sample-client specs + live recorder + banned terms · **T3.2** safe fetch + HTML text + robots + website sensor · **T3.3** document store + replay gate (db) | disjoint writes; all need only wave 0 |
| - | **orchestrator runs `tasks.py record-sensors -- --yes`**, reviews the diff by eye (contacts, sole traders), commits `tests/fixtures/sensors/{ted,tavily}/` | only the orchestrator has `.env` and network |
| 2 | **T3.4** TED sensor + date validation + procedure linking · **T3.5** Tavily sensor | parse the real recorded responses |
| 3 | **T3.6** registry + multi-client generality + replay-leakage suite (test engineer) | needs every sensor |

Eight tickets. The draft's T3.0 was split (critique nit; M2's T2.0 blocked twice at that size):
the record/replay transport is its own wave-0 ticket with disjoint writes.

### Changes from the draft (critique and research)

- **Request builders are frozen code, not literal fixtures.** The draft had T3.1 hand-write
  request bodies that T3.4/T3.5 then had to reproduce byte for byte (the "request-shape drift"
  risk). Now T3.0a fully implements the pure `ted.build_request` and
  `tavily.build_search_request` from confirmed facts; the recorder calls them, and the recorded
  exchanges carry the bodies. Drift is impossible by construction. `tests/fixtures/sensors/requests/`
  is dropped.
- **`dates.parse_date` / `parse_datetime` are implemented in T3.0a** (blocking finding: T3.5
  depended on a same-wave stub). T3.4 implements only `validate_notice_dates` and
  `available_at_for_publication`.
- **Availability rule restated** (blocking finding). Non-official tiers: `available_at <= fetched_at`.
  Official tier: `available_at` may be later than `fetched_at`, but needs `published_on` and must
  be `>=` 00:00 UTC of `published_on + 1 day`. Named test: a TED notice fetched on its publication day.
- **`ted_availability_lag_days`** (default 1, min 1) is a setting; D36 is provisional until the
  indexing lag is measured (hourly poll parked in LATER).
- **Versions:** `notice-version` goes into meta; the TED sensor de-duplicates on
  (`publication-number`, `notice-version`); every notice, change or not, is dated by its own
  `publication-date`. Unconfirmed params (`scope`, `onlyLatestVersions`, `checkQuerySyntax`) are never sent.
- **Pagination:** PAGE_NUMBER mode only (window 15000 is far above `sensor_max_results`).
  Stop on an empty page, when unique notices reach `totalNoticeCount`, or at `max_results`;
  de-duplicate. ITERATION mode is parked (it never returns a null token).
- **Pacing:** `ted_min_interval_seconds` = 1.5. The recorder and the TED sensor both pace. An
  nginx HTML 429 with no `Retry-After` maps to `SensorRateLimited(retry_after=None)`.
- **PII:** the TED `fields` requested are exactly `TED_SAFE_FIELDS` (the research allow-list); a
  test proves no field matches `email|tel|fax|person|contact-point|ubo|internet-address`.
  `links` is stripped before writing a fixture. Sole-trader winners are caught by the
  orchestrator's by-eye review.
- **Tavily specifics:** `include_published_date=true`; `days` is never sent; `country` only with
  `topic=general` and exactly one country (lowercase English name from the ISO table), else
  omitted and the reason put in `notes`; null/unparseable `published_date` gives
  `published_on=None` + a flag.
- **Country codes:** `SensorQuery.countries` stays ISO 3166-1 alpha-2; TED needs alpha-3 and
  Tavily needs an English name. T3.0a adds an ISO 3166 table (data, `core/iso3166.csv`) and two
  helpers in `core/standards.py`.
- **Banned terms** move from T3.0 to T3.1, which owns the client specs.
- **Generality literal check** is defined precisely (AST string constants; exclusions documented).

## Frozen contracts

Wave 0 lands these. Everything marked *(impl)* is fully implemented in wave 0; everything else
is a signature with a docstring and a `NotImplementedError` body. Contract tests check shape only.

```
core/standards.py (T3.0a, impl)
  iso2_to_iso3(code: str) -> str            # 'DE' -> 'DEU'; KeyError on unknown
  iso2_to_name(code: str) -> str            # 'GB' -> 'united kingdom' (lowercase English short name)
  data: core/iso3166.csv  (alpha2,alpha3,name) - every ISO 3166-1 country

core/models.py (T3.0a)
  DocumentRow  += external_id: str | None, group_key: str | None, meta: dict

core/settings.py (T3.0a)
  fetch_timeout_seconds=15, fetch_max_bytes=5_000_000, fetch_max_redirects=5,
  fetch_user_agent, fetch_deny_hosts=["linkedin.com", ...], ted_api_url (probe-confirmed URL),
  ted_min_interval_seconds=1.5, ted_availability_lag_days=1 (>=1), ted_extreme_lag_days=365,
  tavily_api_url="https://api.tavily.com", tavily_api_key: SecretStr | None,
  tavily_max_calls_per_run=20, sensor_max_results=250

sensors/base.py (T3.0a, impl)
  DateFlag(StrEnum): deadline_before_publication, decision_after_publication, extreme_lag,
                     missing_publication, unparseable, multiple_values, claimed_date_untrusted
  SensorQuery    schema_ver=1; kinds: list[EventType]; codes: list[str] ('cpv:NNNNNNNN',
                 regex ^[a-z0-9]+:[A-Za-z0-9.\-]+$); countries: list[ISO2]; languages: list[ISO639-1];
                 text: str | None; published_from/published_to: date | None (from <= to);
                 max_results: 1..settings.sensor_max_results
  SensorDocument source, tier: SourceTier, url, title, text, content_hash, language,
                 published_on: date | None, fetched_at (tz-aware), available_at (tz-aware | None),
                 external_id, group_key, meta: dict, date_flags: list[DateFlag]
                 availability rule: see "Changes" above
  SensorResult   documents, next_cursor: str | None, truncated: bool, enumerable: bool, notes: list[str]
  Sensor         runtime-checkable Protocol; ClassVar name: str, tier: SourceTier, enumerable: bool;
                 async search(query, *, as_of: datetime | None = None, cursor: str | None = None) -> SensorResult
  errors         SensorError > FetchBlocked, RobotsDisallowed, SensorRateLimited(retry_after: float | None),
                 ReplayUnsupported, LeakageError        (ConfigError is imported from core/settings.py)
  content_hash(text: str) -> str            # sha256 hex of whitespace-normalized text

sensors/replay.py (T3.0b, impl)
  RecordedExchange   method, url, request_json | None, status, headers (allow-listed subset),
                     body_json | None, body_text | None, recorded_at
  load_exchanges(path) -> list[RecordedExchange];  save_exchanges(path, exchanges) -> None
  replay_transport(exchanges, *, match_body=True) -> httpx.MockTransport
                     # matches method+url(+parsed JSON body); unmatched -> ReplayMismatch (never network)
  RecordingTransport(inner: httpx.AsyncBaseTransport)   .exchanges: list[RecordedExchange]
  ReplayMismatch(AssertionError)

sensors/dates.py
  parse_date(value: str | None) -> date | None          (T3.0a, impl) calendar date as written;
  parse_datetime(value: str | None) -> datetime | None  (T3.0a, impl) tz-aware or None; never raises
  validate_notice_dates(publication, deadlines, decisions, *, extreme_lag_days) -> list[DateFlag]   (T3.4)
  available_at_for_publication(d: date, *, lag_days: int = 1) -> datetime                          (T3.4)

sensors/ted.py
  TED_SAFE_FIELDS: tuple[str, ...]          (T3.0a, impl) exactly the research allow-list:
     publication-number, notice-type, notice-subtype, notice-version, notice-identifier,
     procedure-identifier, publication-date, deadline-receipt-request, winner-decision-date,
     buyer-name, buyer-country, winner-name, winner-country, classification-cpv, notice-title,
     estimated-value-lot, total-value
  TED_KIND_TO_NOTICE_TYPES: dict[EventType, tuple[str, ...]]   (T3.0a, impl)
     tender_published -> ("cn-standard",), contract_awarded -> ("can-standard",)
  TED_MAX_LIMIT = 250
  build_request(query, *, as_of=None, page=1, settings=None) -> dict      (T3.0a, impl)
  render_notice_text(record: dict) -> str                                  (T3.4)
  parse_notice(record: dict, *, fetched_at: datetime, settings=None) -> SensorDocument   (T3.4)
  class TedSensor(client: httpx.AsyncClient | None = None, settings=None, sleep=None)    (T3.4)

sensors/procedures.py (T3.4)
  ProcedureTimeline  group_key, tender_published_on, deadline, winner_decision_on, award_published_on,
                     tender_to_deadline_days, deadline_to_decision_days, decision_to_award_days, flags
  group_by_procedure(docs) -> dict[str, list[SensorDocument]]
  procedure_timeline(docs) -> ProcedureTimeline

sensors/tavily.py
  build_search_request(query, *, settings=None) -> tuple[dict, list[str]]   (T3.0a, impl) body + notes
  parse_result(result: dict, *, fetched_at: datetime) -> SensorDocument     (T3.5)
  class TavilySensor(client=None, settings=None)                             (T3.5)

sensors/fetch.py (T3.2)
  FetchedPage   url, final_url, status, content_type, text, fetched_at
  Resolver = Callable[[str], Awaitable[list[str]]]
  is_public_ip(addr: str) -> bool;  host_denied(host: str, deny_hosts: Sequence[str]) -> bool
  async safe_fetch(url, *, client=None, resolver=None, settings=None) -> FetchedPage
  class RobotsCache: async allowed(url, *, client=None, resolver=None, settings=None) -> bool

sensors/html_text.py (T3.2)
  html_to_text(html: str) -> tuple[str | None, str];  extract_links(html: str, base_url: str) -> list[str]

sensors/website.py (T3.2)
  class WebsiteSensor(client=None, resolver=None, settings=None)
     async snapshot(url, *, max_pages=10) -> SensorResult;  search(...) as the protocol

core/documents.py (T3.3)
  SaveResult(inserted: int, unchanged: int)
  async ensure_source(session, name, tier) -> UUID
  async save_documents(session, docs, *, workspace_id=None) -> SaveResult
  async documents_available_as_of(session, as_of, *, source_names=None, group_key=None, limit=500) -> list[DocumentRow]
  assert_available(docs, as_of) -> None      # raises LeakageError

sensors/registry.py (T3.6)
  SENSOR_NAMES: tuple[str, ...];  get_sensor(name, *, client=None, settings=None) -> Sensor
```

### Canonical TED request (frozen in T3.0a, confirmed by PF1-PF3)

```
clauses, in this order, joined by " AND ":
  1. notice types   from TED_KIND_TO_NOTICE_TYPES over query.kinds (order kept, de-duplicated);
                    no mappable kind -> ValueError
  2. classification-cpv   codes with scheme 'cpv', prefix stripped, order kept; omitted if none
  3. buyer-country        countries via iso2_to_iso3; omitted if none
  4. publication-date>=yyyyMMdd     if published_from
  5. publication-date<=yyyyMMdd     min(published_to, as_of_utc_date - ted_availability_lag_days) when as_of set
one value -> "field=v"; several -> "field IN (v1 v2)"
body = {"query": ..., "fields": list(TED_SAFE_FIELDS), "limit": min(TED_MAX_LIMIT, max_results), "page": page}
query.text and non-cpv codes are ignored by TED in M3 (listed in the docstring)
```

### Canonical Tavily search request (frozen in T3.0a)

```
{"query": query.text (required, ValueError if None), "topic": "general", "search_depth": "basic",
 "max_results": min(20, max_results), "include_raw_content": "text",
 "include_published_date": true, "include_usage": true}
 + "start_date"/"end_date" (YYYY-MM-DD) from published_from/to when set
 + "country": iso2_to_name(c) only when exactly one country; otherwise omitted and a note added
never sent: days, auto_parameters, the API key (it goes only in the Authorization: Bearer header)
```

## Decisions proposed (orchestrator writes them to DECISIONS.md before wave 1)

- **D35** Sensors speak a generic query language (`SensorQuery`: EventType kinds, scheme-prefixed
  codes, ISO 3166-1 alpha-2 countries, ISO 639-1 languages, free text, a date range). Each sensor
  maps it to its own vocabulary inside its module; client values exist only as data (rule #1, D33).
- **D36 (provisional)** TED `available_at` = 00:00 UTC of `publication-date + ted_availability_lag_days`
  (default 1), derived only from `publication-date`. Deadlines and decision dates are stored, never
  used for availability (D29). Provisional until the API indexing lag is measured by an hourly poll.
- **D37** Live web and Tavily documents get `available_at = fetched_at`; claimed dates go to
  `published_on` flagged `claimed_date_untrusted`. Sensors raise `ReplayUnsupported` for an
  `as_of` they cannot honour (ARCHITECTURE §23).
- **D38** Messy dates are flagged with `DateFlag` values stored on the document, never dropped or
  corrected (D29).
- **D39** A notice's document text is a deterministic plain-text rendering of its PII-free search
  record, so code quote checks (rule #2) have real text; the structured fields live in
  `documents.meta` (`schema_ver` 1). Raw TED XML is never persisted.
- **D40** Migration 0004: `documents.external_id`, `documents.group_key`, `documents.meta jsonb`,
  indexes on (source_id, group_key), (source_id, external_id), (available_at), and
  `UNIQUE (sources.name)`. Sources stay **global provider rows** ('ted', 'tavily', 'website',
  'order_history'); privacy lives in `documents.workspace_id`, not in sources. Before `migrate`
  on production, the orchestrator checks `SELECT name FROM sources GROUP BY name HAVING count(*) > 1`.
- **D41** Every sensor declares `enumerable`, carried on every `SensorResult`. Recall and
  coverage are reported only for enumerable sensors (D30).
- **D42** Sensor fixtures are recorded once from the live API by the orchestrator through T3.1's
  recorder, redaction first, and are never hand-written. Synthetic HTML is allowed only for
  fetch/SSRF/robots/website tests, which test our own code, not an API shape.
- **D43** Sensor HTTP uses `httpx` (promoted to a runtime dependency), called directly. No Tavily SDK.
- **D44** TED requests only the research allow-list of fields (`TED_SAFE_FIELDS`), paces at
  >= 1.5 s, uses PAGE_NUMBER pagination, de-duplicates on (publication-number, notice-version),
  and never sends unconfirmed body parameters.

## How the invariants are kept

- **#1 nothing hardcoded:** query vocabulary is generic; CPV codes, countries and words live in
  `tests/fixtures/clients/*.json`; T3.1 adds the sample clients' industry words to
  `factory/banned_terms.txt`; T3.6 asserts no client value is a string literal in `northvaine/`.
  The TED kind map is a generic EventType -> TED notice-type table.
- **#2 no source, no claim:** every document carries `text` + `content_hash`; Tavily snippet-only
  results are marked `meta.text_kind='snippet'` so the M4 verifier can refuse them.
- **#7 untrusted content:** sensors never call an LLM; fetched text is stored as data; an
  injected-instruction page is a named test.
- **#8:** no LLM in M3.
- **#9 no forbidden scraping:** `fetch_deny_hosts` (LinkedIn) and robots.txt before any website fetch.
- **Replay (ARCH §4/§11):** SQL filter plus a pure `assert_available` in code; Tavily and the
  website sensor refuse `as_of`.
- **No secrets/PII in repo:** recorder redaction refuses to write if an email or phone survives;
  orchestrator reviews by eye.

## Risks

1. **Fixtures before parsers.** Wave 2 waits for the orchestrator's recording run. TED is free,
   but Tavily needs `TAVILY_API_KEY` (not in `.env`). Without it T3.5 blocks and the
   announcement half of the generality demo has no data.
2. **Personal data in a public repo.** Contact fields are never requested (allow-list), `links`
   is stripped, the recorder refuses to write on a surviving email/phone, and the orchestrator
   reviews the diff by eye. Residual: a sole-trader `winner-name` or a person in `notice-title`;
   choose fixtures from companies and public bodies.
3. **D36 rests on an unmeasured fact.** The OJ S time of day and the API indexing lag are not
   documented. If indexing lags past 00:00 UTC D+1, replay could show notices live search could
   not yet return. Mitigation: `ted_availability_lag_days` setting; hourly poll in LATER.
4. **Change notices.** Whether search returns all versions, and how a change notice is dated, is
   unconfirmed (PF2). If a change carries the original `publication-date`, replay leaks the
   updated content. PF2 must answer it before approval; otherwise raise the lag or exclude
   `notice-version > 1` from replay.
5. **TED rate limits.** A ~14-call burst got an nginx 429; 1.5 s pacing worked for 30 calls. The
   recorder and sensor pace; nightly backoff policy belongs to M5.
6. **Tavily country names and dates.** The accepted country-name list is not published; PF4
   checks one. `published_date` format is unspecified; if the recorded fixtures carry a format
   `parse_date` cannot read, T3.5 records `published_on=None` + `unparseable` and files a contract
   change request (dates.py is T3.4's in wave 2).
7. **T3.0a size.** Still the biggest ticket (models, migration, settings, two pure request
   builders, date parsing, ISO table, skeletons, DDL test ownership). The replay transport was split
   out; the mechanical check is a precondition of approval.
8. **UNIQUE(sources.name)** is harmless on an empty table; production must be checked for
   duplicates before `migrate` (D40).
9. **SSRF via DNS rebinding.** `safe_fetch` checks the resolved IPs, but httpx resolves again on
   connect. Acceptable for the hackathon (the website sensor fetches only client-given or
   same-domain URLs); IP pinning is parked.
10. **Tavily snippet-only content** is weak evidence; M5 quality on the announcement stream depends
    on `raw_content` being present.

## Questions for the founder

**Answered 4 Oct 2026:** Q1 = the proposed three clients (A, B, C), no Find a Tender sensor in M3.
Q2 = pending (founder to add `TAVILY_API_KEY`; blocks PF4 and the T3.1 recording run only).
Q3 = approved by the orchestrator. Q4 = yes, commit redacted TED and Tavily fixtures.

1. **Which 2-3 sample clients?** Proposed, very different (D22/D33): (A) an overseas natural-stone
   supplier into the UK and EU (works-consumption, heavy TED); (B) an EU cold-chain/refrigeration
   equipment maker selling EU-wide (product and works CPVs, multilingual); (C) a packaging supplier
   to private cosmetics brands (announcement stream only, the honest weak case). If any client
   sells into the UK, should a Find a Tender (UK OCDS) sensor join M3 as a wave-2 ticket? The UK is
   not in TED after 2020 (FTS note: free, no auth, OGL v3.0).
2. **`TAVILY_API_KEY`** is not in `.env`. Please add it (free tier, 1,000 credits/month; the
   recording run uses well under 30).
3. **Approve migration 0004** (D40): `documents.external_id`, `group_key`, `meta jsonb`, indexes,
   and `UNIQUE (sources.name)` with sources kept global.
4. **OK to commit redacted, contact-free fixtures** to the public repo? TED notices are freely
   reusable (Decision 2011/833/EU; attribution "Source: TED, Publications Office of the European
   Union, ted.europa.eu" goes in the fixture README). Tavily's terms neither allow nor forbid it;
   fixtures are small, keyless, without `request_id`.

## Parked (orchestrator copies to docs/LATER.md)

- Find a Tender / Contracts Finder (UK) sensor: only if Q1 picks a UK-market client (then a
  wave-2 ticket); otherwise M5+.
- TED notice types beyond cn-standard/can-standard (`cn-social`, `veat`, `can-modif`, `pin-only`)
  in `TED_KIND_TO_NOTICE_TYPES`; TED ITERATION pagination; place-of-performance country filter;
  TED text (`~`) queries.
- Hourly poll to measure the TED indexing lag (D36 provisional).
- Companies House, SEC EDGAR, SAM.gov registry sensors (M4/M5 or later).
- Award winners -> `companies` rows (entity resolution, the D20 award->winner hop): M4/M5.
- Planning portals / planning.data.gov.uk (D32).
- Fetching TED notice XML/HTML for free-text scope and per-lot winners (strip contacts first).
- Tavily `/extract`; Tavily credit ledger alongside `llm_calls`.
- Archived web snapshots (Wayback) to make web documents replay-safe.
- Wiring sensors into the nightly `discover` job and per-provider concurrency caps: M5.
- Gate persisting rejected sellers with `rejected_as`: M4/M5.
- DNS pinning in `safe_fetch` (rebinding protection).

## Tickets

| id | title | wave | role | depends_on |
|---|---|---|---|---|
| T3.0a | Sensor contracts: models, migration 0004, settings, request builders, date parsing, skeletons | 0 | builder | - |
| T3.0b | Record/replay HTTP transport for sensor tests | 0 | builder | - |
| T3.1 | Sample-client specs, banned terms and the live fixture recorder | 1 | builder | T3.0a, T3.0b |
| T3.2 | Safe fetch, HTML-to-text, robots.txt and the website snapshot sensor | 1 | builder | T3.0a |
| T3.3 | Document store and the available_at replay gate | 1 | builder | T3.0a |
| T3.4 | TED sensor: notices to documents, date validation, procedure linking | 2 | builder | T3.0a, T3.0b, T3.1 |
| T3.5 | Tavily sensor: the non-enumerable announcement stream | 2 | builder | T3.0a, T3.0b, T3.1 |
| T3.6 | Sensor registry, multi-client generality and replay-leakage suite | 3 | test-engineer | T3.2, T3.3, T3.4, T3.5 |
