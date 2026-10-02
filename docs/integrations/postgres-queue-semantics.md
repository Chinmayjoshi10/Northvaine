# Postgres queue semantics (PG16 target)

Date checked: 2026-10-02. Researcher notes for the Northvaine factory (see `docs/FACTORY.md`, rule 7).
All sources are the official PostgreSQL documentation (postgresql.org/docs), except where a fact is marked otherwise.

## Summary

- **Claiming a job with `FOR UPDATE SKIP LOCKED LIMIT 1` inside `UPDATE ... WHERE id = (subquery) RETURNING`
  works as a queue pattern on PG16.** The docs describe `SKIP LOCKED` as meant for "multiple consumers
  accessing a queue-like table". Under READ COMMITTED, a row that a concurrent worker changed and committed is
  checked again against the `WHERE` clause using its latest version. So a row that is no longer `queued` is not
  claimed twice. That this holds for the full composed statement is inferred from the documented rules, not
  stated in one place in the docs (see Facts F1 to F6).
- **`UNIQUE NULLS NOT DISTINCT` exists from PG15** on both constraints and indexes. **Partial unique indexes**
  (`CREATE UNIQUE INDEX ... WHERE predicate`) enforce uniqueness only among rows that match the predicate.
  `WHERE stage NOT IN ('done','failed')` is a valid predicate: constants with an immutable operator, no subquery.
  The two options can be combined in one `CREATE UNIQUE INDEX`.
- **`gen_random_uuid()` is built into PostgreSQL from PG13** (it returns a v4 UUID). You do not need pgcrypto
  or uuid-ossp to generate a v4 UUID. Install them only for their other functions.

## Facts

| # | Fact | Source | Confidence |
|---|---|---|---|
| F1 | "With `SKIP LOCKED`, any selected rows that cannot be immediately locked are skipped. Skipping locked rows provides an inconsistent view of the data, so this is not suitable for general purpose work, but can be used to avoid lock contention with multiple consumers accessing a queue-like table." | https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE | confirmed in docs |
| F2 | `NOWAIT`/`SKIP LOCKED` apply only to the row-level lock. The `ROW SHARE` table-level lock is still taken in the ordinary way. | same | confirmed in docs |
| F3 | "If a `LIMIT` is used, locking stops once enough rows have been returned to satisfy the limit (but note that rows skipped over by `OFFSET` will get locked)." | same | confirmed in docs |
| F4 | "When a locking clause appears in a sub-`SELECT`, the rows locked are those returned to the outer query by the sub-query." | same | confirmed in docs |
| F5 | READ COMMITTED: `UPDATE` and `SELECT FOR UPDATE` find only rows committed as of the command's start. If a target row was updated by a concurrent transaction, the command waits for that transaction to finish. After a commit, "the `WHERE` clause is re-evaluated to see if the updated version of the row still matches", and a deleted row is ignored. | https://www.postgresql.org/docs/16/transaction-iso.html#XACT-READ-COMMITTED | confirmed in docs |
| F6 | Composed pattern: the subquery locks one `queued` row and skips rows other workers hold. The outer `UPDATE` then changes a row this transaction already holds, so it does not wait on it. A row that another worker committed as non-`queued` fails the re-check in F5 and is not returned. Result: each row is claimed by at most one worker at a time. | derived from F1, F3, F4, F5 | inferred |
| F7 | With `ORDER BY` plus a locking clause under READ COMMITTED, rows can come back out of order if the ordering columns changed while the command waited for a lock. | https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE | confirmed in docs |
| F8 | Use `id = (scalar subquery)`, not `id IN (subquery)`. A scalar subquery is evaluated once as an InitPlan. With `IN`, the planner may turn the subquery into a join and run it more than once, which can lock or update more than `LIMIT` rows. | community knowledge; not in the official docs | inferred (blogs/forums, not verified here) |
| F9 | PG15 release note: "Allow unique constraints and indexes to treat `NULL` values as not distinct ... using `UNIQUE NULLS NOT DISTINCT`." | https://www.postgresql.org/docs/15/release-15.html | confirmed in docs |
| F10 | Table constraint syntax: `UNIQUE [ NULLS [ NOT ] DISTINCT ] ( column_name [, ... ] )`. "For the purpose of a unique constraint, null values are not considered equal, unless `NULLS NOT DISTINCT` is specified." | https://www.postgresql.org/docs/16/sql-createtable.html | confirmed in docs |
| F11 | `CREATE INDEX` accepts `[ NULLS [ NOT ] DISTINCT ]` and `[ WHERE predicate ]` in the same statement. By default nulls are distinct, so a unique index can hold many NULLs. | https://www.postgresql.org/docs/16/sql-createindex.html | confirmed in docs |
| F12 | A partial index predicate may refer only to columns of the table. Subqueries and aggregates are forbidden. All functions and operators must be immutable. | same | confirmed in docs |
| F13 | A partial unique index "enforces uniqueness among the rows that satisfy the index predicate, without constraining those that do not." | https://www.postgresql.org/docs/16/indexes-partial.html | confirmed in docs |
| F14 | The planner uses a partial index only when the query's `WHERE` provably implies the index predicate, and it decides this at plan time. A parameter such as `stage <> $1` will not match a predicate with literals. | same | confirmed in docs |
| F15 | `stage NOT IN ('done','failed')` evaluates to NULL when `stage` is NULL. Rows with a NULL `stage` are then outside the index and not constrained. Declare `stage NOT NULL`. | follows from SQL three-valued logic plus F13 | inferred |
| F16 | `INSERT ... ON CONFLICT` can only use a partial unique index as the arbiter if the conflict target repeats the predicate: `ON CONFLICT (cols) WHERE <predicate>`. | https://www.postgresql.org/docs/16/sql-insert.html | inferred (not re-fetched on the date checked) |
| F17 | PG13 release note: "Add function `gen_random_uuid()` to generate version-4 UUIDs ... Previously UUID generation functions were only available in the external modules uuid-ossp and pgcrypto." | https://www.postgresql.org/docs/13/release-13.html | confirmed in docs |
| F18 | PG16 docs: "PostgreSQL includes one function to generate a UUID: `gen_random_uuid`. This function returns a version 4 (random) UUID." uuid-ossp provides the other UUID algorithms. | https://www.postgresql.org/docs/16/functions-uuid.html | confirmed in docs |

## Examples

Copied from the docs:

```sql
-- Partial unique index (docs/16/indexes-partial.html, Example 11.3)
CREATE UNIQUE INDEX tests_success_constraint ON tests (subject, target)
    WHERE success;

-- Locking in a sub-select (docs/16/sql-select.html)
SELECT * FROM (SELECT * FROM mytable FOR UPDATE) ss WHERE col1 = 5;  -- locks only col1 = 5 rows
```

Applied to this project. This is illustrative, not from the docs. The contracts ticket owns the real schema.

```sql
-- Claim one job (READ COMMITTED, autocommit or short transaction)
UPDATE jobs
SET    stage = 'running', claimed_at = now(), attempts = attempts + 1
WHERE  id = (
         SELECT id FROM jobs
         WHERE  stage = 'queued'
         ORDER  BY created_at
         LIMIT  1
         FOR UPDATE SKIP LOCKED
       )
RETURNING *;
-- Returns zero rows when the queue is empty or every queued row is locked by another worker.

-- One active job per key; finished jobs do not count
CREATE UNIQUE INDEX jobs_one_active_per_key
    ON jobs (kind, dedupe_key) NULLS NOT DISTINCT
    WHERE stage NOT IN ('done', 'failed');

-- Primary key default without pgcrypto (PG13+)
id uuid PRIMARY KEY DEFAULT gen_random_uuid()
```

## Limits and caveats

- `SKIP LOCKED` gives an inconsistent view of the data (F1). Use it only for the claim step. Do not use it for
  reporting or counting.
- `ORDER BY created_at` with SKIP LOCKED is best-effort FIFO. Rows locked by other workers are skipped, and
  ordering is not strict under concurrency (F7).
- The claim and the work are separate. If a worker commits `running` and then crashes, nothing frees that row.
  You need a lease or timeout sweep, for example `claimed_at < now() - interval '15 minutes'`. This is a design
  choice, not a Postgres guarantee.
- If the whole job runs inside the claiming transaction, a crash rolls the claim back. The cost is a
  transaction left open for the length of the job.
- The predicate of the partial index must use literals in `NOT IN (...)` (F12, F14). If the set of stages
  changes, you must recreate the index.
- `NULLS NOT DISTINCT` requires PG15 or later (F9). On PG14 or earlier the `CREATE INDEX` statement fails.

## Open questions

1. Confirm the server version of the target deployment. The founder can run `SELECT version();` or
   `SHOW server_version_num;` (needs at least 150000 for NULLS NOT DISTINCT; PG16 is 160000 or higher).
2. F8 (scalar `=` vs `IN`) is not in the official docs. To confirm the plan on the real schema, run
   `EXPLAIN (VERBOSE) <claim query>;` and check that it shows `InitPlan` for the subquery.
3. F16 was not re-fetched. Check https://www.postgresql.org/docs/16/sql-insert.html (the `conflict_target` /
   `index_predicate` section) before any ticket depends on `ON CONFLICT` against the partial index.
4. The lease or timeout length and the retry policy for crashed workers are product decisions for the architect.
