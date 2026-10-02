# pgvector

Date checked: 2026-10-02. Researcher notes for the Northvaine factory (see `docs/FACTORY.md`).

## Summary

- Extension name is `vector` (`CREATE EXTENSION vector;`). The latest release is **0.8.7** (2026-10-01). It supports Postgres 13+.
- You can declare a column as `vector` with no dimension. **HNSW and IVFFlat indexes refuse it** with `column does not have dimensions`. To index a dimensionless column you need an expression index that casts to `vector(N)`, usually made partial with a WHERE clause. Our plan: if we know the embedding size, declare `vector(N)` up front.
- Changing `vector` to `vector(N)` later should work through `ALTER COLUMN ... TYPE vector(N)`. The extension defines an implicit `vector AS vector` cast that applies the typmod. This is **inferred from source**: no doc says it in words.
- `pgvector.sqlalchemy.VECTOR` sends vectors as text (`'[1.0,2.0]'`) and parses text results. With `postgresql+asyncpg` this works **without registering any codec**. Upstream's own test suite runs the asyncpg engine with no registration. Registering the asyncpg codec on a SQLAlchemy engine is marked `TODO` upstream, so don't do it.
- `pgcrypto` is a trusted extension, so any role with `CREATE` on the database can create it. `vector` is **not** trusted: its control file has no `trusted = true`. On vanilla Postgres it needs a superuser. On managed providers it needs the provider's admin role (`rds_superuser`, `cloudsqlsuperuser`, Azure allowlist plus admin), or you enable it through the provider's UI or SQL editor.

## Facts

| # | Fact | Source | Confidence |
|---|------|--------|------------|
| 1 | Extension name `vector`, enabled with `CREATE EXTENSION vector;` once per database | https://github.com/pgvector/pgvector#getting-started | confirmed in docs |
| 2 | Latest version 0.8.7 (2026-10-01); `default_version = '0.8.7'` | https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md, https://github.com/pgvector/pgvector/blob/master/vector.control | confirmed |
| 3 | Supports Postgres 13+ | https://github.com/pgvector/pgvector#installation | confirmed in docs |
| 4 | Minimum pgvector version for us: **0.7.0** for `halfvec`/`bit`/`sparsevec`, `<+>`, `binary_quantize`, `subvector`. 0.8.0 adds iterative index scans. Releases 0.8.2 through 0.8.7 fix buffer overflows and HNSW vacuum corruption, so **prefer >= 0.8.2, ideally the latest** | README function tables, CHANGELOG | confirmed (choosing the minimum is our call) |
| 5 | Dimensionless column allowed: "You can use `vector` as the type (instead of `vector(n)`)" | https://github.com/pgvector/pgvector#can-i-store-vectors-with-different-dimensions-in-the-same-column | confirmed in docs |
| 6 | Indexing a dimensionless column: "you can only create indexes on rows with the same number of dimensions (using expression and partial indexing)" | same FAQ | confirmed in docs |
| 7 | HNSW and IVFFlat builds raise `ERROR: column does not have dimensions` when the indexed column's typmod is < 0 | https://github.com/pgvector/pgvector/blob/master/src/hnswbuild.c (around line 705), https://github.com/pgvector/pgvector/blob/master/src/ivfbuild.c (around line 360) | confirmed in source |
| 8 | Index dimension limits: `vector` up to 2,000, `halfvec` up to 4,000, `bit` up to 64,000 (HNSW and IVFFlat). Storage limit 16,000 dims | README HNSW/IVFFlat sections, "Vector Type" | confirmed in docs |
| 9 | `CREATE CAST (vector AS vector) WITH FUNCTION vector(vector, integer, boolean) AS IMPLICIT` (the typmod coercion). A value whose length differs from the typmod fails with `expected %d dimensions, not %d` | https://github.com/pgvector/pgvector/blob/master/sql/vector.sql (lines ~202, 234), https://github.com/pgvector/pgvector/blob/master/src/vector.c (`CheckExpectedDim`) | confirmed in source |
| 10 | So `ALTER TABLE t ALTER COLUMN embedding TYPE vector(N)` works on an empty table, and on a non-empty one if every row already has N dims (otherwise it errors) | follows from #9 plus Postgres ALTER TYPE semantics | **inferred**, verify with the commands below |
| 11 | pgvector-python latest is 0.5.0, requires Python >= 3.10 | https://pypi.org/pypi/pgvector/json | confirmed |
| 12 | `pgvector.sqlalchemy.VECTOR(dim=None)`: with dim None the DDL is `VECTOR`, otherwise `VECTOR(n)`. `bind_processor` returns text through `Vector._to_db`. `result_processor` parses text, or a `Vector` object if a codec handed it one | https://github.com/pgvector/pgvector-python/blob/master/pgvector/sqlalchemy/vector.py | confirmed in source |
| 13 | Also exported: `HALFVEC`, `BIT`, `SPARSEVEC`, plus `avg` and `sum` aggregates. Comparator methods: `l2_distance`, `max_inner_product`, `cosine_distance`, `l1_distance` (`hamming_distance` and `jaccard_distance` on BIT) | pgvector-python README "SQLAlchemy" | confirmed in docs |
| 14 | README: you only need to "register the types with the underlying driver" for **ARRAY(VECTOR)** columns. It shows Psycopg 3, async Psycopg 3 and Psycopg 2 listeners, and none for asyncpg | https://github.com/pgvector/pgvector-python#sqlalchemy | confirmed in docs |
| 15 | Upstream tests: `create_async_engine('postgresql+asyncpg://...')` with **no** registration is in `async_engines` and `async_array_engines`. `asyncpg_type_engine` (with `register_vector` via `run_async`) is excluded with `# TODO support asyncpg_type_engine` | https://github.com/pgvector/pgvector-python/blob/master/tests/test_sqlalchemy.py (lines 47-61) | confirmed in source |
| 16 | Raw asyncpg (no SQLAlchemy) uses `from pgvector.asyncpg import register_vector; await register_vector(conn)`, or `init=` on the pool | pgvector-python README "asyncpg" | confirmed in docs |
| 17 | Postgres: `CREATE EXTENSION` needs a superuser unless the extension is "trusted". `pgcrypto` is in the trusted list | https://www.postgresql.org/docs/current/contrib.html | confirmed in docs |
| 18 | `vector.control` has no `trusted` line, so pgvector is not trusted on vanilla Postgres | https://github.com/pgvector/pgvector/blob/master/vector.control | confirmed in source |
| 19 | AWS RDS: on 13+ a role with CREATE can install trusted extensions (the list includes `pgcrypto` but **not** `vector`). Most other extensions need `rds_superuser`. `rds.allowed_extensions` can restrict either. RDS has pgvector 0.8.2 on PG 15.19 through 18.6 | https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.FeatureSupport.Extensions.html, https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html | confirmed in docs (RDS also has "delegated extension support", not researched) |
| 20 | Google Cloud SQL: "only users with the `cloudsqlsuperuser` role can create extensions", and the default `postgres` user has it. pgvector 0.8.5 on PG 13+. pgcrypto is supported | https://docs.cloud.google.com/sql/docs/postgres/extensions | confirmed in docs |
| 21 | Azure Flexible Server: you must add extensions to the `azure.extensions` server parameter allowlist before `CREATE EXTENSION` | https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-allow-extensions | confirmed in docs (which role can create was not confirmed on this page) |
| 22 | Neon: `CREATE EXTENSION IF NOT EXISTS vector;` on every plan. Its page names no special privilege; the default role is the project owner role | https://neon.com/docs/extensions/pgvector | confirmed in docs (whether a role we create ourselves can do it is inferred) |
| 23 | Supabase: `create extension vector with schema extensions;` (or the Dashboard > Database > Extensions page). The type is then `extensions.vector(384)` unless `extensions` is on the search_path | https://supabase.com/docs/guides/database/extensions/pgvector | confirmed in docs |

## Examples (copied from docs)

```sql
-- pgvector README
CREATE EXTENSION vector;
CREATE TABLE items (id bigserial PRIMARY KEY, embedding vector(3));
CREATE INDEX ON items USING hnsw (embedding vector_l2_ops);

-- dimensionless column + expression/partial index (README FAQ)
CREATE TABLE embeddings (model_id bigint, item_id bigint, embedding vector, PRIMARY KEY (model_id, item_id));
CREATE INDEX ON embeddings USING hnsw ((embedding::vector(3)) vector_l2_ops) WHERE (model_id = 123);
SELECT * FROM embeddings WHERE model_id = 123 ORDER BY embedding::vector(3) <-> '[3,1,2]' LIMIT 5;
```

```python
# pgvector-python README, SQLAlchemy
from pgvector.sqlalchemy import VECTOR

class Item(Base):
    embedding: Mapped[list[float]] = mapped_column(VECTOR(3))

index = Index(
    'my_index',
    Item.embedding,
    postgresql_using='hnsw',
    postgresql_with={'m': 16, 'ef_construction': 64},
    postgresql_ops={'embedding': 'vector_l2_ops'}
)

session.scalars(select(Item).order_by(Item.embedding.l2_distance([3, 1, 2])).limit(5))
```

```python
# upstream tests/test_sqlalchemy.py: asyncpg engine used with no codec registration
asyncpg_engine = create_async_engine('postgresql+asyncpg://localhost/pgvector_python_test')
```

```python
# pgvector-python README, raw asyncpg only (not via SQLAlchemy)
from pgvector.asyncpg import register_vector

async def init(conn):
    await register_vector(conn)

pool = await asyncpg.create_pool(..., init=init)
```

## Limits

- Indexable dims: `vector` 2,000; `halfvec` 4,000; `bit` 64,000. Storage max 16,000 dims for `vector`/`halfvec`.
- Storage: `vector` is `4 * dims + 8` bytes; `halfvec` is `2 * dims + 8` bytes.
- Elements must be finite (no NaN/Infinity).
- Approximate indexes apply filtering after the scan, so filtered queries can return fewer rows. Iterative scans (0.8.0+) help.
- HNSW can be built on an empty table. IVFFlat needs data to train its lists, so build it after loading.

## Open questions

1. **ALTER `vector` to `vector(N)`.** Inferred, not documented. Verify:
   ```sh
   docker run --rm -d --name pgv -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg18-trixie
   docker exec -i pgv psql -U postgres -c "CREATE EXTENSION vector; CREATE TABLE t (e vector); ALTER TABLE t ALTER COLUMN e TYPE vector(3); \d t"
   docker exec -i pgv psql -U postgres -c "CREATE TABLE u (e vector); INSERT INTO u VALUES ('[1,2]'); ALTER TABLE u ALTER COLUMN e TYPE vector(3);"  # expect: expected 3 dimensions, not 2
   ```
2. **Provider pgvector versions lag.** RDS has 0.8.2 and Cloud SQL 0.8.5, versus 0.8.7 upstream. Don't depend on features newer than 0.8.0. Once deployed, check with `SELECT extversion FROM pg_extension WHERE extname = 'vector';`.
3. **Non-superuser app role.** The safest pattern: the migration or admin role (provider admin) runs `CREATE EXTENSION IF NOT EXISTS vector` (and `pgcrypto`) once per database, and the app role only owns tables. On a new provider, confirm with `SELECT rolname, rolsuper FROM pg_roles WHERE rolname = current_user;` followed by `CREATE EXTENSION IF NOT EXISTS vector;`.
4. **Azure role and Neon non-owner roles.** Which roles may create extensions there was not confirmed. Check the Azure "extensions overview" page and Neon's "manage roles" page before relying on either.
5. **pgcrypto may be unneeded.** On PG 13+, `gen_random_uuid()` is built into core Postgres. Only add pgcrypto if we need its other functions. (Recalled from general knowledge, not re-checked today: see https://www.postgresql.org/docs/current/functions-uuid.html.)
6. **ARRAY(VECTOR) with asyncpg.** The tests include the unregistered asyncpg engine in the array-engine list, but the README only documents psycopg registration for arrays. Avoid array-of-vector columns unless we need them.
