# Milestone 2 plan: `brain/llm.py`, the single auditable door to every model call

status: **approved** (founder, 3 Oct 2026 - all four questions answered yes)
pre-flight: **P1/P2/P3 run and recorded 3 Oct 2026**; decisions D1-D14 written to docs/DECISIONS.md
date: 2026-10-03
baseline: `main` after the M1 sign-off (T1.0-T1.8 merged, head 0002 on the production Neon branch).
research: `docs/integrations/nebius-token-factory-api-surface-and-client.md`,
`docs/integrations/nvidia-nemotron-model-ids-limits-and-prices-on-token-factory.md`,
`docs/integrations/nemotron-embeddings-and-the-vector-dimension.md`,
`docs/integrations/pgvector.md`.

## Goal

Land `northvaine/brain/llm.py` as the single, auditable door to every model call:

- a Nebius Token Factory client (OpenAI-compatible, `openai` SDK, confirmed base URL);
- fast / mid / deep / embed tier routing to configured model ids;
- Pydantic-validated JSON output with repair retries and backoff;
- a **four-level money guard** - per-call, per-run, per-day, and lifetime `TOTAL_BUDGET_USD` -
  that hard-stops and never silently degrades;
- an `llm_calls` row for **every attempt**, successes and failures alike;
- a prompt loader with `<name>.v<N>.md` versioning;
- untrusted-text fencing **by construction** (CLAUDE.md #7 becomes a type error);
- migration 0003 fixing the embedding dimension and adding the vector indexes;
- one live smoke script that is also the fixture recorder, plus offline replay tests.

## Pre-flight: one orchestrator probe, before wave 0

Three facts the research could not settle are **hard prerequisites of the build**, not steps
inside it. The orchestrator runs one short live session with the founder's key and records the
results (with today's date and the raw responses) into
`docs/integrations/nebius-token-factory-api-surface-and-client.md`:

| # | Probe | Cost | Settles |
|---|---|---|---|
| P1 | `GET /v1/models?verbose=true` | free | the real `MODEL_FAST/MID/DEEP/EMBED` ids, per-model max output tokens, per-model prices and rate-limit metadata. **Prerequisite of T2.0** - `pricing.json` must be keyed by ids that were observed, not read off a marketing page. |
| P2 | one tiny `response_format={"type":"json_schema", ...}` call on the cheapest model | sub-cent | whether the schema nests under `json_schema.schema` or directly under `json_schema`, and whether `strict` is honoured. The research doc flags this explicitly as unconfirmed. **Prerequisite of T2.4**; without it T2.4's central request shape is a guess. |
| P3 | one `POST /v1/embeddings` call with `dimensions=<chosen N>` on a three-word input | sub-cent | the **actual returned vector length**. **Prerequisite of T2.1a** - M1 deliberately left the vector columns dimensionless so this would be measured, not guessed. |

The raw P2 and P3 responses (redacted) are handed to T2.5a as its starting fixture shapes, so the
replay tests are never written against hand-crafted JSON.

The orchestrator also writes **all ten decisions below to `docs/DECISIONS.md` before wave 1
starts.** No ticket writes that file; naming the owner here is what keeps it from falling through
(FACTORY §2 rule 9).

## The embedding model and the dimension (changed from the draft)

The research is unambiguous and the plan now follows it rather than the old CLAUDE.md comment:

- Token Factory's live catalog lists **exactly one** embedding model, `Qwen/Qwen3-Embedding-8B`
  ($0.01 / 1M input, eu-north1). The Nemotron page lists only text-generation models. There is
  **no Nemotron embedder to configure**. The hackathon's Nemotron requirement is satisfied by the
  fast / mid / deep generation tiers, not by the embedder. This needs a founder decision.
- Its **native dimension is 4096**. pgvector's index limits are 2,000 for `vector` and **4,000 for
  `halfvec`** (`docs/integrations/pgvector.md` fact 8), so 4096 **cannot be indexed at all** -
  not as `vector`, not as `halfvec`. The draft's halfvec fallback was unachievable.
- The endpoint documents a `dimensions` parameter (Matryoshka, 32-4096). So the **primary path** is
  to request `N <= 2000`, store `vector(N)` and index it with plain HNSW `vector_cosine_ops`.
  The model normalizes its embeddings, so cosine is the right operator class.

Decision ladder baked into T2.1a:

| Confirmed N | Column | Index | Verdict |
|---|---|---|---|
| N <= 2000 | `vector(N)` | HNSW `vector_cosine_ops` | **primary path** |
| 2000 < N <= 4000 | `vector(N)` | `halfvec(N)` expression index, `halfvec_cosine_ops` | fallback |
| N > 4000 | - | - | **not acceptable**; truncate via `dimensions` and re-probe |

**EMBED_DIM = 1024 - confirmed live by P3** (comfortably under the index limit, a standard Matryoshka
truncation point, a quarter of the storage of 4096). P3 returned exactly 1024 floats, L2-normalized to 1.0. Primary path holds: `vector(1024)` + HNSW `vector_cosine_ops`.

## Waves

| Wave | Tickets | Why here |
|---|---|---|
| - | **pre-flight probe P1/P2/P3** (orchestrator) + DECISIONS.md entries | gates the build |
| 0 | T2.0 contracts | everything depends on the frozen shapes |
| 1 | T2.1a migration 0003 · T2.2 prompts + fencing | disjoint writes; both need only T2.0 |
| 2 | T2.1b M1 carry-overs · T2.3 budget guard | T2.1b follows 0003 so the parser sees the real HNSW DDL |
| 3 | T2.4 `brain/llm.py` | needs prompts, fencing and the budget guard |
| 4 | T2.5a smoke script + redaction helper | needs the whole stack |
| - | **orchestrator runs the smoke script, commits `tests/fixtures/llm/*.json`** | only the orchestrator has `.env` |
| 5 | T2.5b replay tests against the real recorded fixtures | needs the fixtures to exist |

Eight tickets instead of six: the critique split T2.1 (four unrelated concerns, seven files, well
over the ~400-line guidance) and T2.5 (a chicken-and-egg where the test engineer was asked to
commit fixtures it could not record). Both splits have disjoint write sets.

### Why the T2.5 split matters

Builder worktrees have no `.env` - the M1 lesson, and deliberate. A test engineer asked to commit
`tests/fixtures/llm/*.json` **and** a replay test that runs in the default gate would have to
hand-craft the fixtures from the research doc. The orchestrator's later real run would then produce
different shapes and break the gate on `main` after the ticket was marked done. So: T2.5a ships the
recorder and the redaction helper with **no committed fixtures and no replay test**; the
orchestrator records; T2.5b writes the replay tests against what was actually returned.

## Frozen contracts (wave 0, T2.0)

```
ModelTier        = fast | mid | deep | embed
BudgetKind       = call | run | day | total
LlmUsage         (input_tokens, output_tokens, total_tokens)
ModelPrice       (model, usd_per_million_input, usd_per_million_output, context_length,
                  checked_on: date, source_url)
LlmResult[T]     Generic[T]: value: T, usage: LlmUsage, cost_usd: Decimal, model: str
LlmCallRow       mirrors llm_calls incl. the four columns 0003 adds

brain/errors.py  LlmError
                 |- LlmTimeout, LlmTransportError, LlmInvalidOutput
                 |- PricingUnknown
                 |- BudgetExceeded(kind, cap, spent, would_spend)
                 (ConfigError is imported from core/settings.py, never redefined)

brain/llm.py     complete_json, complete_text, embed, list_models, estimate_cost
brain/budget.py  RunContext, check_budget, record_call
brain/fencing.py Untrusted, fence
brain/prompts/   load_prompt, Prompt.render, Prompt.version_label
core/standards.py  EMBED_DIM_EXPECTED  <- the single source of the dimension
```

New settings: `total_budget_usd` and `daily_budget_usd` (both `Decimal | None`, **no default**),
`run_budget_usd` and `max_call_cost_usd` (conservative defaults), `llm_timeout_seconds`,
`llm_max_retries`.

## Decisions proposed

1. Add `TOTAL_BUDGET_USD`, a lifetime cap summed from `llm_calls.cost_usd` across all rows, checked
   before every call alongside the per-call, per-run and per-day caps. Neither `DAILY_BUDGET_USD`
   nor `TOTAL_BUDGET_USD` has a default: calls raise `ConfigError` naming the variable until the
   founder sets both. `RUN_BUDGET_USD` and `MAX_CALL_COST_USD` do get conservative defaults, since
   a run cap with no default would block every run.
2. A cap that would be exceeded raises `BudgetExceeded` and stops. The system never silently
   degrades: no model downgrade, no truncated prompt, no partial result.
3. The daily cap is a per-workspace UTC-day bucket (`workspace_id` NULL is its own bucket, which is
   what onboarding and smoke calls use); the lifetime cap is global across every row, because it
   protects one wallet.
4. Every attempt writes an `llm_calls` row - successes, transport failures, timeouts and
   invalid-JSON retries alike. Retries are paid for, so they must be visible. A call that fails with
   no usage reported records `cost_usd = 0` and `ok = false`, never an estimate.
5. `llm_calls` gains `run_id`, `prompt_version`, `latency_ms` and `error`, plus indexes on
   `created_at` and `(workspace_id, created_at)` so the budget sums stay cheap as the table grows.
6. **`MODEL_EMBED = Qwen/Qwen3-Embedding-8B`.** Token Factory serves no Nemotron embedding model.
   The hackathon's Nemotron requirement is met by the fast/mid/deep generation tiers. CLAUDE.md's
   `# Nemotron Embed id` comment and the `.env.example` line are corrected accordingly.
7. **`EMBED_DIM` is set by the `dimensions` parameter to a value <= 2000 (proposed 1024)**, so the
   column stays `vector(N)` with a plain HNSW `vector_cosine_ops` index. `halfvec` is a fallback
   only for 2000 < N <= 4000; N > 4000 is not acceptable. The chosen N lives in exactly one place,
   `core/standards.EMBED_DIM_EXPECTED`, and an offline test proves schema.sql, migration 0003 and
   that constant agree.
8. Prompts are files named `<name>.v<N>.md` with front matter; `load_prompt(name)` takes the highest
   version and `llm_calls.prompt_version` stores `"<name>.v<N>"`, so a prompt change is attributable
   later (SPEC §12). M2 ships the loader and exactly one tiny generic prompt.
9. External text is fenced by construction: a prompt declares which variables are untrusted,
   `render()` refuses anything but an `Untrusted` value for them, and it passes every such value
   through `fence()` before interpolation. CLAUDE.md #7 becomes a type error, not a reviewer's
   memory.
10. The live smoke script is the only code path in the repository that spends money, and it doubles
    as the fixture recorder: one sub-cent run buys the recorded responses every later milestone
    replays offline. It imports no HTTP or LLM SDK itself - it calls `brain/llm.py`, including the
    free `list_models()`. Model call concurrency stays at one for M2: check-then-call is not atomic,
    and under a $1 lifetime cap correctness of the guard beats throughput.

## Risks

- **The embedding dimension is the one fact 0003 bakes into the database.** If the documented
  dimension differs from what the endpoint returns, 0003 is wrong and must be re-migrated.
  Mitigation: probe P3 before wave 1; the doc records the confirmation; `embed()` and the smoke
  script both assert the live length forever after; one constant, one offline agreement test.
- **No Nemotron embedder exists on Token Factory.** Until the founder decides, `MODEL_EMBED` has no
  valid value and T2.1a has no dimension. This is a decision, not a build task - it blocks wave 1.
- **The `json_schema` nesting shape is unconfirmed** and the research doc says the Nebius example
  differs from OpenAI's usual convention. Probe P2 settles it before T2.4. Without P2, the fallback
  (JSON mode + Pydantic validation + one repair retry) costs extra tokens on every malformed reply,
  which matters under a $1 lifetime cap.
- **Model ids are unconfirmed against the API.** Only catalog/marketing ids were found. If the
  configured ids miss `pricing.json`, `price_for()` raises `PricingUnknown` and every call fails -
  including the smoke run that is supposed to buy the fixtures. Mitigation: P1 keys `pricing.json`
  by observed ids, and `validate_configured_models()` reports all missing ids in one `ConfigError`
  before anything is spent.
- **The $1 lifetime cap means that once the smoke run is spent, every further live call is refused**
  until Nebius promo credits arrive. Milestones 3 to 5 need live calls to produce real briefs. If
  credits do not arrive, M5's first-radar run is blocked on money, not code. Watch this now, not in
  week two.
- **Prices in `pricing.json` are a snapshot.** If Nebius changes pricing, every recorded `cost_usd`
  is wrong and both caps drift. Mitigation: `checked_on` and `source_url` in the file, a test that
  every configured model id has an entry, and `PricingUnknown` rather than a zero-cost fallback.
- **Migration 0003 must be applied to the already-migrated production Neon database**, and the smoke
  run needs it (it writes the four new columns and relies on the new indexes). As with 0002 this
  needs the founder's explicit go-ahead; until then production and the schema diverge and the smoke
  run cannot proceed.
- **`db-test` session reuse trades isolation for speed** and can reintroduce cross-test leakage.
  T2.1b must show the suite still passes in a random order, not just faster.
- **Six waves is more serialization than M1 had.** The pre-flight probe is therefore a gate on
  starting the build rather than a step inside it: if P1/P2/P3 are unanswered when wave 0 starts,
  the whole chain stalls.
- **The lifetime cap is summed per-database.** Spend against `TEST_DATABASE_URL` and spend against
  the production database are two independent "lifetimes" of the same single dollar, and the
  pre-flight probe's spend (raw curl, no `llm_calls` row) is invisible to both. Documented in the
  budget module docstring; the smoke script prints which database it summed from.

## Questions for the founder

1. **Money, and therefore yours to set.** We propose `DAILY_BUDGET_USD=1.00` and
   `TOTAL_BUDGET_USD=1.00` in your `.env` - the same single dollar, so the daily cap can never
   outspend the lifetime one. Confirm the two values and set them yourself; the code refuses to make
   any call until both exist.
2. **Token Factory serves no Nemotron embedding model.** Its catalog lists exactly one embedder,
   `Qwen/Qwen3-Embedding-8B` ($0.01 / 1M input). Approve it as `MODEL_EMBED`? The hackathon's
   Nemotron requirement is still met by the fast/mid/deep generation tiers. And approve
   `EMBED_DIM = 1024` via the endpoint's `dimensions` parameter, so the vector column can carry an
   HNSW index at all (4096 cannot be indexed by pgvector).
3. **Approve the pre-flight probe:** one free `GET /v1/models?verbose=true`, one tiny JSON-schema
   completion and one embedding call, well under $0.01 total. It settles the model ids, the
   structured-output request shape and the real vector dimension - all three are facts the build
   would otherwise guess.
4. **Approve running migration 0003 against the production Neon database** once T2.1a lands, as you
   did for 0002. This is a **precondition of the approved smoke run**, not a later tidy-up: the
   smoke script writes `run_id`, `prompt_version`, `latency_ms` and `error`, and refuses to start
   unless the connected database reports head 0003.
5. **Approve one live smoke run** against Token Factory: the free model listing, two or three tiny
   calls on the cheapest Nemotron model (Lightning, $0.06 / $0.24 per 1M) and one embedding call -
   estimated well under $0.01, printed before it spends and aborted if the estimate exceeds a cent.
   It is what records the fixtures every later milestone replays for free.

## Parked (for `docs/LATER.md`)

- The four T1.2 SSL nits (verify-ca without sslrootcert, CA docs for require/prefer, root.crt
  fallback docs, scrubbing the decoded password from error text). No M2 ticket touches
  `core/db.py`, and opening it for documentation nits adds risk to the one file every other ticket
  depends on. The password scrub is the one with real security value - fold it into M3, which
  touches config and fetching anyway.
- A lint or type check that catches `await` inside a sync comprehension (M1 carry-over 5). The
  candidate is mypy over `tests/db`: a new dev dependency, new config and a new gate step whose
  runtime grows with the codebase. Revisit when the gate is next touched.
- Concurrency-safe budget reservations (a reserved-spend row or an advisory lock) so several calls
  can run in parallel without racing past a cap. M2 runs calls serially instead.
- A single cross-database view of lifetime spend (test and production are separate ledgers today).
- Local token counting (tiktoken or equivalent) for tighter pre-call estimates. M2 uses a
  character-based upper bound plus `max_output_tokens`, which over-estimates and therefore fails
  safe.
- Streaming responses, prompt caching and batch endpoints - cost and latency optimizations with no
  demo value under a $1 cap.
- Disagreement-sampled tier routing (ARCHITECTURE §3.2). M2 ships static fast/mid/deep routing;
  adapting the routing belongs with the learners.
- A golden set for prompts (SPEC §12). M2 ships one tiny prompt; the golden set arrives with the
  gate and judge prompts in M4/M5.
- Distilling perception into the fast tier from accumulated verified claims (ARCHITECTURE §20,
  "no fine-tuning now").
