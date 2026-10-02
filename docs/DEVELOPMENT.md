# Development

Every command runs on Windows without `make`, `psql` or a POSIX shell. It behaves the same in
PowerShell and Git Bash. The runner is `scripts/tasks.py` (stdlib only). The `Makefile` only
delegates to it, for machines that have `make`.

## Windows setup

1. Install uv (https://docs.astral.sh/uv/). Check with `uv --version`.
2. Install Python 3.12. The repo pins it in `.python-version`:
   ```
   uv python install 3.12
   ```
3. Create the environment (project plus the `dev` dependency group):
   ```
   uv sync
   ```
4. Copy `.env.example` to `.env` and fill in the values you need. `.env` is never committed.
5. Run tasks:
   ```
   uv run python scripts/tasks.py --help          # list tasks
   uv run python scripts/tasks.py test            # unit tests
   uv run python scripts/tasks.py --print lint    # show the commands, run nothing
   ```

## Tasks

| Task | Runs |
|---|---|
| `setup` | `uv sync` |
| `dev` | `uvicorn northvaine.api.main:app --reload --port 8000`, plus `npm --prefix frontend run dev` (`npm.cmd` on Windows) when `frontend/package.json` exists |
| `test` | `pytest -q -m "not live and not db" --ignore=tests/golden` |
| `golden` | `pytest tests/golden -v --tb=short`. It prints "no golden tests yet" and exits 0 when there are none |
| `lint` | `ruff check` and `ruff format --check` on `northvaine tests scripts migrations` |
| `migrate` | `alembic upgrade head` |
| `db-check` | `python -m northvaine.core.db` (connects with `DATABASE_URL` and prints the status) |
| `db-test` | `pytest -q -m db`. It stops first with a message if `TEST_DATABASE_URL` is not set |
| `gate` | `scripts/gate.py`, the gate every ticket and merge must pass |
| `nightly` | `python -m northvaine.jobs.nightly`. It exits 2 until a later milestone adds it |

Python tools run through the same interpreter as the runner (`python -m ...`). Nothing runs
through a shell.

## Database URLs

Both URLs use the asyncpg driver form:

```
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>?ssl=require
TEST_DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<test_db>?ssl=require
```

- `DATABASE_URL` is the app and demo database. `migrate` and `db-check` use it.
- `TEST_DATABASE_URL` is only for db tests. Never point it at the demo database. With
  `TEST_DB_ISOLATION=database` (the default) the db tests create and drop a throwaway
  `nv_test_<hex>` database. With `reuse` they migrate `TEST_DATABASE_URL` itself.
- `ssl=require` encrypts the connection but does not verify the server certificate. Hosted
  URLs copied from a provider often say `sslmode=require` instead. The app rewrites `sslmode`
  for asyncpg (see `docs/integrations/sqlalchemy-asyncpg.md`).
- To verify the server (verify-full), give the CA file explicitly. The libpq default
  `root.crt` path is not used:
  ```
  DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>?sslmode=verify-full&sslrootcert=C:/certs/root.crt
  ```
  `verify-full` without `sslrootcert` is a configuration error. Nebius Managed PostgreSQL
  documents `sslmode=verify-full` with its CA certificate (see
  `docs/integrations/postgres-hosting.md`).

## Pooled endpoints: DB_POOL_MODE

- `DB_POOL_MODE=session` (the default) is for a direct connection.
- `DB_POOL_MODE=transaction` is for a transaction pooler (PgBouncer `pool_mode=transaction`,
  such as a Neon `-pooler` host or the Nebius pooler in Transaction mode). The engine then
  uses no client-side pool and turns off prepared statement caches. A Neon `-pooler` host is
  treated as transaction mode even if the setting says session. For the Nebius pooler, set
  it explicitly.
- Run migrations over a direct (non-pooled) connection.

## Tests and the database

- Unit tests (`tasks.py test`, and the gate) need **no database and no network**. Tests marked
  `db` or `live` are excluded.
- `tasks.py db-test` runs the `db` tests against `TEST_DATABASE_URL`. It reads the variable
  from the environment or from `.env`, and fails with a readable message before pytest starts
  if neither sets it.
- **db-test must pass before milestone sign-off.** The gate does not run it, so run it by hand
  against a real Postgres 16+ with pgvector (for example a Neon branch or Docker
  `pgvector/pgvector`).
