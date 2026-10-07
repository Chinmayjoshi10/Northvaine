# Deploying Northvaine on Nebius

Date checked: 2026-10-08. Every fact below carries its source. Anything marked **UNCONFIRMED**
was not found in the official docs; do not rely on it. No secret values appear in this file:
environment variables are listed by name only.

## 1. What was confirmed, with sources

| # | Fact | Source |
|---|---|---|
| D1 | Serverless AI runs a container as an **endpoint** (listens for requests, gets a managed public HTTPS URL, can be stopped and started) or a **job** (non-interactive, ends on completion or timeout, no public URL, cannot be stopped and restarted). | https://docs.nebius.com/serverless/overview |
| D2 | Create an endpoint with `nebius ai endpoint create`. Flags: `--name`, `--image`, `--platform`, `--preset`, `--container-port`, `--env KEY=VALUE` (repeatable), `--env-secret KEY=SECRET_SELECTOR` (repeatable), `--auth none\|token`, `--token`, `--token-secret`, `--public`, `--subnet-id`, `--container-command`, `--args`, `--registry-username`, `--registry-password`, `--registry-secret`, `--disk-size` (default 250Gi), `--async`, `--dry-run`. Creation takes about five minutes. | https://docs.nebius.com/serverless/endpoints/manage , https://docs.nebius.com/cli/reference/ai/endpoint/create |
| D3 | The quickstart uses a **CPU** platform: `--platform cpu-d3 --preset 4vcpu-16gb`. | https://docs.nebius.com/serverless/quickstart/endpoints |
| D4 | Each HTTP container port gets a managed `https://` URL, read from `status.public_endpoints` with `nebius ai endpoint get`. `--public` (a public IP) is not needed to reach the endpoint from the internet. | https://docs.nebius.com/serverless/endpoints/manage , https://docs.nebius.com/serverless/quickstart/endpoints |
| D5 | `--auth token` makes callers send `Authorization: Bearer <token>`. Without `--auth` (default `none`) the endpoint is open. | https://docs.nebius.com/serverless/endpoints/manage , https://docs.nebius.com/cli/reference/ai/endpoint/create |
| D6 | Job: `nebius ai job create --name --image --container-command --args --platform --preset --timeout`. `--timeout` minimum 1h, maximum 168h, default 24h. `--restart-policy on-failure\|never`. Logs: `nebius ai job logs <job_ID> --follow`. | https://docs.nebius.com/serverless/jobs/manage |
| D7 | Env vars: `--env` for plain values, `--env-secret KEY=SELECTOR` for secrets from MysteryBox (renamed SecretStash; the CLI still says `mysterybox`). A key cannot be in both. | https://docs.nebius.com/serverless/jobs/manage , https://docs.nebius.com/mysterybox/secrets/create |
| D8 | Create a secret: `nebius mysterybox secret create --name <n> --secret-version-payload '[{"key":"K","string_value":"V"}]'`. Viewing payloads needs the `mysterybox.payload-viewer` role. | https://docs.nebius.com/mysterybox/secrets/create |
| D9 | Container Registry: `nebius registry create --name <n>` (the FQDN is at `status.registry_fqdn`, pattern `cr.<region_ID>.nebius.cloud`). `nebius registry configure-helper` sets up a Docker credential helper, so `docker login` is not needed. Image tag form: `cr.<region>.nebius.cloud/<registry-name>/<image>:<tag>`. Images from a Container Registry in the same project need no pull credentials. | https://docs.nebius.com/container-registry/quickstart , https://docs.nebius.com/container-registry/registries/manage |
| D10 | Public regions: `eu-north1` (Finland), `eu-west1` (France), `me-west1` (Israel), `us-central1` (Kansas City, US). The current Serverless AI page says it is available in all public regions; older wording excluded some non-public regions. Confirm in your own project. | https://docs.nebius.com/overview/regions , https://docs.nebius.com/serverless |
| D11 | Serverless AI has no pricing of its own: it is billed like Compute VMs, per second. A stopped endpoint is not billed for compute or storage. Jobs are billed while running. The service is described as **Preview** with no service level. | https://docs.nebius.com/serverless/pricing-quotas , https://docs.nebius.com/legal/specific-terms/serverless-ai |
| D12 | Compute rates (USD, before taxes), non-GPU AMD Epyc Genoa: vCPU-hour $0.012 until 30 Sep 2026, **$0.015 from 1 Oct 2026**; GiB-RAM-hour $0.0032, then **$0.0045**. Network SSD disk $0.071 per GiB per 730 h. | https://docs.nebius.com/compute/resources/pricing |
| D13 | Neon is a separate service (not on Nebius). Use the direct host for migrations and the `-pooler` host (PgBouncer, transaction mode) for the app. | `docs/integrations/postgres-hosting.md` (E5, E6) |

### Rough cost (computed, not quoted)

Assumption, **UNCONFIRMED**: the `cpu-d3` platform is billed at the "Non-GPU AMD Epyc Genoa" rate. The
pricing page does not name `cpu-d3`.

- Preset `4vcpu-16gb` at the rates from 1 Oct 2026: 4 x 0.015 + 16 x 0.0045 = **$0.132 per hour**,
  about $95 per 30-day month if left running, plus disk. The default disk is 250 GiB
  (about $24 per month at $0.071 per GiB-month) unless lowered with `--disk-size`.
- A smaller preset may exist (for example 2vcpu-8gb); the preset list for `cpu-d3` was **not found**.
  Run `nebius ai endpoint create --help` or use the console to see it.
- Cheapest plan for a hackathon: run the endpoint only for the judging window and **stop** it
  otherwise (stopped endpoints are not billed for compute or storage, D11).
- A nightly job at 4vcpu-16gb for 30 minutes costs about $0.07.
- Hackathon or promo credits: unknown. Promo codes exist (`docs/integrations/postgres-hosting.md`, N13).

## 2. Open questions (could not be confirmed from official docs)

1. **Scheduled or cron jobs.** The jobs page mentions "scheduled batch workloads" in passing but documents
   no schedule or cron option. Assume there is none. Fallback for the nightly run: a GitHub Actions
   `schedule:` workflow that runs `nebius ai job create` (needs a Nebius service account credential
   stored as a GitHub secret), or the founder starts the job by hand before the demo.
2. **Health checks.** No health-check, probe or replica flag exists on `nebius ai endpoint create`
   (checked the CLI reference). The image carries a Docker `HEALTHCHECK`, but whether Nebius reads it
   is **UNCONFIRMED**. Monitor `GET /health` from outside instead.
3. **Autoscaling and scale to zero.** Not documented. Treat the endpoint as one always-on instance
   that you stop and start by hand. The stop command was not on the pages read (the quickstart shows
   only delete); look in `nebius ai endpoint --help`.
4. **Reaching Neon from a Serverless endpoint.** Neon is reached over the public internet with
   `ssl=require`. No Nebius egress restriction was found, but outbound access from endpoints is **UNCONFIRMED**.
5. **Whether `--auth token` fits a public demo.** A token-protected endpoint returns 401 to judges.
   For a public demo URL use `--auth none` (the app has no login yet), or put the app's own login in
   front. Decide before deploying.
6. **Preset list and exact price for `cpu-d3`** (see above).
7. **Frontend.** `frontend/` does not exist on this branch yet. The Docker image therefore serves
   only the API. Once the web app exists, either build it in a Node stage and serve `frontend/dist`
   from FastAPI (`StaticFiles`), or host the static build elsewhere. Neither is done yet.
8. **Nightly module.** `northvaine/jobs/nightly.py` does not exist yet (`scripts/tasks.py nightly`
   reports "available from a later milestone"). Until it does, the job command below runs the radar script.

## 3. Prerequisites (once)

1. A Nebius AI Cloud account with a project in one public region (examples use `eu-north1`; any
   region from D10 works). Install and configure the CLI: `nebius profile create`.
   Also install Docker and `jq`.
2. A Neon project (see `docs/integrations/postgres-hosting.md`). Create a branch or database for the
   demo; keep it separate from the test branch (`TEST_DATABASE_URL`).
3. Keys: Nebius Token Factory key, Tavily key. Never paste them into a file in the repo.

## 4. Build and push the image

```bash
# from the repo root
nebius registry create --name northvaine
nebius registry configure-helper          # one-off, replaces docker login
# registry host: nebius registry list  ->  status.registry_fqdn  (cr.<region>.nebius.cloud)
export REG=cr.<region>.nebius.cloud/northvaine
docker build -t $REG/northvaine:$(git rev-parse --short HEAD) .
docker push $REG/northvaine:$(git rev-parse --short HEAD)
```

Check locally first (no secrets needed for `/health`):

```bash
docker run --rm -p 8000:8000 northvaine
curl http://127.0.0.1:8000/health      # {"status":"ok"}
```

## 5. Database

Migrations need a **direct** (non-pooled) Neon connection:

```bash
DATABASE_URL='<direct neon url, postgresql+asyncpg://...?ssl=require>' uv run python scripts/tasks.py migrate
```

The running app uses the pooled host with `DB_POOL_MODE=transaction`. Variable names are in `.env.example`.

## 6. Secrets

Create one MysteryBox/SecretStash secret per sensitive value (D8). Values are typed at the prompt
or taken from your shell; do not commit them.

```bash
nebius mysterybox secret create --name nv-env --secret-version-payload '[
  {"key":"DATABASE_URL","string_value":"..."},
  {"key":"NEBIUS_API_KEY","string_value":"..."},
  {"key":"TAVILY_API_KEY","string_value":"..."}
]'
```

The `--env-secret KEY=SELECTOR` flag form takes a secret name, ID or version selector (D7). How a
single payload key is selected from a multi-key secret is **UNCONFIRMED**: check
`nebius ai endpoint create --help` or the console ("Secret environment variables"). If unclear,
make one secret per key.

## 7. Environment variables (names only)

Secret (use `--env-secret`):

| Name | Used for |
|---|---|
| `DATABASE_URL` | Neon pooled URL for the app |
| `NEBIUS_API_KEY` | Token Factory |
| `TAVILY_API_KEY` | Tavily search |

Plain (use `--env`; values are choices, not secrets):

| Name | Note |
|---|---|
| `NEBIUS_BASE_URL` | Token Factory OpenAI-compatible base URL (`docs/integrations/nebius-token-factory-api-surface-and-client.md`) |
| `MODEL_FAST`, `MODEL_MID`, `MODEL_DEEP` | Nemotron model ids from the Token Factory catalog |
| `MODEL_EMBED`, `EMBED_DIM` | Embedding model and its dimension (must match `northvaine.core.standards`) |
| `DAILY_BUDGET_USD`, `TOTAL_BUDGET_USD` | Required: LLM calls refuse to run without them. Set them equal. |
| `RUN_BUDGET_USD`, `MAX_CALL_COST_USD` | Optional, defaults in `northvaine/core/settings.py` |
| `DB_POOL_MODE` | `transaction` for a Neon `-pooler` host |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | Optional |
| `PORT` | Defaults to 8000 in the image |

`TEST_DATABASE_URL` and `TEST_DB_ISOLATION` are for tests only. Never set them in production.

## 8. Deploy the API endpoint

```bash
nebius ai endpoint create \
  --name northvaine-api \
  --image $REG/northvaine:<tag> \
  --platform cpu-d3 --preset 4vcpu-16gb \
  --container-port 8000 \
  --disk-size 30Gi \
  --auth none \
  --env NEBIUS_BASE_URL=<url> --env MODEL_FAST=<id> --env MODEL_MID=<id> --env MODEL_DEEP=<id> \
  --env MODEL_EMBED=<id> --env EMBED_DIM=<n> \
  --env DAILY_BUDGET_USD=<n> --env TOTAL_BUDGET_USD=<n> --env DB_POOL_MODE=transaction \
  --env-secret DATABASE_URL=<selector> --env-secret NEBIUS_API_KEY=<selector> \
  --env-secret TAVILY_API_KEY=<selector> \
  --subnet-id <subnet_ID> --dry-run    # remove --dry-run to create
```

`--disk-size 30Gi` is an assumption that the minimum is acceptable; the docs give only the 250Gi
default (D2). Add `--subnet-id` only if the project has several subnets.

Get the URL and check health:

```bash
ID=$(nebius ai endpoint get-by-name --name northvaine-api --format jsonpath='{.metadata.id}')
URL=$(nebius ai endpoint get "$ID" --format json | jq -r '.status.public_endpoints[] | select(startswith("https://"))' | head -1)
curl "$URL/health"          # {"status":"ok"}
```

Update: push a new tag, delete the endpoint, create it again (an in-place update command was not
found in the pages read).

## 9. Nightly radar job

Same image, a different command. Until `northvaine.jobs.nightly` exists, the command is the radar
script (it needs a client id from `tests/fixtures/clients/`; a live run needs `--record --yes` and
spends money, so the job below uses the offline replay):

```bash
nebius ai job create \
  --name northvaine-radar \
  --image $REG/northvaine:<tag> \
  --platform cpu-d3 --preset 4vcpu-16gb \
  --container-command python \
  --args "scripts/radar.py --client stone_supplier" \
  --timeout 1h --restart-policy never \
  --env-secret DATABASE_URL=<selector> --env-secret NEBIUS_API_KEY=<selector> \
  --env-secret TAVILY_API_KEY=<selector> --env NEBIUS_BASE_URL=<url> --env MODEL_FAST=<id> \
  --env MODEL_MID=<id> --env MODEL_DEEP=<id> --env DAILY_BUDGET_USD=<n> --env TOTAL_BUDGET_USD=<n>
nebius ai job logs <job_ID> --follow
```

How `--args` splits arguments was not shown; check `nebius ai job create --help`. The minimum job
timeout is 1h (D6). Scheduling is open question 1.

## 10. Check list before the public demo

- [ ] `curl $URL/health` returns ok.
- [ ] Endpoint auth mode chosen deliberately (open vs token).
- [ ] Budgets set; Tavily and Token Factory keys are in secrets, not in `--env`.
- [ ] Neon demo branch is separate from the test branch.
- [ ] Stop or delete the endpoint after judging to stop charges.
