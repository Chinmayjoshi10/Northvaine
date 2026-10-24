# Northvaine

**Intent data for the real economy.** Northvaine finds the companies most likely to buy what a B2B
business sells, *soon*, and tells the seller why, when and what to say. It reads official trade
records, public tenders and contract awards, company registers, company websites and project news
across the client's markets, connects the dots, and hands over **five leads a day**, each with every
fact quoted from its source.

- **Live demo:** https://chinmayjoshi10.github.io/Northvaine/ (the sample client is an anonymised
  Indian natural-stone exporter selling to the UK, US, Germany, France, Italy, UAE, Saudi Arabia
  and Qatar)
- **Try it on your own business:** the demo's "Build my radar" (live server:
  https://northvaine.onrender.com - free hosting, may take a minute to wake)
- **Video:** _link added at submission_
- **Track:** Best Apps and Agents - Nebius x NVIDIA Global AI Hackathon

## The problem

A manufacturer, exporter or distributor wins business by calling the right company at the right
moment: when a hotel is about to be fitted out, when a distributor opens a new branch and needs a new
supplier, when an importer starts buying the product. Those moments are public, but scattered across
government registers, tender portals, trade records, company sites and news in many countries and
languages. Today a salesperson spends days searching, and most of what they find is either the wrong
kind of company or already too late. Tools that sell "intent data" track website clicks for software
companies; nobody does it for businesses that sell physical products to other businesses.

## What Northvaine does

Every night, for each client, Northvaine builds **opportunities**: a company, the dated reasons to talk
to it now, the kind of play, and the next action.

| Label | What it means | Example |
|---|---|---|
| **Connected** | Several independent signals agree on one company | New owner in May + first import in June + its own site sells the product |
| **Approach now** | A project of the kind that needs the product, with a named company | A contractor wins a contract that names the product |
| **Build a relationship** | A fitting distributor or dealer that is changing | A stone and tile distributor opens a new showroom |
| **Looking for it** | Proof it already buys the product, plus a fresh sign | It started importing the client's product codes this year |
| **Watch list** | Right fit, nothing new yet | Woken up automatically when a new signal appears |

Each lead shows **Intent** (how strong and fresh the signal is), **Fit** (how well it matches what the
client sells) and **Confidence** (how many independent kinds of source agree), the **source chain**
behind it (each fact with its date and a link to where it came from), the **evidence against**, and
**one line to open with**. The Station shows the best five each day; the rest are one click away.

## How it works

```
client's answers (offer, products, buyers, markets, the projects that create need)
   │
   ├─ sensors: UK import records (HMRC) · UK Find a Tender · EU tenders (TED) · US contracts
   │           (USAspending) · intent web searches per market (Tavily) · company register
   │           (Companies House) · company websites (free fetch, robots.txt respected)
   ▼
evidence ledger ── every fact is a claim whose quote CODE finds in the stored source text
   ▼
off-target filter (code) ── other markets, contracts and news that never relate to the product
   ▼
buyer gate (Nemotron Super) ── buyer / competitor / reseller / publisher / not a buyer
   ▼
skeptic (Nemotron Super) ── cited evidence against every lead
   ▼
company fit (Nemotron Super + Tavily) ── does its own site show it deals in the product, and what
                                          is it: maker, reseller or user? quote-checked
   ▼
opportunity ranking (code) ── play, intent, fit, confidence, labels
   ▼
senior review (Nemotron Ultra) ── "would this business call them today?" with cited facts;
                                   a "no" is held back to the watch list with its reason
   ▼
five leads a day, each with its source chain, why now and an opening line
```

Nothing is written for one industry: every search phrase and rule comes from the client's own data,
and a check in the build fails if an industry word appears in the code. Northvaine never sends
anything and never quotes prices: a person decides and makes contact.

## Where NVIDIA Nemotron, Nebius Token Factory and Tavily are used

| What | Model / service | Where in the code |
|---|---|---|
| Senior review of the top leads (serious reasoning) | **Nemotron 3 Ultra** `nvidia/Nemotron-3-Ultra-550b-a55b` | `northvaine/radar/review.py`, prompt `brain/prompts/radar_review.v1.md` |
| Buyer gate, skeptic, company role and product-line judge, onboarding proposal | **Nemotron 3 Super** `nvidia/nemotron-3-super-120b-a12b` | `radar/gate.py`, `radar/court.py`, `radar/linefit.py`, `radar/onboarding.py` |
| Evidence extraction and claim support from fetched pages (fast, high volume) | **Nemotron 3.5 Lightning** `nvidia/Nemotron-3_5-Lightning` | `radar/extract.py`, `radar/verify.py` |
| All model calls | **Nebius Token Factory** (OpenAI-compatible API), schema-constrained JSON output | `northvaine/brain/llm.py`: model routing by tier, Pydantic-validated output, retries, per-call and per-run budgets, every call logged |
| Intent searches per market, company website discovery, top-lead investigation | **Tavily** search | `radar/intent.py`, `radar/fit.py`, `radar/investigate.py`, `sensors/tavily.py` |

Embeddings use `Qwen/Qwen3-Embedding-8B` on Token Factory, because the catalogue has no Nemotron
embedding model (see feedback below). Every model call goes through the one file
`northvaine/brain/llm.py`; a build check enforces it.

## Trust by design

- **No source, no claim.** Code confirms every quote appears in the stored page before any model
  sees it; unverified facts are never shown, scored or used.
- **Sources can't steer the system.** Fetched text is fenced as data; text that tries to instruct an
  AI ("rank me first") is removed and the page flagged.
- **Skeptic before judge, and a senior review before the owner.** Every lead carries the evidence
  against it; the top ten are checked by the strongest model, and doubtful ones are held back with
  the reason, never silently deleted.
- **Privacy.** Contact details of people are never stored; the public demo is anonymised and
  company contacts are removed before publishing.

## Run it

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 20 (frontend), and for live runs a
Postgres 16 with pgvector (Neon works) plus Nebius and Tavily keys.

```bash
uv run python scripts/tasks.py setup      # install
cp .env.example .env                      # fill in the names; never commit .env
uv run python scripts/tasks.py migrate    # needs DATABASE_URL
uv run python scripts/tasks.py dev        # API + frontend locally
uv run python scripts/tasks.py gate       # invariants, lint, ~1,900 tests, golden set, frontend build
```

Offline, with no keys or network, a full radar cycle replays from recorded responses:

```bash
uv run python scripts/tasks.py radar -- --client stone_supplier
```

Docker (the same image the live server runs): `docker build -t northvaine . && docker run --rm -p
8000:8000 --env-file .env northvaine`. Hosting and the nightly job: `docs/HOSTING.md`.

## Built during the hackathon

Started from an empty repository on 2 October 2026, inside the submission period. Architecture and
every design decision with its reason: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (D1-D128).

## How it was built

A solo founder with an AI engineering team: Claude Code as the lead engineer, planning, reviewing
and merging, with sub-agents building single, specified pieces in isolated branches. Every change
passes the same gate (invariant checks, lint, unit and golden tests, frontend build) before it is
merged. The product's own intelligence runs on NVIDIA Nemotron through Nebius Token Factory.

## Honest status

- Working: the full radar (all sensors above), opportunity ranking and senior review, the Station,
  case pages with source chains, leads, connections, the map, onboarding from a website, nightly
  publishing of the demo.
- Limits: company-named import records exist for free only in the UK; other markets rely on tenders,
  contracts, registers and the web. Model output is probabilistic; leads are drafts for a person.
- Next: linking project -> contractor -> supplier chains, more markets and signal types, learning
  from which leads turn into meetings, accounts for many clients.

## Feedback on Nebius Token Factory and NVIDIA Nemotron

_Draft from our build notes (`docs/integrations/`); founder to review and add._

- **Model tiers work as the track suggests.** Lightning for high-volume extraction, Super for the
  buyer gate and skeptic, Ultra only for the final review keeps a full run (about 300 model calls
  across eight markets) at about a quarter of a dollar, in about 25 minutes.
- **Structured output is the feature we relied on most, and it is under-documented.** Token Factory
  accepts `response_format: json_schema`, but no page lists which JSON Schema keywords are honoured.
  We probed it live: `$defs`/`$ref`, `enum`, `maxItems` and `additionalProperties: false` were
  enforced even against prompt pressure; `minItems`, `pattern`, `format`, `oneOf` were never
  confirmed. A per-model "structured output: yes / which keywords" table would save every team a day.
- **No Nemotron embedding model in the Token Factory catalogue.** We had to use Qwen3-Embedding-8B for
  embeddings next to Nemotron for generation. A Nemotron embedder on Token Factory would let a whole
  app stay on NVIDIA models.
- **Model ids are inconsistent in casing and format** (`Nemotron-3_5-Lightning` with an underscore,
  `nemotron-3-super-120b-a12b` lower case, `NVIDIA-Nemotron-3-Nano-30B-A3B` upper case). They must be
  copied verbatim; one consistent scheme, or case-insensitive matching, would prevent silent errors.
- **Reasoning control for Ultra is not documented on Token Factory** (whether
  `chat_template_kwargs.enable_thinking` or `reasoning_effort` applies). We had to find out by testing.
- **Error bodies and rate limits are not documented**, so we treat every 5xx as retryable with
  backoff. Published per-model rate limits would let apps size their concurrency safely.
- **Usage visibility:** a per-key, per-model usage and cost view (or an API for it) would help apps
  enforce budgets; we log every call ourselves for that reason.

## Licence

MIT, see `LICENSE`.
