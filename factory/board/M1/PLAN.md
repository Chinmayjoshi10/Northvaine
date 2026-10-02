# Milestone 1 plan: a correct, Windows-friendly substrate

status: proposed (waiting for founder approval)
baseline: `main` at dec7f58. schema.sql, pyproject.toml and northvaine/ are unchanged since
e141b6d, so "schema.sql at e141b6d" and "schema.sql at dec7f58" are the same bytes.

## Goal

Make the partial skeleton correct and usable on Windows without `make`:
- a valid uv / Python 3.12 toolchain;
- typed settings that never need a `.env` to import;
- a lazy async DB engine that works with hosted Postgres URLs (sslmode, poolers);
- the canonical schema plus the ARCHITECTURE §21 changes, applied through Alembic;
- Pydantic models that mirror the schema;
- a Postgres-backed jobs queue with leases, retries and stale-lease recovery;
- a task runner (`scripts/tasks.py`) and a Makefile that only delegates to it;
- a gate that stays green with no Postgres on the machine.

Unit tests never need a database. Every DB test is marked `db`, skips unless
`TEST_DATABASE_URL` is set, and runs with `uv run python scripts/tasks.py db-test`.
**The milestone is not signed off until db-test has passed against a real Postgres 16
with pgvector** (see Risks).

## Defects found on main (why this milestone exists)

| # | Defect | Fixed by |
|---|---|---|
| a | `build-backend = "setuptools.backends._legacy:_Backend"` does not exist, so `uv run` cannot build the project at all (confirmed in docs/integrations/uv-packaging.md) | T1.0 |
| b | `readme = "README.md"` points to a missing file | T1.0 |
| c | Dev tools are in `[project.optional-dependencies]`, which `uv run` does not install | T1.0 |
| d | Later-milestone runtime deps (openai, tavily-python, pdfplumber, tenacity, python-dotenv, httpx) | T1.0 |
| e | `core/__init__.py` builds `Settings()` at import with guessed model ids and EMBED_DIM; `core/db.py` builds an engine at import and imports a name that is not a module | T1.0, T1.2 |
| f | ruff and mypy target Python 3.11 | T1.0 |
| g | No Alembic setup, no `db` test marker | T1.0, T1.1 |
| h | `document_chunks.embedding` and `theses.embedding` are `vector(1024)`, a guessed dimension | T1.4 |

## Waves

```
wave 0  T1.0 contracts + toolchain (alone; every worktree's gate is broken until it merges)
wave 1  T1.1 alembic + v1 baseline   T1.2 db engine   T1.3 task runner
wave 2  T1.4 migration 0002 + schema.sql v2 (needs T1.1, T1.2)   T1.5 gate extensions (needs T1.1)
wave 3  T1.6 row/enum models (needs T1.4)   T1.7 jobs queue (needs T1.2, T1.4)
wave 4  T1.8 consistency + live-schema tests (test engineer; needs T1.3..T1.7)
```

| Ticket | Title | Role | Lane | Wave | Depends on |
|---|---|---|---|---|---|
| T1.0 | Fix toolchain, freeze M1 contracts | builder | infra | 0 | none |
| T1.1 | Alembic scaffold, SQL splitter, frozen v1 baseline (0001) | builder | data | 1 | T1.0 |
| T1.2 | Lazy async engine, URL normalization, DB health | builder | backend | 1 | T1.0 |
| T1.3 | Windows task runner and Makefile shim | builder | infra | 1 | T1.0 |
| T1.4 | Migration 0002 (§21) and schema.sql v2 end state | builder | data | 2 | T1.1, T1.2 |
| T1.5 | Gate: offline migration render, invariant scan of SQL | builder | infra | 2 | T1.1 |
| T1.6 | Pydantic row and enum models for schema v2 | builder | data | 3 | T1.4 |
| T1.7 | Jobs queue: claim, lease, retry, recovery, worker | builder | backend | 3 | T1.2, T1.4 |
| T1.8 | Consistency and live-schema tests | test-engineer | data | 4 | T1.3, T1.4, T1.5, T1.6, T1.7 |

Write scopes are disjoint inside every wave (listed in each ticket). Shared files:
- `pyproject.toml`, `uv.lock`, `core/settings.py`: T1.0 only.
- `schema.sql`: T1.4 only.
- `core/models.py`: T1.0 creates the contract types. T1.6 (wave 3, the only writer in its
  wave) adds row models and enums but must not change the T1.0 types.
- `.gitattributes`, `CLAUDE.md`: no ticket writes these. They are integrator or orchestrator
  edits at retro (see Decisions 11).

The critique's split is applied. The draft's single T1.1 is now T1.1 (scaffold + 0001) and
T1.4 (0002 + schema.sql), so each stays near the 400-line guideline. The frozen 272-line SQL
copy in T1.1 is checked by hash, not line by line.

---

## Frozen contracts (landed by T1.0; changes need a contract change request)

### `northvaine/core/settings.py`

```python
class ConfigError(RuntimeError): """A required setting is missing or invalid; message names the variable."""

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        extra="ignore", env_ignore_empty=True, case_sensitive=False,
    )
    # database
    database_url: SecretStr | None = None
    test_database_url: SecretStr | None = None
    db_pool_mode: Literal["session", "transaction"] = "session"
    db_pool_size: int = 5            # ge=1
    db_max_overflow: int = 10        # ge=0
    db_echo: bool = False
    test_db_isolation: Literal["database", "reuse"] = "database"
    # LLM + sensors (values confirmed in M2; no defaults, no guesses)
    nebius_api_key: SecretStr | None = None
    nebius_base_url: str | None = None
    model_fast: str | None = None
    model_mid: str | None = None
    model_deep: str | None = None
    model_embed: str | None = None
    embed_dim: int | None = None     # ge=1 when set
    tavily_api_key: SecretStr | None = None
    daily_budget_usd: Decimal | None = None   # founder question 6
    # queue
    job_lease_seconds: int = 300     # ge=1
    job_max_attempts: int = 5        # ge=1
    job_backoff_base_seconds: float = 30.0
    job_backoff_max_seconds: float = 3600.0

def get_settings() -> Settings: ...                 # functools.lru_cache(maxsize=1); tests call get_settings.cache_clear()
def require_database_url(settings: Settings | None = None) -> str: ...       # ConfigError("DATABASE_URL is not set ...")
def require_test_database_url(settings: Settings | None = None) -> str: ...  # ConfigError("TEST_DATABASE_URL is not set ...")
```

`northvaine/core/__init__.py` becomes a docstring only, with no `Settings()` at import.

### `northvaine/core/db.py` (stubs in T1.0, implemented by T1.2)

```python
@dataclass(frozen=True)
class NormalizedUrl:
    url: str                       # postgresql+asyncpg://..., libpq-only query keys removed
    connect_args: dict[str, Any]   # e.g. {"ssl": "require"} or {"ssl": <SSLContext>}

@dataclass(frozen=True)
class DatabaseStatus:
    server_version: str
    server_version_num: int
    has_vector: bool
    has_pgcrypto: bool

def normalize_database_url(raw: str) -> NormalizedUrl: ...
def redact_url(raw: str) -> str: ...                     # password replaced by "***"
def create_engine(url: str | None = None, *, settings: Settings | None = None) -> AsyncEngine: ...
def get_engine() -> AsyncEngine: ...                     # lazy module singleton
def get_sessionmaker() -> async_sessionmaker[AsyncSession]: ...
@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]: ...   # commit on success, rollback on error
async def get_db() -> AsyncIterator[AsyncSession]: ...           # FastAPI dependency
async def dispose_engine() -> None: ...                          # no-op when no engine exists
async def check_database(engine: AsyncEngine | None = None) -> DatabaseStatus: ...
def main() -> int: ...                                           # `python -m northvaine.core.db`
```

### `northvaine/core/queue.py` (stubs in T1.0, implemented by T1.7)

Queue functions never commit. The caller owns the transaction. `run_worker` uses one
`session_scope()` for the claim and a separate one for the finish, so a claim is committed
before its handler runs.

```python
Handler = Callable[[Job], Awaitable[None]]

@dataclass(frozen=True)
class StaleResult:
    requeued: int
    failed: int

async def enqueue(session: AsyncSession, job: NewJob) -> int: ...
async def claim(session: AsyncSession, worker_id: str, kinds: Sequence[str] | None = None) -> Job | None: ...
async def heartbeat(session: AsyncSession, job_id: int, worker_id: str) -> bool: ...
async def complete(session: AsyncSession, job_id: int, worker_id: str) -> bool: ...
async def fail(session: AsyncSession, job_id: int, worker_id: str, error: str) -> bool: ...
async def requeue_stale(session: AsyncSession, lease_seconds: int | None = None) -> StaleResult: ...
def backoff_delay(attempts: int, *, base_seconds: float | None = None, max_seconds: float | None = None) -> timedelta: ...
async def run_worker(
    handlers: Mapping[str, Handler], worker_id: str, *,
    once: bool = False, poll_seconds: float = 1.0,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int: ...                                            # returns jobs processed
```

`heartbeat`, `complete` and `fail` only affect a row
`WHERE id = :id AND status = 'running' AND locked_by = :worker_id`. They return False when no
row matched, which means the lease was lost. Handlers must be idempotent. A long handler must
call `heartbeat` more often than `job_lease_seconds`.

### `northvaine/core/models.py` (T1.0 part, frozen)

```python
class NorthvaineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class JobStatus(StrEnum): QUEUED="queued"; RUNNING="running"; DONE="done"; FAILED="failed"

class NewJob(NorthvaineModel):
    kind: str                          # ^[a-z][a-z0-9_]*$, max 64 chars
    payload: dict[str, Any] = {}
    run_after: datetime | None = None  # None = now (DB default)
    max_attempts: int | None = None    # ge=1; None = settings.job_max_attempts
    workspace_id: UUID | None = None

class Job(NorthvaineModel):            # mirrors the v2 jobs row exactly; also serves as JobRow
    id: int; kind: str; payload: dict[str, Any]; status: JobStatus
    attempts: int; max_attempts: int; run_after: datetime
    locked_at: datetime | None; locked_by: str | None; error: str | None
    workspace_id: UUID | None; created_at: datetime; finished_at: datetime | None

class EventType(StrEnum):   # exactly the 12 generic types of SPEC §1, each with a docstring comment
    FACILITY_OPENED, CONTRACT_AWARDED, TENDER_PUBLISHED, HIRING_SURGE, LEADERSHIP_CHANGE,
    PRODUCT_LAUNCH, MARKET_ENTRY, TRADE_MEASURE, WEBSITE_CHANGE, REORDER_DUE, QUOTE_STALE,
    INBOUND_QUESTION   (values are the lowercase snake strings)
```

### Test fixtures (`tests/conftest.py`, T1.0)

- `clean_settings`: deletes every Settings env var with monkeypatch, patches `get_settings`
  to return `Settings(_env_file=None)`, and clears the cache before and after. Every test that
  needs "no URL" uses it, so a developer's `.env` cannot leak in.
- `test_database_url`: returns `require_test_database_url()`, or calls `pytest.skip("db: set
  TEST_DATABASE_URL")`.
- An autouse fixture for tests marked `db` only. It depends on `test_database_url` and awaits
  `dispose_engine()` in teardown, so no engine is reused across event loops.
- pytest config: `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`,
  `asyncio_default_test_loop_scope = "function"`, markers `live`, `golden`, `db`.

### Migration helpers (T1.1)

`northvaine/core/sqlsplit.py: split_sql(text: str) -> list[str]`. It removes `--` comments
outside quotes and splits on top-level `;`, respecting single quotes, double quotes and
`$tag$` dollar quotes. It returns non-empty statements without the trailing `;`.

`tests/db/conftest.py: migrated_url` is a **sync** fixture, so the stock async `env.py` can
call `asyncio.run` safely.
- In `test_db_isolation = "database"` mode it connects to TEST_DATABASE_URL, runs
  `CREATE DATABASE nv_test_<hex>`, runs `alembic upgrade head` against it, yields the URL, then
  drops the database.
- In `"reuse"` mode (for a Neon branch, or a role without CREATEDB) it runs `downgrade base` and
  then `upgrade head` on TEST_DATABASE_URL itself. On teardown it runs `downgrade base`.

Extensions are never dropped by a downgrade.

---

## Schema v2: exact changes in migration 0002 (T1.4)

General rules:
- New tables use `uuid PRIMARY KEY DEFAULT gen_random_uuid()` unless `bigserial` is stated.
- Every `jsonb` column has a versioned Pydantic model later. Tables whose main payload is
  jsonb carry `schema_ver text NOT NULL`.
- `created_at timestamptz NOT NULL DEFAULT now()` wherever it is listed.
- `learner` columns use one CHECK list: `('world','org','buying','research','allocator')`.
- `strategy_version int NOT NULL DEFAULT 0`, where 0 means the defaults before the first
  learned version. It is not a foreign key, because shared rows have `workspace_id IS NULL`
  while `strategy_versions` keys on a non-null workspace.
- Vector columns are dimensionless `vector`. No vector indexes in M1.
- No colons in any SQL string or seed description (`sa.text` would read `:x` as a bind
  parameter).

### Changes to v1 tables

| Table | Change (upgrade) | Downgrade |
|---|---|---|
| documents | `ADD available_at timestamptz NULL` (NULL = not replay-safe) | drop column |
| document_chunks | `ALTER embedding TYPE vector` | `TYPE vector(1024)` |
| theses | `ALTER embedding TYPE vector`; `DROP alpha`, `DROP beta` (moved to beliefs) | restore `vector(1024)`; re-add `alpha/beta real NOT NULL DEFAULT 1` |
| events | `ADD concept_id uuid NULL REFERENCES event_concepts(id)`; `ADD slots jsonb NOT NULL DEFAULT '{}'`; index `events_concept (concept_id)`; `event_type` is kept as the level-0 label | drop |
| cases | `ADD pattern_id uuid NULL REFERENCES hypotheses(id)`; `ADD CONSTRAINT cases_stage_check CHECK (stage IN ('candidate','gated','investigated','briefed','approved','contacted','replied','meeting','samples','quoted','won','lost','dismissed'))`; `CREATE UNIQUE INDEX cases_open_unique ON cases (workspace_id, company_id, pattern_id, window_start) NULLS NOT DISTINCT WHERE stage NOT IN ('won','lost','dismissed')` | drop |
| outcomes | `ADD CONSTRAINT outcomes_stage_check` with the same 13-stage list | drop |
| contacts | `ADD workspace_id uuid NULL REFERENCES workspaces(id) ON DELETE CASCADE` (NULL = world-layer contact) | drop |
| jobs | `ADD created_at timestamptz NOT NULL DEFAULT now()`, `finished_at timestamptz NULL`, `max_attempts int NOT NULL DEFAULT 5 CHECK (max_attempts >= 1)`, `locked_by text NULL`, `workspace_id uuid NULL REFERENCES workspaces(id) ON DELETE CASCADE`; `DROP INDEX jobs_ready`; `CREATE INDEX jobs_claim ON jobs (run_after, id) WHERE status = 'queued'`; `CREATE INDEX jobs_lease ON jobs (locked_at) WHERE status = 'running'` | reverse, recreate `jobs_ready` |
| strategy_versions | none (snapshot content widens to all learner states + policy_params + prompt versions; JSON only) | none |

`enqueue()` passes `settings.job_max_attempts` explicitly. The DB default of 5 is only a
fallback.

### New tables

**event_concepts** (world layer)
| column | type | null | notes |
|---|---|---|---|
| id | uuid PK | no | |
| parent_id | uuid → event_concepts(id) ON DELETE RESTRICT | yes | NULL only at level 0 |
| level | int | no | CHECK level >= 0 |
| label | text | no | CHECK `label ~ '^[a-z][a-z0-9_]*$'` |
| description | text | no | |
| embedding | vector | yes | dimensionless until M2 |
| status | text | no | DEFAULT 'active', CHECK IN (active, proposed, merged, retired) |
| merged_into | uuid → event_concepts(id) | yes | set when status = merged |
| created_at | timestamptz | no | |

Constraints: `CHECK ((level = 0) = (parent_id IS NULL))`,
`UNIQUE NULLS NOT DISTINCT (parent_id, label)`.
Seed: 12 rows at level 0, one per EventType value, with these descriptions:
facility_opened "A new site, plant, yard, branch or warehouse opened or announced";
contract_awarded "A contract or tender award was made to the company";
tender_published "The company published a tender or request for proposals";
hiring_surge "A marked rise in open roles at the company";
leadership_change "A senior leader joined, left or changed role";
product_launch "The company launched or announced a product or service";
market_entry "The company entered a new region or segment";
trade_measure "A tariff, quota, duty or other trade rule changed";
website_change "A material change to the company website";
reorder_due "A past customer is due to reorder based on its history";
quote_stale "A quote was sent and has had no reply for too long";
inbound_question "A buyer or buyer agent asked a question through the Gateway".

**hypotheses** (one registry for all learners)
| column | type | null | notes |
|---|---|---|---|
| id | uuid PK | no | |
| workspace_id | uuid → workspaces ON DELETE CASCADE | yes | NULL = shared |
| learner | text | no | learner CHECK |
| kind | text | no | CHECK lowercase snake (`pattern`, `concept_split`, `program`, ...) |
| parent_id | uuid → hypotheses(id) | yes | refinement of a parent (§3.2) |
| body | jsonb | no | |
| schema_ver | text | no | |
| status | text | no | DEFAULT 'proposed', CHECK IN (proposed, exploring, exploiting, degraded, retired, rejected) (§7.4 + rejected) |
| origin | text | no | CHECK IN (llm_prior, history_mining, world_lift, error_driven, missed_opportunity, cross_org, owner) (§7.2) |
| proposed_at | timestamptz | no | DEFAULT now() |
| tests | jsonb | no | DEFAULT '[]' |
| decided_at | timestamptz | yes | |
| strategy_version | int | no | DEFAULT 0 |

Index `hypotheses_lookup (workspace_id, learner, kind, status)`.

**patterns** is a view: `CREATE VIEW patterns AS SELECT id, workspace_id, learner, parent_id,
body, schema_ver, status, origin, proposed_at, tests, decided_at, strategy_version FROM
hypotheses WHERE kind = 'pattern'`.

**playbooks** (procedural half of a thesis)
id uuid PK; workspace_id uuid NOT NULL → workspaces CASCADE; hypothesis_id uuid NULL →
hypotheses; thesis_id uuid NULL → theses (migration path); name text NOT NULL; spec jsonb NOT
NULL (buyer roles, angle, first offer, follow-up signals); schema_ver text NOT NULL; status
text NOT NULL DEFAULT 'active' CHECK IN (active, exploring, retired); pinned boolean NOT NULL
DEFAULT false; created_at.

**search_programs**
id uuid PK; workspace_id uuid NULL → workspaces CASCADE (NULL = shared); source_hypothesis
uuid NULL → hypotheses; name text NOT NULL; templates jsonb NOT NULL DEFAULT '[]'; sources
jsonb NOT NULL DEFAULT '[]'; filters jsonb NOT NULL DEFAULT '{}'; schedule jsonb NOT NULL
DEFAULT '{}'; status text NOT NULL DEFAULT 'trial' CHECK IN (active, trial, paused, retired);
yields jsonb NOT NULL DEFAULT '{}'; schema_ver text NOT NULL; created_at; updated_at
timestamptz NOT NULL DEFAULT now().

**expectations**
id uuid PK; workspace_id uuid NULL → workspaces CASCADE; company_id uuid NOT NULL →
companies; concept_id uuid NOT NULL → event_concepts; hypothesis_id uuid NULL → hypotheses;
window_start date NOT NULL; window_end date NOT NULL, CHECK (window_end >= window_start);
origin text NOT NULL (learner CHECK); status text NOT NULL DEFAULT 'pending' CHECK IN
(pending, met, missed); value numeric NULL (expected value on the allocator's scale);
met_event_id uuid NULL → events; created_at; resolved_at timestamptz NULL.
Index `expectations_open (status, window_end)`.

**beliefs**
id bigserial PK; learner text NOT NULL (learner CHECK); workspace_id uuid NULL → workspaces
CASCADE; strategy_version int NOT NULL DEFAULT 0; kind text NOT NULL (lowercase snake); key
text NOT NULL; params jsonb NOT NULL; schema_ver text NOT NULL; n_evidence real NOT NULL
DEFAULT 0 CHECK (n_evidence >= 0); prior_source text NULL; updated_at timestamptz NOT NULL
DEFAULT now().
`UNIQUE NULLS NOT DISTINCT (learner, workspace_id, strategy_version, kind, key)`.

**belief_source_calibration** (meta-calibration)
id bigserial PK; workspace_id uuid NULL → workspaces CASCADE (NULL = pooled); learner text
NOT NULL (learner CHECK); prior_source text NOT NULL (e.g. llm_strong, owner_statement,
history, cross_org); bias real NOT NULL DEFAULT 0; spread real NOT NULL DEFAULT 1 CHECK
(spread > 0); n_pairs int NOT NULL DEFAULT 0 CHECK (n_pairs >= 0); strategy_version int NOT
NULL DEFAULT 0; updated_at.
`UNIQUE NULLS NOT DISTINCT (workspace_id, learner, prior_source, strategy_version)`.

**policy_params**
id bigserial PK; workspace_id uuid NULL → workspaces CASCADE (NULL = global default); name
text NOT NULL CHECK `name ~ '^[a-z][a-z0-9_.]*$'`; default_value jsonb NOT NULL;
current_value jsonb NOT NULL; update_rule text NOT NULL ('none' while stubbed); metric text
NOT NULL; strategy_version int NOT NULL DEFAULT 0; updated_at.
`UNIQUE NULLS NOT DISTINCT (workspace_id, name)`. History lives in
`strategy_versions.snapshot`.

**decisions** (decision log with propensities, never cut)
id bigserial PK; workspace_id uuid NULL → workspaces CASCADE; kind text NOT NULL CHECK IN
(brief, search, investigation, question); case_id uuid NULL → cases ON DELETE SET NULL;
company_id uuid NULL → companies; features jsonb NOT NULL; choice jsonb NOT NULL;
value_estimate real NULL; propensity real NOT NULL CHECK (propensity > 0 AND propensity <=
1); cost_usd numeric(10,6) NOT NULL DEFAULT 0; strategy_version int NOT NULL DEFAULT 0;
created_at.
Index `decisions_log (workspace_id, kind, created_at)`.

**failure_attributions**
id uuid PK; feedback_id uuid NOT NULL → feedback ON DELETE CASCADE; code text NOT NULL
(lowercase snake, the §12 failure codes); learner text NOT NULL (learner CHECK; reasoning or
prompt failures go to `research` with component `prompt`); component text NOT NULL;
target_id text NULL (id of the belief, hypothesis, program or prompt, as text); weight real
NOT NULL DEFAULT 1 CHECK (weight > 0 AND weight <= 1); confirmed boolean NOT NULL DEFAULT
false; created_at.

**missed_opportunities**
id uuid PK; workspace_id uuid NOT NULL → workspaces CASCADE; source text NOT NULL CHECK IN
(inbound, win, public_award); company_id uuid NULL → companies; case_id uuid NULL → cases ON
DELETE SET NULL; occurred_on date NOT NULL; evidence_claim_id uuid NULL → claims;
postmortem_status text NOT NULL DEFAULT 'pending' CHECK IN (pending, not_surfaced,
surfaced_dropped, surfaced_late, surfaced_in_time) (§8.4); postmortem jsonb NOT NULL DEFAULT
'{}'; created_at; analyzed_at timestamptz NULL.

**controls** (matched controls for case-control, never cut)
id uuid PK; workspace_id uuid NOT NULL → workspaces CASCADE; hypothesis_id uuid NULL →
hypotheses ON DELETE CASCADE; positive_company_id uuid NOT NULL → companies;
control_company_id uuid NOT NULL → companies; as_of date NOT NULL (point-in-time index date);
match_on jsonb NOT NULL DEFAULT '{}'; created_at.
`CHECK (positive_company_id <> control_company_id)`; `UNIQUE NULLS NOT DISTINCT (workspace_id,
hypothesis_id, positive_company_id, control_company_id, as_of)`.

**lessons** (no lesson without a recorded change)
id uuid PK; workspace_id uuid NOT NULL → workspaces CASCADE; strategy_version int NOT NULL;
`FOREIGN KEY (workspace_id, strategy_version) REFERENCES strategy_versions(workspace_id,
version)`; learner text NOT NULL (learner CHECK); body text NOT NULL; belief_change jsonb NOT
NULL; behaviour_change jsonb NOT NULL; created_at.

**inbound_queries** (Gateway demand signal)
id uuid PK; workspace_id uuid NOT NULL → workspaces CASCADE; channel text NOT NULL (open,
like messages.channel); counterpart text NOT NULL CHECK IN (human, agent); agent_domain text
NULL; query text NOT NULL (untrusted external text); answered boolean NOT NULL DEFAULT false;
case_id uuid NULL → cases ON DELETE SET NULL; cluster_id uuid NULL; created_at.

**case_open_questions** (companion of case_evidence)
id uuid PK; case_id uuid NOT NULL → cases ON DELETE CASCADE; question text NOT NULL;
source_learner text NOT NULL (learner CHECK); hypothesis_id uuid NULL → hypotheses; status
text NOT NULL DEFAULT 'open' CHECK IN (open, answered, dropped); answer_claim_id uuid NULL →
claims; created_at; resolved_at timestamptz NULL.

Creation order in 0002: event_concepts (+ seed), hypotheses, the v1-table ALTERs, patterns
view, then the remaining tables. The downgrade runs in exact reverse.

---

## Research used (docs/integrations/, all checked 2026-10-02)

| Fact | Source file | Used by |
|---|---|---|
| Valid backends; dev group via PEP 735 is installed by `uv run`; `.python-version`; universal lock; missing readme breaks uv_build/hatchling | uv-packaging.md | T1.0 |
| async env.py shape; offline needs no DB (`dialect_name='postgresql'`); op.execute + text() binds on `:x`; asyncpg prepares every statement so multi-statement strings fail online; asyncio.run cannot run inside a running loop; alembic.ini read with the locale encoding | alembic-async.md | T1.1, T1.4, T1.5 |
| `postgres://` unsupported; bare `postgresql://` picks psycopg; `sslmode` raises TypeError, use `ssl`; pooler-safe settings (NullPool, both statement caches 0, unique prepared statement names); asyncpg 0.31 has cp312 Windows wheels; SQLAlchemy 2.1.2 current | sqlalchemy-asyncpg.md | T1.0, T1.2 |
| dimensionless `vector` allowed; HNSW/IVFFlat need a dimension; no codec registration with SQLAlchemy + asyncpg; pgcrypto trusted, vector not | pgvector.md | T1.4 |
| Nebius PG16 with vector 0.8 + pgcrypto; Neon PG14-18, pooled `-pooler` hosts in transaction mode, branches; pgvector on Windows needs a C toolchain | postgres-hosting.md | founder questions |
| SKIP LOCKED + LIMIT semantics; READ COMMITTED re-check; NULLS NOT DISTINCT is PG15+; partial unique index predicate rules; gen_random_uuid is core since PG13 | postgres-queue-semantics.md | T1.4, T1.7 |
| pytest-asyncio 1.4 loop scopes; engine across loops; pydantic-settings extra/env_ignore_empty/SecretStr | pytest-asyncio-and-pydantic-settings.md | T1.0 |

Still unconfirmed, and handled by a test rather than assumed:
- The claim query running as an InitPlan (T1.7 asserts it with EXPLAIN).
- `channel_binding` raising TypeError (T1.2 strips it anyway).
- ALTER `vector` to `vector(N)` on an empty table (M2 runs the docker check).
- Offline render with asyncpg absent (not needed: the offline env.py uses `dialect_name`).

No model ids, endpoints or prices are used in M1.

---

## Risks

1. **T1.0 is a single point of failure.** Until it merges, no worktree can `uv run`. It runs
   alone in wave 0.
2. **Hosting is undecided, so DB behaviour can stay unverified.** Online migrations, SKIP LOCKED
   concurrency, the InitPlan claim and the live schema cannot be proven until the founder
   provides TEST_DATABASE_URL. The gate is green without it, so **milestone sign-off is
   blocked on `tasks.py db-test` passing** (T1.8's last criterion). The M1 report lists the
   claim-once guarantee as unverified until then.
3. **asyncpg with poolers and libpq URL keys.** This is handled through the explicit
   `db_pool_mode` setting and a defined list of keys to strip or translate (T1.2). The Nebius
   pooler port and format are not confirmed, so pooler mode is never inferred from a Nebius URL.
4. **Running frozen SQL through Alembic.** The method is fixed: split, then run one statement
   per `op.execute(sa.text(...))`, with a test that no bind parameters appear. It does not use
   the unconfirmed raw `run_async` route.
5. **Schema drift between schema.sql, migrations and models.** T1.6 runs after T1.4 merges, and
   T1.8 adds consistency tests, including an adversarial one.
6. **§21 interpretations.** The tables above are loosely described in ARCHITECTURE. They are
   interpretations, and learner milestones may amend them with new migrations.
7. **PG version.** NULLS NOT DISTINCT needs PG15+. Both candidate hosts offer 16. On PG14 the
   unique keys would need coalesce-based indexes.
8. **Deferred embedding dimension.** M2 must ALTER to `vector(N)` and add HNSW indexes after
   EMBED_DIM is confirmed. The empty-table ALTER is still unconfirmed.
9. **Windows specifics.** Proactor loop (inferred to work, checked in db-test), npm.cmd, CRLF.
   `.gitattributes` already has `* text=auto eol=lf`, and the 0001 hash test also normalizes
   CRLF to LF before hashing. alembic.ini stays ASCII-only, and .sql files are read with
   `encoding="utf-8"`.
10. **Version drift.** SQLAlchemy 2.1.2 was released on the day of research. Pins are explicit
    with upper bounds, and setuptools.build_meta avoids tying the build to the uv version.
11. **One open case per (workspace, company, pattern, window).** With NULLS NOT DISTINCT, a
    company can have only one open case with no pattern and no window, for example inbound.
    See founder question 3.
12. **Per-worktree `uv sync` cost on Windows.** The uv cache mitigates it.

## Decisions proposed

1. Python 3.12 via uv: `.python-version` = 3.12, `requires-python = ">=3.12,<3.13"`. ruff
   targets py312. The mypy block is removed (mypy is parked).
2. Build backend `setuptools.build_meta` (`setuptools>=75`), with no `readme` field until M15.
   It is confirmed working and does not depend on the uv version.
3. Runtime deps are only the substrate, with explicit upper bounds:
   - fastapi `>=0.115,<1`
   - uvicorn[standard] `>=0.32,<1`
   - sqlalchemy[asyncio] `>=2.1.2,<2.2`
   - asyncpg `>=0.31,<0.32`
   - alembic `>=1.20,<2`
   - pgvector `>=0.5,<0.6`
   - pydantic `>=2.10,<3`
   - pydantic-settings `>=2.15,<3`

   The PEP 735 `dev` group has pytest `>=8.4,<9`, pytest-asyncio `>=1.4,<2`, ruff `>=0.8`, and
   httpx `>=0.28,<1` (test client only). openai, tavily-python, runtime httpx, pdfplumber and
   tenacity come back with the milestone that uses them. python-dotenv is dropped as a direct
   dep (pydantic-settings brings it). pytest-cov is dropped.
4. Settings never require a DB or keys at import. Secrets, including DATABASE_URL, are
   SecretStr. Model ids, base URL, EMBED_DIM and the daily budget have no guessed defaults.
5. Migrations:
   - 0001 is a byte-identical, sha256-pinned copy of v1 schema.sql, run statement by statement.
   - 0002 applies §21 exactly as specified above.
   - schema.sql is the end state, proven equal to the migrations by T1.8.
6. Vector columns are dimensionless `vector` (the two v1 columns are altered in 0002). There
   are no vector indexes in M1.
7. The §21 interpretations above, including:
   - one Learner list of five values;
   - the hypothesis status list from §7.4 plus `rejected`;
   - the origin list from §7.2;
   - `theses.alpha/beta` dropped;
   - lessons foreign-keyed to a strategy version;
   - a 13-stage CHECK on `cases.stage` and `outcomes.stage`;
   - `cases.pattern_id` as an FK to hypotheses.
8. Queue:
   - Claim with `UPDATE ... WHERE id = (SELECT id ... ORDER BY run_after, id FOR UPDATE SKIP
     LOCKED LIMIT 1) RETURNING`.
   - Finishes are ownership-checked.
   - `heartbeat` extends the lease.
   - Capped exponential backoff.
   - Stale running jobs go back to queued, or to failed once attempts >= max_attempts.
   - Handlers must be idempotent.
   - The error text is truncated to 2,000 chars.
9. DB tests use the `db` marker, the `TEST_DATABASE_URL` variable and a fresh database per run
   (or "reuse" mode for a Neon branch). The gate deselects them.
10. SQL consistency uses a small, documented, line-based DDL parser in tests (no new
    dependency). The live `information_schema` comparison is the authoritative check.
11. Follow-ups for the orchestrator at retro (no ticket may write these):
    - CLAUDE.md "Commands" points to `scripts/tasks.py`;
    - `.gitattributes` adds `*.sql text eol=lf` explicitly.

## Questions for the founder

1. **Postgres + pgvector hosting (paid service + credentials).** Recommendation: no local
   install on Windows, because pgvector there needs a C toolchain.
   - Use Nebius Managed PostgreSQL (PG16, vector 0.8, pgcrypto) for the demo database. The
     2vcpu-8gb preset is about $0.14/h, roughly $100/month if left running. Hackathon credits
     are not documented, so ask the organisers. Promo credits need a payment method and a $25
     verification charge.
   - Use a Neon free-tier project with disposable branches as TEST_DATABASE_URL.
   - If Nebius is not wanted, Neon (choose PG16+) can serve both until M15.

   Which do you approve? Will you create the instances and put the URLs in your local `.env`?
2. **Test database privileges.** May db-test create and drop databases named `nv_test_<hex>`
   on the TEST_DATABASE_URL server? That needs a role with CREATEDB, and either CREATE EXTENSION
   vector rights or vector pre-installed in the template. If the role lacks CREATEDB, should
   db-test use "reuse" mode on a dedicated Neon branch? TEST_DATABASE_URL must never point at
   the demo database.
3. **Do you approve the §21 interpretations in Decisions 7?** In particular:
   - dropping `theses.alpha/beta`;
   - the jobs additions;
   - the stage CHECK lists;
   - lessons requiring a strategy version;
   - the open-case unique key. It allows only one open case per company and pattern, so a
     second inbound request from the same company joins the open case.
4. Do you approve dimensionless vector columns in M1, with the dimension fixed in M2?
5. Do you confirm the MIT licence currently in pyproject? The LICENSE file comes in M15.
6. DAILY_BUDGET_USD: no default, so LLM calls refuse to run until it is set (recommended)? Or
   a value you choose?
7. Do you approve removing the unused later-milestone dependencies now?

## Parked (for docs/LATER.md)

- SQLAlchemy table metadata and a repository layer.
- Versioned Pydantic payload models for the JSONB fields.
- Vector indexes (HNSW) and the EMBED_DIM ALTER (M2).
- `northvaine/jobs/nightly.py` and the time machine (the M1 task only reports "later
  milestone").
- `/health/db` endpoint and app-lifespan engine disposal.
- The Alembic connection-sharing env.py branch for async fixtures.
- mypy in the gate.
- CI (outward-facing).
- 180-day document retention job.
- README and LICENSE (M15).
- pytest-socket enforcement of no network in tests.
- Enum CHECKs for `hypotheses.kind`, `messages.channel` and `inbound_queries.channel`.
- Cross-org pooling of beliefs.
