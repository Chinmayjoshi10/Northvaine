# Postgres hosting options

Date checked: 2026-10-02. Researcher notes per `docs/FACTORY.md` rule 7. No secrets in this file.

## Summary

- **All three options support Postgres 16+**, so `UNIQUE NULLS NOT DISTINCT` (added in PG15) works on all of them.
- **Nebius Managed Service for PostgreSQL** supports **only PostgreSQL 16**. It ships pgvector 0.8 and
  pgcrypto 1.3 pre-installed (enable with `CREATE EXTENSION`; you cannot add other extensions).
  It is billed per second at $0.034/vCPU-h + $0.009/GiB-RAM-h + $0.071/GiB-month SSD. The quickstart
  preset is `2vcpu-8gb`, one host, a 96 GiB disk: about **$0.14/h, roughly $102/month compute plus about $6.8/month disk** if left running.
  The docs state no free tier and no hackathon credits. Promo codes exist (see below).
- **Neon** supports PG 14 to 18 and pgvector 0.8.0 (PG14 to 17) or 0.8.6 (PG18). The free plan gives
  **1 GB storage per project** (20 GB per account), **100 CU-hours per project per month**, and scale-to-zero after 5 minutes,
  which cannot be disabled. Branching gives instant copy-on-write databases with an optional expiry,
  which works well for disposable test databases. It has a London region (`aws-eu-west-2`).
- **Local Windows**: the official installer is EDB's and covers PG 16 on Windows (the EDB table lists Server 2022/2019; Windows 11 is
  not listed by name). **pgvector has no official prebuilt Windows binary.** The official paths are:
  build with Visual Studio C++ tools (`nmake`), conda-forge, or Docker. Without Visual Studio, use
  **conda-forge** (`conda install -c conda-forge pgvector`, which brings its own Postgres) or **Docker**
  (`pgvector/pgvector` image).

Recommendation input for the architect (not a decision): use Neon (London, PG16 or 17) for dev and tests through branches,
and Docker `pgvector/pgvector:pg16` locally for offline tests. Use Nebius Managed PG only if workloads on Nebius need a
private-network DB and the founder accepts the always-on cost of about $0.14/h.

## Facts table

| # | Fact | Source | Confidence |
|---|---|---|---|
| N1 | Nebius Managed PG: "The service currently supports only version 16." | https://docs.nebius.com/postgresql/clusters/manage | confirmed in docs |
| N2 | Nebius: `vector` (pgvector) **0.8** is pre-installed. It defines the vector type with `ivfflat` and `hnsw`. | https://docs.nebius.com/postgresql/databases/extensions | confirmed in docs (the patch version is not given) |
| N3 | Nebius: `pgcrypto` **1.3** is pre-installed. | https://docs.nebius.com/postgresql/databases/extensions | confirmed in docs |
| N4 | Nebius: extensions are pre-installed and enabled with `CREATE EXTENSION <name>;`. You cannot install any other extension. | https://docs.nebius.com/postgresql/databases/extensions | confirmed in docs |
| N5 | Nebius pricing: CPU $0.034/h per vCPU, RAM $0.009/h per GiB (Ice Lake and Genoa are the same). Billed per second. Example given: `4vcpu-16gb` = $0.28/h. | https://docs.nebius.com/postgresql/resources/pricing | confirmed in docs |
| N6 | Nebius storage: network SSD $0.071 per GiB-month (730 h). Public access is free of charge. | https://docs.nebius.com/postgresql/resources/pricing | confirmed in docs |
| N7 | Nebius quickstart uses preset `2vcpu-8gb`, 1 host, 96 GiB disk, `--config-public-access`. At N5 rates that is 2×0.034 + 8×0.009 = **$0.14/h**. | https://docs.nebius.com/postgresql/quickstart | preset confirmed; the cost is computed. Whether a smaller preset exists is **unknown**. |
| N8 | Nebius quotas per region: 10 clusters, 80 vCPU, 320 GiB RAM, 2 TiB SSD in total. | https://docs.nebius.com/postgresql/resources/quotas-limits | confirmed in docs |
| N9 | Nebius connection: `psql "host=<cluster_endpoint> port=5432 sslmode=verify-full dbname=<DB_name> user=<username>"`. The Nebius CA cert goes in `~/.postgresql/root.crt`. Console → cluster → **How to connect** gives the prefilled command. | https://docs.nebius.com/postgresql/databases/connect | confirmed in docs |
| N10 | Nebius endpoints: the **public** endpoint (only if public access was enabled at creation) is for the internet, so a home Windows machine can reach it. The **private** endpoint is for other Nebius AI Cloud resources. | https://docs.nebius.com/postgresql/databases/connect , https://docs.nebius.com/postgresql/clusters/manage | confirmed in docs |
| N11 | Nebius has a built-in pooler with Session (default) or Transaction mode. | https://docs.nebius.com/postgresql/clusters/manage | confirmed in docs (the pooler port is not documented) |
| N12 | Nebius Serverless endpoints and jobs run in a subnet you pick, with a private or public IP option for jobs. The docs do not say explicitly that they can reach a Managed PG private endpoint in the same network. | https://docs.nebius.com/serverless/endpoints/manage , https://docs.nebius.com/serverless/jobs/manage | inferred: likely, since both sit in the same VPC subnet. Not confirmed. |
| N13 | Nebius credits: promo codes add credits to your balance and usually expire. A payment method is required, with a $25 verification charge added to the balance. The docs do not mention hackathon credits or which services the credits cover. | https://docs.nebius.com/signup-billing/payments/promo-codes | confirmed (hackathon credits **unknown**) |
| E1 | Neon supports Postgres 14, 15, 16, 17 and 18. You choose the version at project creation. | https://neon.com/docs/reference/compatibility | confirmed in docs |
| E2 | Neon `vector` versions: 0.8.0 on PG14 to 17, **0.8.6 on PG18**. `pgcrypto` 1.3 on PG14 to 17, 1.4 on PG18. Enable with `CREATE EXTENSION vector;`. | https://neon.com/docs/extensions/pg-extensions | confirmed in docs |
| E3 | Neon Free: 1 GB storage per project (20 GB per account); 100 CU-hours per project per month (about 400 h at 0.25 CU); scale to zero after 5 min, which cannot be disabled; 100 projects; 10 branches per project; 5 GB public transfer per project per month; 1 day of monitoring history. | https://neon.com/docs/introduction/plans | confirmed in docs |
| E4 | Neon Free overage: if compute hours or transfer run out, the compute suspends until the next cycle. If storage is exceeded, writes fail. | https://neon.com/docs/introduction/plans | confirmed in docs |
| E5 | Neon pooled vs direct: add `-pooler` to the endpoint id in the host. The pooler is PgBouncer in **transaction mode** (`max_client_conn=10000`). | https://neon.com/docs/connect/connection-pooling | confirmed in docs |
| E6 | Neon pooled mode does not support `SET`/`RESET`, `LISTEN`/`NOTIFY`, SQL-level `PREPARE`/`DEALLOCATE`, temp tables or `WITH HOLD` cursors. Protocol-level prepared statements work. Use the direct connection for migrations, `pg_dump` and session state. | https://neon.com/docs/connect/connection-pooling | confirmed in docs |
| E7 | Neon branches are copy-on-write, created instantly, have no impact on the parent, can have an expiry (TTL), and can be reset from the parent. | https://neon.com/docs/introduction/branching | confirmed in docs |
| E8 | Neon regions: AWS us-east-1, us-east-2, us-west-2, **eu-central-1 (Frankfurt)**, **eu-west-2 (London)**, ap-southeast-1, ap-southeast-2, sa-east-1. Azure regions are deprecated for new projects. | https://neon.com/docs/introduction/regions | confirmed in docs |
| E9 | Neon does not support tablespaces, true superuser (you get `neon_superuser` instead) or `track_commit_timestamp`. Unlogged tables are lost on compute restart or scale-to-zero. | https://neon.com/docs/reference/compatibility | confirmed in docs |
| W1 | The official Windows installer is from EDB and includes the server, pgAdmin and StackBuilder. PG16 is listed for 64-bit Windows Server 2022/2019. | https://www.postgresql.org/download/windows/ | confirmed in docs (Windows 11 is not named in the table) |
| W2 | pgvector on Windows (official README): needs "C++ support in Visual Studio" and the "x64 Native Tools Command Prompt", then `nmake /F Makefile.win`. The latest version is 0.8.7. | https://github.com/pgvector/pgvector | confirmed in docs |
| W3 | pgvector has **no GitHub release binaries**. The releases page says "There aren't any releases here"; there are tags only. | https://github.com/pgvector/pgvector/releases | confirmed |
| W4 | pgvector's other official install paths are `conda install -c conda-forge pgvector` and `docker pull pgvector/pgvector:pg18-trixie` (other `pgNN` tags exist). | https://github.com/pgvector/pgvector | confirmed in docs (the exact `pg16` tag name is inferred) |
| W5 | pgvector is not reliably available in EDB StackBuilder. Third-party prebuilt DLLs exist (e.g. github.com/andreiramani/pgvector_pgsql_windows). | web search, non-official | **forum/third-party, last resort, not recommended** |
| W6 | Known Windows build issue: "unresolved external symbol" on PG 17.0 to 17.2; upgrade to 17.3+. | https://github.com/pgvector/pgvector | confirmed in docs |
| P1 | `UNIQUE NULLS NOT DISTINCT` was added in PostgreSQL **15.0**, so all options above (PG16+) support it. | https://www.postgresql.org/docs/release/15.0/ , https://www.postgresql.org/docs/current/sql-createindex.html | confirmed in docs |

## Examples (copied from docs, placeholders only)

Nebius (https://docs.nebius.com/postgresql/databases/connect):
```bash
psql "host=<cluster_endpoint> \
  port=5432 \
  sslmode=verify-full \
  dbname=<DB_name> \
  user=<username>"
```
As a libpq URL (inferred equivalent): `postgresql://<username>:<password>@<cluster_endpoint>:5432/<DB_name>?sslmode=verify-full&sslrootcert=<path-to-root.crt>`.
On Windows, libpq's default root cert path is `%APPDATA%\postgresql\root.crt`, not `~/.postgresql/root.crt`. That comes from the libpq docs and was not re-checked today, so treat it as inferred.

Neon (https://neon.com/docs/connect/connection-pooling):
```
# direct
postgresql://user1:AbC123dEf@ep-cool-darkness-123456.us-east-2.aws.neon.tech/dbname?sslmode=require
# pooled
postgresql://user1:AbC123dEf@ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech/dbname?sslmode=require
```

Neon disposable test branch (https://neon.com/docs/reference/cli-branches):
```bash
neon branches create --name mybranch --expires-at 2025-08-15T18:00:00Z
neon connection-string mybranch            # direct
neon connection-string mybranch --pooled   # pooled
neon branches delete mybranch
```

pgvector on Windows with Visual Studio (https://github.com/pgvector/pgvector), run in the "x64 Native Tools Command Prompt" as admin:
```
set "PGROOT=C:\Program Files\PostgreSQL\18"
cd %TEMP%
git clone --branch v0.8.7 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
```
Without Visual Studio:
```
docker pull pgvector/pgvector:pg18-trixie        # from README; pick a pg16 tag for PG16
conda install -c conda-forge pgvector
```

PG15+ feature check (https://www.postgresql.org/docs/release/15.0/):
```sql
CREATE TABLE t (k text UNIQUE NULLS NOT DISTINCT);
```

## Limits

- Nebius: PG16 only. Extension set is fixed. Disk can only grow. 10 clusters and 80 vCPU per region. No free tier is documented. The cluster bills while it runs; no scale-to-zero is documented.
- Neon Free: 1 GB per project, 100 CU-h per project per month, 10 branches per project, 5 GB transfer. Scale-to-zero after 5 min adds a cold start on the first query. The pooled endpoint is transaction mode only (no `LISTEN/NOTIFY`, no session `SET`), so use the direct string for migrations and session features. Unlogged tables are not durable.
- Local Windows: pgvector needs a build toolchain, conda or Docker. There is no official DLL.

## Open questions (for the founder)

1. **Nebius hackathon credits**: not in the docs. Ask the hackathon organisers whether a promo code is provided and whether it covers Managed PostgreSQL. Apply it at Console → Billing → Apply promo code.
2. **Smallest Nebius preset**: only `2vcpu-8gb` appears in the quickstart. Check with the Nebius CLI:
   `nebius msp postgresql v1alpha1 cluster create --help` (the command path is inferred; confirm with `nebius msp --help`) or look at the preset dropdown in the console.
3. **Serverless to Managed PG over a private network**: not documented. To confirm, create both in the same project/subnet, then run a job with `pg_isready -h <private_endpoint> -p 5432` (or `psql ... -c "select 1"`).
4. **Nebius pooler port and connection string**: copy from Console → cluster → How to connect.
5. **Nebius pgvector patch version**: after connecting, run `SELECT extversion FROM pg_extension WHERE extname='vector';` (after `CREATE EXTENSION vector;`) or `SELECT * FROM pg_available_extensions WHERE name IN ('vector','pgcrypto');`.
6. **Nebius regions where Managed PG runs**: the changelog says it is in eu-west2 (France) among others. Not checked in detail.
7. **Neon defaults**: the default PG version for new projects is not stated. Pick 16 or 17 explicitly.
