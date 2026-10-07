# Northvaine

Northvaine is an AI sales assistant for real-world B2B businesses such as exporters,
manufacturers, distributors and logistics firms. **Radar** finds organisations that are about to
buy, at the right moment, from public tenders, award notices, news and company pages, and writes a
short brief in which every fact links to a saved copy of its source. **Gateway** (planned) makes the
business findable and answerable to people and AI agents. A person always negotiates and decides:
Northvaine never sends anything and never quotes prices.

Built for the Nebius x NVIDIA Global AI Hackathon, Best Apps and Agents track (with the Tavily bonus).

## How it works, in brief

1. **Business profile.** A client spec (what they sell, where, to whom) is turned into search
   theses and queries by an LLM. Nothing is hard-coded for any industry; business knowledge is data.
2. **Sensors** fetch candidate buyers: Tavily search, the EU TED tenders API, and public web pages
   (robots-respecting). All fetched content is treated as untrusted data and fenced in prompts.
3. **Gate.** Competitors and sellers of the client's own offer are rejected before any investigation.
4. **Evidence.** Every fact is a claim linked to a stored document snapshot. Code checks that the
   quoted text really appears in the snapshot before any model judges it. Unverified claims are never
   shown, scored or used.
5. **Skeptic before judge.** Each case stores the evidence against it, or says "unknown".
6. **Brief.** A one-screen summary, what is stated versus inferred, and next actions. Drafts and
   approval only: no real sending.

Architecture notes: `docs/ARCHITECTURE.md`. Exact specs: `docs/SPEC.md`. Rules: `CLAUDE.md`.

## Where the sponsors are used

| Technology | Where | What for |
|---|---|---|
| **NVIDIA Nemotron** | `northvaine/brain/llm.py` (model routing by tier `MODEL_FAST`, `MODEL_MID`, `MODEL_DEEP`); prompts in `northvaine/brain/prompts/` (`radar_gate`, `radar_skeptic`, `evidence_extract`, `claim_support`) | Gate, evidence extraction, claim checking, skeptic |
| **Nebius Token Factory** | `northvaine/brain/llm.py` (OpenAI-compatible client, `NEBIUS_BASE_URL`, `NEBIUS_API_KEY`); `scripts/smoke_llm.py` for a live check | Serves the Nemotron models. Every call is Pydantic-validated, budget-capped and logged to the `llm_calls` table |
| **Tavily** | `northvaine/sensors/tavily.py` | Web search for buying signals, with a hard budget stop |
| Nebius Serverless | `Dockerfile`, `docs/DEPLOY.md` | Hosting the API and job |

Every model call goes through the one file `northvaine/brain/llm.py` (enforced by
`scripts/check_invariants.py`). Embeddings: Token Factory serves no Nemotron embedding model, so the
catalog's Qwen embedder is used for embeddings (see `docs/DECISIONS.md`, D6); generation uses Nemotron.

## Setup

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), and for the full app a Postgres 16 with
pgvector (Neon works).

```bash
uv run python scripts/tasks.py setup      # uv sync
cp .env.example .env                      # then fill the names in; never commit .env
uv run python scripts/tasks.py migrate    # needs DATABASE_URL
uv run python scripts/tasks.py dev        # run the API locally
uv run python scripts/tasks.py gate       # lint, invariants, unit tests, golden set
```

## Try it offline (no keys, no network)

The radar can run a full cycle from recorded sensor and model responses:

```bash
uv run python scripts/tasks.py radar -- --client stone_supplier
```

Other recorded clients: `coldchain_maker`, `packaging_supplier` (specs in `tests/fixtures/clients/`).
Reports are written to `reports/radar/` (git-ignored). Live recording (`record-radar`) spends real
money and needs keys.

## Run with Docker

```bash
docker build -t northvaine .
docker run --rm -p 8000:8000 --env-file .env northvaine
curl http://127.0.0.1:8000/health
```

Deploying on Nebius: `docs/DEPLOY.md`.

## Honest status

- Working: the radar pipeline (gate, evidence ledger with source-quote verification, skeptic, brief),
  TED and Tavily sensors, the LLM layer with budgets and a ledger, database schema and migrations,
  offline replay, the golden test set.
- In progress or planned: the web app for leads and feedback, UK tenders, the learning loop from
  owner feedback, the Gateway, the scheduled nightly run.
- Not done: any real sending of messages (by design), and a public demo URL (placeholder:
  `TODO: add demo URL`).
- Model output is probabilistic. Briefs are drafts for a person to review.

## Licence

MIT, see `LICENSE`.

## Feedback on Token Factory, Nebius and NVIDIA tools

_Founder to fill in before submission. Prompts:_

- **Token Factory:** What worked first time? What did the docs get wrong or leave out (for example
  the `response_format` nesting and `reasoning_effort` behaviour we measured against the live API)?
  How was latency and cost per call? Anything you wished the model catalog or usage dashboard showed?
- **Nemotron:** Which tier (fast, mid, deep) was worth its price for which task? Where did structured
  JSON output fail or surprise you? How did it compare on long source documents?
- **Nebius Serverless / Container Registry:** How long did first deploy take? Was Preview status a
  problem? What was missing (scheduled jobs, health checks, scaling, stop/start)?
- **Nebius Managed services or credits:** Anything about billing, quotas or support worth passing on?
- **Tavily:** Result quality for B2B buying signals, rate limits, cost per useful lead.
