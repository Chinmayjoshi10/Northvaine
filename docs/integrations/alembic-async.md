# Alembic with async SQLAlchemy 2 + asyncpg

Date checked: 2026-10-02. Researcher notes only; no application code is prescribed here.
Snippets below are copied from official docs/source or are clearly marked as sketches.

## Summary

- Latest Alembic release is **1.20.0** (2026-09-11), requiring Python >= 3.10. 1.20.0 dropped
  SQLAlchemy 1.4, so SQLAlchemy >= 2.0 is required. `1.20.1` is listed in the changelog as
  unreleased.
- `alembic init -t async <dir>` exists (also `-t pyproject_async` since 1.16.3). Its `env.py`
  runs online migrations with `async_engine_from_config(...)` + `connection.run_sync(...)`
  inside `asyncio.run(...)`. Offline mode is plain sync code with no engine.
- Offline mode (`--sql`) needs **no reachable DB**. Only a URL is used, to choose the dialect.
  From the source, building the dialect does not import the DBAPI, so a dummy URL like
  `postgresql+asyncpg://x/x` (or plain `postgresql://`) should work (inferred; command below
  confirms it).
- **Multiple statements in one string will not work online with asyncpg.** SQLAlchemy's
  asyncpg adapter always prepares the statement, and PostgreSQL won't allow more than one
  command in a prepared statement. Offline, the string is just written to the output, so it
  works there. Either split the statements, or (online only) call asyncpg's own
  `Connection.execute`, which accepts several commands when no arguments are given.
- Programmatic upgrades: `alembic.command.upgrade(Config(...), "head")`. The async `env.py`
  calls `asyncio.run()`, so call it from a **sync** pytest fixture, or use the documented
  connection-sharing pattern through `config.attributes`.
- Windows: Alembic reads `alembic.ini` with `encoding="locale"`, which is cp1252 on most
  Windows machines. Keep the ini ASCII. Always read `.sql` files with an explicit
  `encoding="utf-8"` (or `"utf-8-sig"`). Use forward slashes and `%(here)s` in
  `script_location`, and double any `%` in URLs.

## Facts table

| # | Fact | Source | Confidence |
|---|---|---|---|
| 1 | Latest release is 1.20.0, released 2026-09-11, Python >= 3.10 | https://pypi.org/project/alembic/ | confirmed |
| 2 | Changelog lists 1.20.1 (no date, unreleased), 1.20.0 (2026-09-11), 1.19.2 (2026-09-04), 1.19.1 (2026-08-08), 1.19.0 (2026-08-04) | https://alembic.sqlalchemy.org/en/latest/changelog.html | confirmed |
| 3 | 1.20.0 dropped SQLAlchemy 1.4 support; SQLAlchemy 2.0.0 is the minimum | changelog (as above) | confirmed |
| 4 | Templates in 1.20.0 are `async`, `generic`, `multidb`, `pyproject`, `pyproject_async` | https://github.com/sqlalchemy/alembic/tree/rel_1_20_0/alembic/templates | confirmed |
| 5 | `pyproject_async` added in 1.16.3; PEP 621 / pyproject.toml config added in 1.16.0 | changelog | confirmed |
| 6 | The async `env.py` at tag `rel_1_20_0` matches the code quoted below | https://raw.githubusercontent.com/sqlalchemy/alembic/rel_1_20_0/alembic/templates/async/env.py | confirmed |
| 7 | Offline mode: "no database connection is present"; `--sql` writes to stdout; `start:end` ranges only offline; `output_buffer` sends output to a file | https://alembic.sqlalchemy.org/en/latest/offline.html | confirmed |
| 8 | With `url=` and no connection, `MigrationContext.configure` runs `make_url(url).get_dialect()(**dialect_opts)`. It creates no engine and makes no connection | https://raw.githubusercontent.com/sqlalchemy/alembic/main/alembic/runtime/migration.py | confirmed (source) |
| 9 | Because of #8, offline mode needs no reachable DB and probably no asyncpg install either. The asyncpg import happens in `import_dbapi()` at `create_engine` time, not when the dialect class is created | migration.py + SQLAlchemy dialect design | inferred; run check A |
| 10 | `dialect_name="postgresql"` can replace `url` in offline `context.configure` | https://alembic.sqlalchemy.org/en/latest/api/runtime.html | confirmed |
| 11 | `op.execute` accepts a str (turned into `text()`) or an Executable. Offline it "emits directly to the output stream". Bound parameters don't work offline. Literal colons must be backslash-escaped | https://alembic.sqlalchemy.org/en/latest/ops.html | confirmed |
| 12 | SQLAlchemy's asyncpg cursor `execute()` always goes through `_prepare_and_execute()`, which calls `adapt_connection._prepare(...)` with or without parameters. No code path uses the simple query protocol | https://raw.githubusercontent.com/sqlalchemy/sqlalchemy/main/lib/sqlalchemy/dialects/postgresql/asyncpg.py | confirmed (source) |
| 13 | PostgreSQL rejects several commands in one prepared statement ("cannot insert multiple commands into a prepared statement") | https://github.com/MagicStack/asyncpg/issues/30 (issue tracker, not docs) | confirmed (issue tracker) |
| 14 | asyncpg `Connection.execute(query, *args)` "can execute many SQL commands at once, when no arguments are provided" | https://magicstack.github.io/asyncpg/current/api/index.html | confirmed |
| 15 | `AdaptedConnection.run_async(fn)` runs an awaitable-only driver method from sync (greenlet) context (added in SQLAlchemy 1.4.30) | https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html | confirmed |
| 16 | `Config(file_=None, toml_file=None, ini_section="alembic", output_buffer=None, stdout=sys.stdout, cmd_opts=None, config_args=..., attributes=None)` | https://raw.githubusercontent.com/sqlalchemy/alembic/main/alembic/config.py ; https://alembic.sqlalchemy.org/en/latest/api/config.html | confirmed |
| 17 | `set_main_option` values are interpolated, so a literal `%` must be written as `%%` | api/config.html ; tutorial.html | confirmed |
| 18 | Cookbook: share a connection through `cfg.attributes["connection"]`. `env.py` checks it and calls `do_run_migrations(connection)` directly instead of `asyncio.run(...)` | https://alembic.sqlalchemy.org/en/latest/cookbook.html | confirmed |
| 19 | `asyncio.run()` raises RuntimeError if an event loop is already running. Calling `command.upgrade` with the stock async env.py inside an async (pytest-asyncio) test therefore fails | Python asyncio docs, https://docs.python.org/3/library/asyncio-runner.html | confirmed (Python docs); applied to Alembic by inference |
| 20 | `alembic.ini` is read with `ConfigParser.read(..., encoding="locale")` (since 1.11.3); pyproject.toml is read in binary mode with `tomllib` | https://raw.githubusercontent.com/sqlalchemy/alembic/main/alembic/util/compat.py ; config.py | confirmed (source) |
| 21 | `%(here)s` is set from `Path(...).absolute().parent.as_posix()`, so it uses forward slashes on Windows too | config.py (as above) | confirmed (source) |
| 22 | The template says `script_location` is "typically a path given in POSIX (e.g. forward slashes) format, relative to the token %(here)s"; `path_separator = os` is the new-project default (1.16.0+) | https://raw.githubusercontent.com/sqlalchemy/alembic/rel_1_20_0/alembic/templates/async/alembic.ini.mako ; https://alembic.sqlalchemy.org/en/latest/tutorial.html | confirmed |
| 23 | `output_encoding` (ini) sets the encoding for new revision files (default utf-8). `output_encoding` in `context.configure` sets the encoding of `--sql` output | tutorial.html ; api/runtime.html | confirmed |
| 24 | Python `open()` without `encoding=` uses the locale encoding (cp1252 on most Windows setups) unless UTF-8 mode is on | https://docs.python.org/3/library/functions.html#open | confirmed |
| 25 | Windows PowerShell 5.1 `>` redirection may write UTF-16LE, so `alembic upgrade head --sql > out.sql` can give a non-UTF-8 file. Prefer `Config(output_buffer=open(..., "w", encoding="utf-8"))` or `-x`-driven output in env.py | general PowerShell behaviour, not Alembic docs | inferred |

## Examples (copied from docs / source)

### `env.py` from `alembic init -t async` (Alembic 1.20.0)

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```
(Comments trimmed; code unchanged.)

The template ini has `sqlalchemy.url = driver://user:pass@localhost/dbname` with the comment
"This is consumed by the user-maintained env.py script only". So env.py is free to take the URL
from somewhere else.

### Setting the URL from application settings (sketch, not from docs)

Option 1: overwrite the option at the top of env.py, so both offline and online paths pick it
up unchanged:

```python
# env.py, after `config = context.config`
# from northvaine.<settings module> import settings   # whatever the contracts ticket defines
if not config.get_main_option("sqlalchemy.url") or config.get_main_option("sqlalchemy.url").startswith("driver://"):
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
```
`replace("%", "%%")` is needed because `set_main_option` interpolates (fact 17). A
URL-encoded password like `P%40ss` would otherwise break.

Option 2: skip the ini for the URL. Pass `url=` to `context.configure` offline and use
`create_async_engine(settings.database_url, poolclass=pool.NullPool)` online. This avoids
interpolation entirely.

### Programmatic upgrade (cookbook, verbatim)

```python
def run_migrations_online():
    connectable = config.attributes.get("connection", None)
    if connectable is None:
        asyncio.run(run_async_migrations())
    else:
        do_run_migrations(connectable)
```

```python
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import command, config

def run_upgrade(connection, cfg):
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")

async def run_async_upgrade():
    async_engine = create_async_engine("sqlite+aiosqlite://", echo=True)
    async with async_engine.begin() as conn:
        await conn.run_sync(run_upgrade, config.Config("alembic.ini"))

asyncio.run(run_async_upgrade())
```

Config API example (docs, verbatim):

```python
from alembic.config import Config
from alembic import command

alembic_cfg = Config()
alembic_cfg.set_main_option("script_location", "myapp:migrations")
alembic_cfg.set_main_option("sqlalchemy.url", "postgresql://foo/bar")
```

### pytest fixture shapes (sketch, not from docs)

- **Sync fixture (simplest):**
  `cfg = Config(str(repo_root / "alembic.ini")); cfg.set_main_option("sqlalchemy.url", test_url.replace("%", "%%")); command.upgrade(cfg, "head")`.
  This is safe because no event loop is running in a plain sync fixture.
- **Async fixture (pytest-asyncio):** don't call `command.upgrade` directly, because the stock
  env.py would call `asyncio.run` inside the running loop (fact 19). Use the cookbook pattern:
  `async with engine.begin() as conn: await conn.run_sync(run_upgrade, cfg)`, with the
  `config.attributes` branch added to env.py.
- Build `Config` with an absolute path. `%(here)s` comes from the ini file's location, not
  the CWD (fact 21), so tests can run from any directory.

### Multi-statement SQL (sketch, not from docs)

Online with asyncpg, `op.execute(big_sql)` with several `;`-separated commands fails (facts
12, 13). Options:

1. **Split** into one `op.execute` per statement. This works online and offline, and offline
   output gets one statement per line, each ending in `;`. A naive `split(";")` breaks on
   semicolons inside `$$ ... $$` function bodies, string literals or comments. Use a real
   splitter, or keep each statement in its own file or constant.
2. **Online only:** pass the whole script to the driver's simple query protocol:
   ```python
   if context.is_offline_mode():
       op.execute(big_sql)                       # just written to the --sql output
   else:
       op.get_bind().connection.dbapi_connection.run_async(
           lambda c: c.execute(big_sql)           # asyncpg Connection.execute, no args
       )
   ```
   Path from facts 14 and 15. The exact attribute chain (`Connection.connection` → pool proxy
   → `.dbapi_connection` → `AdaptedConnection`) is inferred; run check B. Note that the adapter
   opens a transaction lazily on the first prepared statement. Raw `c.execute` bypasses that,
   so the effect on Alembic's transaction wrapping should be confirmed (check B).
3. Whatever `text()` does still applies on the `op.execute` path: `:word` is treated as a bind
   parameter (escape as `\:`), but `::type` casts are fine.

## Limits and pitfalls

- Offline mode can't run migrations that read data (for example `SELECT` and branch on
  rows). `op.get_bind()` results don't exist there.
- Offline output applies `literal_binds=True`. Complex literal types (dates and so on) may
  need manual formatting (runtime docs).
- `alembic.ini` is read with the locale encoding (cp1252 on Windows), so non-ASCII text, even
  in comments, can be misread. Keep it ASCII, or use `pyproject.toml` config (read as bytes
  with tomllib).
- `.sql` files loaded by migrations: always `Path(p).read_text(encoding="utf-8")`. Use
  `"utf-8-sig"` if editors on Windows may add a BOM, because a BOM at the start of the SQL
  produces a syntax error in PostgreSQL. Resolve them relative to `__file__`, not the CWD.
- `script_location`: use forward slashes and `%(here)s/...` (or a package path like
  `pkg:migrations`). `%(here)s` is already POSIX-style. With `path_separator = os`, Windows
  splits `prepend_sys_path` and `version_locations` on `;`.
- `%` in URLs must be doubled whenever the URL goes through the ini or `set_main_option`.
- `--sql` output on Windows: prefer an explicit UTF-8 `output_buffer` /
  `output_encoding="utf-8"` over shell redirection (fact 25).
- `NullPool` in the template means each `alembic` run opens and closes its own connection.
  That's expected.

## Open questions / commands for the founder to confirm

A. **Offline mode without a DB, and without asyncpg** (confirms facts 8 and 9). Run with no
   Postgres running:
   ```
   uv run alembic -c alembic.ini -x dummy=1 upgrade head --sql
   ```
   with `sqlalchemy.url = postgresql+asyncpg://u:p@127.0.0.1:1/none` (port 1, unreachable).
   Expected: the SQL is printed and there is no connection error. To also test without
   asyncpg, repeat in a venv where asyncpg is not installed.

B. **Raw asyncpg multi-statement path and transactions** (option 2 above). Against a
   disposable test DB, run a migration that executes `CREATE TABLE t1(a int); CREATE TABLE t2(a int);`
   through `dbapi_connection.run_async(lambda c: c.execute(sql))`, then raise an exception in
   the same migration. Check whether t1/t2 roll back:
   ```
   uv run alembic upgrade head ; psql "$TEST_DATABASE_URL" -c "\dt"
   ```
   If they don't roll back, use option 1 (split) only.

C. **Confirm the installed version** once added to the project:
   `uv run python -c "import alembic, sqlalchemy; print(alembic.__version__, sqlalchemy.__version__)"`.

D. Not checked: the latest asyncpg version and its Python 3.13/3.14 Windows wheels. Run
   `uv pip index versions asyncpg` or see https://pypi.org/project/asyncpg/.
