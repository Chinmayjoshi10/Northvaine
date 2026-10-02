# SQLAlchemy (asyncio) + asyncpg

Date checked: 2026-10-02. Researcher notes. Every fact has a source URL. Where something was
checked by running the libraries locally, that is marked "local check" (Windows 11, no database
server; see "How the local checks were run" at the end).

## Summary

- Current versions: **SQLAlchemy 2.1.2** (released 2026-10-02, needs Python >= 3.11) and
  **asyncpg 0.31.0** (released 2025-11-24, needs Python >= 3.9). The latest 2.0.x is 2.0.54
  (2026-09-15).
- URL: always write `postgresql+asyncpg://user:pass@host:port/dbname`. `postgres://` is rejected
  (it was removed in 1.4). Bare `postgresql://` picks the default sync driver, which is
  **psycopg (v3) in 2.1** (in 2.0 it was psycopg2), not asyncpg. So app code must rewrite the
  provider's URL scheme to `postgresql+asyncpg://`.
- `?sslmode=require` does **not** work through SQLAlchemy+asyncpg. SQLAlchemy passes every URL
  query key straight to `asyncpg.connect()` as a keyword argument, and `asyncpg.connect()` has no
  `sslmode` keyword. The result is `TypeError: connect() got an unexpected keyword argument
  'sslmode'`. Change it to `?ssl=require` in the URL, or remove it and pass
  `connect_args={"ssl": "require"}` (or an `ssl.SSLContext`).
- Transaction poolers (PgBouncer `pool_mode=transaction`, Neon pooled endpoint): the safe setup
  is `poolclass=NullPool`, asyncpg `statement_cache_size=0` (through `connect_args`), SQLAlchemy
  `prepared_statement_cache_size=0` (in the URL query or `connect_args`), plus unique prepared
  statement names through `prepared_statement_name_func`. Neon's PgBouncer (1.22+,
  `max_prepared_statements=1000`) supports protocol-level prepared statements, so the cache-off
  settings may not be strictly needed on Neon. They are still the documented safe default
  (see open questions).
- Windows: asyncpg 0.31.0 ships `cp312-win_amd64` wheels. asyncpg's own CI runs on
  `windows-2025` with Python 3.12 and the default asyncio loop, which is `ProactorEventLoop`.
  Local check: on Python 3.12.13 the import and engine code run under `ProactorEventLoop`. A full
  query against a real server was **not** run.

## Facts

| # | Fact | Source | Confidence |
|---|---|---|---|
| 1 | SQLAlchemy latest is 2.1.2, `requires_python >=3.11`, files uploaded 2026-10-02. Has `cp312-cp312-win_amd64` wheel. | https://pypi.org/pypi/SQLAlchemy/json | confirmed |
| 2 | Latest SQLAlchemy 2.0.x is 2.0.54 (2026-09-15). The 2.0 docs call it the "legacy version". | https://pypi.org/pypi/SQLAlchemy/json, https://docs.sqlalchemy.org/en/20/dialects/postgresql.html | confirmed |
| 3 | asyncpg latest is 0.31.0, `requires_python >=3.9.0`, uploaded 2025-11-24. Wheels include `asyncpg-0.31.0-cp312-cp312-win_amd64.whl` and `-win32.whl` (also cp313). | https://pypi.org/pypi/asyncpg/json | confirmed |
| 4 | asyncpg connect string: `postgresql+asyncpg://user:password@host:port/dbname[?key=value&key=value...]`. Use it with `create_async_engine()`. | https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.asyncpg | confirmed |
| 5 | `postgres://` URLs were removed in SQLAlchemy 1.4 ("Remove support for deprecated engine URLs of the form `postgres://`"). Local check, 2.1.2: `create_async_engine("postgres://...")` raises `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres`. | https://github.com/sqlalchemy/sqlalchemy/blob/main/doc/build/changelog/changelog_14.rst (ticket 4643) | confirmed + local check |
| 6 | Bare `postgresql://` picks the default PostgreSQL DBAPI. On `main`/2.1 that is `psycopg` (`base.dialect = dialect = psycopg.dialect`). Local check, 2.1.2: `create_async_engine("postgresql://...")` fails with `ModuleNotFoundError: No module named 'psycopg'` when only asyncpg is installed. | https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/postgresql/__init__.py (line 99) | confirmed + local check |
| 7 | The asyncpg dialect's `create_connect_args` does `opts.update(url.query)`. Every query-string key becomes an `asyncpg.connect()` kwarg. Only `port` and `prepared_statement_cache_size` are converted to int. `sslmode` is not translated. | https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/postgresql/asyncpg.py (`create_connect_args`; same in `rel_2_0`) | confirmed (source) |
| 8 | `asyncpg.connect()` has an `ssl=` keyword and no `sslmode=` keyword. `sslmode` is only understood inside a DSN string, and SQLAlchemy does not pass a DSN. Local check: `asyncpg.connect(..., sslmode='require')` raises `TypeError: connect() got an unexpected keyword argument 'sslmode'`. | https://github.com/MagicStack/asyncpg/blob/master/asyncpg/connection.py (`connect` signature/docstring) | confirmed + local check |
| 9 | asyncpg `ssl` accepts `True`, an `ssl.SSLContext`, or a mode string: `'disable'`, `'allow'`, `'prefer'` (default), `'require'` (encrypt, no cert verification), `'verify-ca'`, `'verify-full'`. | https://magicstack.github.io/asyncpg/current/api/index.html#asyncpg.connection.connect (docstring in connection.py) | confirmed |
| 10 | `?ssl=require` in the SQLAlchemy URL arrives as `ssl='require'` (local check of `dialect.create_connect_args`). | local check | confirmed (local) |
| 11 | SQLAlchemy keeps its own prepared statement cache, 100 per DBAPI connection by default. It is set with the `prepared_statement_cache_size` DBAPI argument (URL query or connect_args). `0` turns it off. | https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#prepared-statement-cache | confirmed |
| 12 | For PgBouncer, SQLAlchemy docs show `poolclass=NullPool` + `connect_args={"prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__"}`. They warn to use `NullPool` and set PgBouncer to run `DISCARD` when connections are returned. | https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#prepared-statement-name-with-pgbouncer | confirmed |
| 13 | asyncpg FAQ: PgBouncer in `transaction`/`statement` mode does not support prepared statements. Options: use asyncpg's pool, pass `statement_cache_size=0`, or use `pool_mode=session`. | https://github.com/MagicStack/asyncpg/blob/master/docs/faq.rst | confirmed |
| 14 | asyncpg source: when `statement_cache_size` is 0, statements are marked unprepared after use "assuming people are running PgBouncer". | https://github.com/MagicStack/asyncpg/blob/master/asyncpg/connection.py (~line 511) | confirmed (source, master) |
| 15 | Neon pooled connections use PgBouncer with `pool_mode=transaction` and `max_prepared_statements=1000`. Protocol-level prepared statements work (PgBouncer >= 1.22.0); SQL-level `PREPARE`/`EXECUTE` does not. Neon's example connection strings include `?sslmode=require`. | https://neon.com/docs/connect/connection-pooling | confirmed |
| 16 | asyncpg CI tests Python 3.9–3.15 on `windows-2025` with the plain `asyncio` loop (uvloop excluded on Windows). The test base calls `asyncio.new_event_loop()` with no policy override, so it uses `ProactorEventLoop`, the Windows default. | https://github.com/MagicStack/asyncpg/blob/master/.github/workflows/tests.yml, https://github.com/MagicStack/asyncpg/blob/master/asyncpg/_testbase/__init__.py | inferred (CI config on master, not a release statement) |
| 17 | Local check: on Python 3.12.13 (uv) with SQLAlchemy 2.1.2 + asyncpg 0.31.0, wheels installed with no compiler, the running loop is `ProactorEventLoop`, and `create_async_engine(...).connect()` gets as far as the network (fails with TimeoutError against a closed port, as expected). No real server round-trip was run. | local check | inferred |
| 18 | SQLAlchemy docs: asyncpg returns json/jsonb as strings by default. SQLAlchemy registers `json.loads` as the decoder (`json_deserializer` overrides it). | https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.asyncpg | confirmed |

## Examples (copied from docs)

Basic (SQLAlchemy docs):

```python
from sqlalchemy.ext.asyncio import create_async_engine
engine = create_async_engine(
    "postgresql+asyncpg://user:pass@hostname/dbname"
)
```

Turning off SQLAlchemy's prepared statement cache (SQLAlchemy docs):

```python
engine = create_async_engine(
    "postgresql+asyncpg://user:pass@hostname/dbname?prepared_statement_cache_size=0"
)
```

PgBouncer (SQLAlchemy docs):

```python
from uuid import uuid4
engine = create_async_engine(
    "postgresql+asyncpg://user:pass@somepgbouncer/dbname",
    poolclass=NullPool,
    connect_args={
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    },
)
```

asyncpg SSL context equivalent to `sslmode=require` (asyncpg docstring):

```python
sslctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
sslctx.check_hostname = False
sslctx.verify_mode = ssl.CERT_NONE
con = await asyncpg.connect(user='postgres', ssl=sslctx)
```

Combined setup for a hosted transaction pooler. This is put together from facts 7–15 above and
was not copied from one doc page. It is a config shape, not application code:

```python
create_async_engine(
    "postgresql+asyncpg://USER:PASS@HOST/DB",   # scheme rewritten, sslmode removed
    poolclass=NullPool,
    connect_args={
        "ssl": "require",                      # or "verify-full" / an SSLContext
        "statement_cache_size": 0,             # asyncpg
        "prepared_statement_cache_size": 0,    # SQLAlchemy dialect
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    },
)
```

URL handling the app has to do, as rules:
`postgres://` or `postgresql://` → `postgresql+asyncpg://`. `sslmode=X` → `ssl=X` (asyncpg
accepts the same mode names). Drop libpq-only keys that asyncpg's `connect()` does not take as
kwargs, such as `channel_binding`, or they will also raise TypeError. That last point is inferred
from fact 7 and was not tested for each key.

## Limits and gotchas

- Any unknown query key in the URL becomes a `TypeError` at connect time, not at engine creation
  (fact 7). Engine creation succeeds, and the first connection fails.
- `ssl='require'` encrypts but does **not** verify the server certificate. Use `verify-full` for
  real verification (fact 9).
- After DDL from another process, cached prepared statements and type OIDs can go stale
  (`InvalidCachedStatementError`, `cache lookup failed for type`). SQLAlchemy clears its caches
  when this happens, but it cannot retry the failed statement (SQLAlchemy docs, Prepared Statement Cache
  warning).
- `NullPool` means a new TCP+TLS connection for every checkout. The external pooler does the pooling.
- SQLAlchemy 2.1 needs Python >= 3.11 (fact 1).

## Open questions

1. **Is `statement_cache_size=0` actually required on Neon's pooled endpoint now that it
   supports protocol-level prepared statements (fact 15)?** Not confirmed for asyncpg. To
   check, against a Neon `-pooler` host run the combined config with and without the two cache
   settings, under concurrency (e.g. 20 parallel `select $1::int`). Watch for
   `prepared statement "__asyncpg_stmt_..." already exists`.
2. **A real query on Windows + Proactor + TLS** was not run (no server here). To confirm:
   Save this as `check.py`, with the DB URL in the `DATABASE_URL` env var (already rewritten to
   `postgresql+asyncpg://`, without `sslmode`):
   ```python
   import asyncio, os
   from sqlalchemy import text
   from sqlalchemy.ext.asyncio import create_async_engine
   async def main():
       e = create_async_engine(os.environ["DATABASE_URL"], connect_args={"ssl": "require"})
       async with e.connect() as c:
           print(type(asyncio.get_running_loop()).__name__, (await c.execute(text("select 1"))).scalar())
       await e.dispose()
   asyncio.run(main())
   ```
   Then run `uv run --python 3.12 --with "sqlalchemy[asyncio]==2.1.2" --with asyncpg==0.31.0 python check.py`.
   The expected output is `ProactorEventLoop 1`.
3. Whether other hosted poolers (Supabase Supavisor, etc.) behave like Neon: not researched. See
   `docs/integrations/postgres-hosting.md`.
4. The CI evidence for Windows (fact 16) comes from asyncpg `master`. There is no release note that
   says "Proactor supported" in so many words.

## How the local checks were run

A scratch venv (Python 3.11.4, SQLAlchemy 2.1.2, asyncpg 0.31.0), plus
`uv run --python 3.12` (3.12.13) with the same pins. Checks: `create_async_engine` on each URL
form, `dialect.create_connect_args(make_url(url))`, `inspect.signature(asyncpg.connect)`,
`asyncpg.connect(sslmode=...)`, and the running loop type. No database server was used.
