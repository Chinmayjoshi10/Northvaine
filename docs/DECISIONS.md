# Decisions

Record any change to the spec: date, decision, reason.

## 2026-10-02 — Adopt ARCHITECTURE.md v2 as the design
- **Decision:** `docs/ARCHITECTURE.md` (v2) is the accepted candidate architecture. It defines
  four learners (world state, org context, buying patterns, research policy) plus an attention
  allocator. Where it conflicts with SPEC.md, ARCHITECTURE wins. The main changes to SPEC:
  - theses are split into patterns + playbooks,
  - the backtest uses matched controls,
  - event types are an open hierarchy,
  - fixed weights and windows become learned beliefs,
  - net-new reach is the headline metric.
- **Reason:** SPEC's learning loop could only re-rank a fixed search. The product must find
  activity the business would have missed and learn where to look (founder, 2 Oct).

## 2026-10-02 — Build with a subagent software factory
- **Decision:** work runs through `docs/FACTORY.md`:
  - architect / researcher / builder / test-engineer / reviewer / integrator roles in
    `.claude/agents/`,
  - tickets in `factory/board/`,
  - the `factory-plan` and `factory-build` workflows in `.claude/workflows/`,
  - `scripts/gate.py` + `scripts/check_invariants.py` as the mechanical gate.
- **Reason:** parallel building by several agents without conflicts needs frozen contracts,
  disjoint write scopes, worktree isolation and one gate.

## 2026-10-02 — Repository layout
- **Decision:** the repo root is `D:\hack`. Docs live in `docs/`, as CLAUDE.md expects. The
  original handoff copies in `files (2)/` and the zip are kept out of git.
- **Reason:** match the layout in CLAUDE.md.

## 2026-10-02 — Milestone 1 plan approved (orchestrator, under the founder's delegation)
- Python 3.12 via uv; setuptools.build_meta backend; unused later-milestone deps removed
  (each milestone re-adds what it needs).
- ARCHITECTURE §21 interpretations in `factory/board/M1/PLAN.md` (Decisions 7) are accepted:
  - `theses.alpha/beta` dropped,
  - jobs gets leases/heartbeat/attempt fields,
  - 13-stage CHECKs on `cases`/`outcomes`,
  - lessons require a strategy version,
  - one open case per company + pattern (a second inbound request joins it).
- Vector columns are dimensionless in M1; the dimension and the indexes are fixed in M2 once
  the embedding model is confirmed.
- Licence: MIT (LICENSE file in M15).
- `DAILY_BUDGET_USD` has no default: LLM calls refuse to run until the founder sets it.
- db-test may create/drop `nv_test_<hex>` databases on the TEST_DATABASE_URL server only. If
  the role can't, it uses `reuse` mode on a dedicated test branch. It never touches the demo DB.
- **Pending, founder:** Postgres hosting (Neon free for dev/test recommended now; Nebius
  Managed PostgreSQL ~ $100/month is a paid decision for the demo, to decide by M14).

## 2026-10-02 — Database: Neon free tier for development, tests and the demo
- **Decision:**
  - Neon project `divine-resonance-54542003`, linked with the `neon` CLI (`neon.ts`, empty policy).
  - Branch `production` → `DATABASE_URL`; branch `test` → `TEST_DATABASE_URL`.
  - Both are Postgres 18.6 with pgvector 0.8.6; the role can create databases, so db-test uses
    `database` isolation.
  - URLs live only in the git-ignored `.env` / `.env.local`.
  - Nebius Managed PostgreSQL is not used.
- **Reason:** the founder wants no spending now, and Neon free covers dev, tests and a hackathon
  demo with no local install.

## 2026-10-03 — Product scope: B2B radar now, one engine for many lenses
- **Decision:**
  - The hackathon product is the B2B radar, for any client (not tied to the founder's company).
  - The engine stays general ("one engine, many lenses", ARCHITECTURE §0.2); company watch /
    market intelligence is the first lens after the hackathon.
  - New milestone 5 "First radar (multi-client)" tests core quality on 2–3 diverse sample
    clients before the learners; later milestones shift by one.
  - Milestone 3 adds official registries and tender sources, chosen after research.
- **Reason:**
  - Prove the core promise (good, sourced buyers for any client) in week 1 rather than week 3.
  - Generality across clients is the strongest proof of "nothing hard-coded".

## 2026-10-03 — Project graph in milestone 6; Apollo/Clay after the product is finished
- **Decision:**
  - Add `projects` + `relationships` (company ↔ project/company with role, dates and a source
    claim) in milestone 6.
  - Contact enrichment (Apollo, Clay) waits until after the hackathon, once the product is
    finished.
- **Reason:**
  - The manual first-radar run showed that the buyer is usually found by following a chain
    (council → project → contractor). Events tied to one company can't represent that.
  - Contact data adds personal-data obligations and cost, and nothing for the demo.

## 2026-10-03 — LLM budget: $1/day until hackathon credits arrive
- **Decision:** `DAILY_BUDGET_USD=1`. `llm.py` hard-stops at the cap. Live LLM use in tests and
  smoke checks is kept minimal; recorded fixtures are replayed instead. Raise the cap when
  Nebius credits arrive.
- **Reason:** the founder has no Token Factory credits yet and doesn't want to spend now.
- **Correction (same day):** the $1 is the **total** available until the promo credits arrive,
  not $1 per day. Milestone 2 must add `TOTAL_BUDGET_USD` (a lifetime cap summed from
  `llm_calls.cost_usd`), checked before every call alongside the daily cap. Until credits
  arrive:
  - only free calls (e.g. listing models) and a handful of tiny smoke calls on the smallest
    model;
  - everything else uses recorded fixtures.

## 2026-10-03 — Milestone 2 approved: `brain/llm.py` as the single auditable door to every model call
Founder approved `factory/board/M2/PLAN.md` and its four open questions on 3 Oct: run the
pre-flight probe, adopt `Qwen/Qwen3-Embedding-8B` at 1024 dimensions, apply migration 0003 to the
production Neon database once T2.1a lands, and run one live smoke run. The ten plan decisions are
recorded here so no ticket owns `docs/DECISIONS.md` (FACTORY §2 rule 9).

- **D1 — Four money caps, no defaults on the two that matter.** `TOTAL_BUDGET_USD` (lifetime, summed
  from `llm_calls.cost_usd` across all rows) joins `DAILY_BUDGET_USD`, `RUN_BUDGET_USD` and
  `MAX_CALL_COST_USD`. All four are checked before every call. Neither `DAILY_BUDGET_USD` nor
  `TOTAL_BUDGET_USD` has a default — calls raise `ConfigError` naming the variable until the founder
  sets both. `RUN_BUDGET_USD` and `MAX_CALL_COST_USD` do get conservative defaults, since a run cap
  with no default would block every run.
  **Reason:** the single dollar is real money and a forgotten variable must fail loudly, not
  silently default to something generous.
- **D2 — A cap that would be exceeded raises `BudgetExceeded` and stops.** No model downgrade, no
  truncated prompt, no partial result.
  **Reason:** silent degradation produces results that look fine and are not; under a $1 cap the
  failure must be visible.
- **D3 — Daily cap is a per-workspace UTC-day bucket** (`workspace_id IS NULL` is its own bucket,
  used by onboarding and smoke calls); the **lifetime cap is global across every row**.
  **Reason:** the daily cap protects a client's share, the lifetime cap protects one wallet.
- **D4 — Every attempt writes an `llm_calls` row** — successes, transport failures, timeouts and
  invalid-JSON retries alike. A failure with no reported usage records `cost_usd = 0` and
  `ok = false`, never an estimate.
  **Reason:** retries are paid for, so they must be visible in the ledger.
- **D5 — `llm_calls` gains `run_id`, `prompt_version`, `latency_ms` and `error`,** plus indexes on
  `created_at` and `(workspace_id, created_at)`.
  **Reason:** the budget sums run before every call and must stay cheap as the table grows.
- **D6 — `MODEL_EMBED = Qwen/Qwen3-Embedding-8B`.** Token Factory serves **no Nemotron embedding
  model** — its catalog has exactly one embedder (confirmed live, P1 below). The hackathon's
  Nemotron requirement is met by the fast/mid/deep generation tiers. CLAUDE.md's `# Nemotron Embed
  id` comment and the `.env.example` line are corrected accordingly (T2.0).
- **D7 — `EMBED_DIM = 1024`,** requested via the endpoint's `dimensions` parameter, stored as
  `vector(1024)` with a plain HNSW `vector_cosine_ops` index. The value lives in exactly one place,
  `core/standards.EMBED_DIM_EXPECTED`, and an offline test proves schema.sql, migration 0003 and
  that constant agree.
  **Reason:** the model's native 4096 **cannot be indexed by pgvector at all** (limit 2,000 for
  `vector`, 4,000 for `halfvec`). `dimensions` is not an optimization here — it is what makes
  indexed vector search possible. `halfvec` remains a fallback only for 2000 < N <= 4000.
- **D8 — Prompts are files named `<name>.v<N>.md` with front matter.** `load_prompt(name)` takes the
  highest version; `llm_calls.prompt_version` stores `"<name>.v<N>"`.
  **Reason:** a prompt change must be attributable to the results it produced (SPEC §12).
- **D9 — External text is fenced by construction.** A prompt declares which variables are untrusted;
  `render()` refuses anything but an `Untrusted` value for them and passes each through `fence()`
  before interpolation.
  **Reason:** CLAUDE.md #7 becomes a type error instead of a reviewer's memory.
- **D10 — The live smoke script is the only code path in the repository that spends money,** and it
  doubles as the fixture recorder. It imports no HTTP or LLM SDK itself — it calls `brain/llm.py`.
  Model call concurrency stays at one for M2.
  **Reason:** one sub-cent run buys the recorded responses every later milestone replays offline;
  check-then-call is not atomic, and under a $1 cap guard correctness beats throughput.

## 2026-10-03 — Pre-flight probe results: model ids, reasoning, and the vector dimension
Three live calls against Token Factory (approved; under $0.0001 total). Full raw detail in
`docs/integrations/nebius-token-factory-api-surface-and-client.md`.

- **D11 — The configured model ids are these exact strings,** copied from the live catalog:
  `MODEL_FAST=nvidia/Nemotron-3_5-Lightning` ($0.06/$0.24 per 1M, 1M ctx, EU),
  `MODEL_MID=nvidia/nemotron-3-super-120b-a12b` ($0.30/$0.90, 262k ctx, **US**),
  `MODEL_DEEP=nvidia/Nemotron-3-Ultra-550b-a55b` ($1.00/$3.00, 1M ctx, **US**),
  `MODEL_EMBED=Qwen/Qwen3-Embedding-8B` ($0.01/1M, EU).
  **Reason:** the catalog ids follow no single convention (an underscore decimal point in one, a
  repeated vendor prefix in another, lowercase in a third). They cannot be guessed, and a miss means
  `PricingUnknown` on every call. Also recorded: prices are returned **per token**, not per million;
  the API exposes **no `max_output_tokens`**, so the budget guard's output bound must come from our
  own `max_tokens`; per-model rate limits differ sharply (Nano is 100 RPM); and the mid and deep
  tiers are **US-region**, which matters for client content.
- **D12 — `brain/llm.py` sends `reasoning_effort: "none"` by default on every structured call.**
  Measured: without it, Lightning spent all 60 allowed tokens thinking in plain prose *into
  `message.content`*, returned `finish_reason: "length"`, and **the JSON schema did not constrain
  the output at all**. With it: `finish_reason: "stop"`, exact schema-valid JSON, 14 completion
  tokens.
  **Reason:** this is the single largest avoidable cost and failure mode under a $1 cap. Raising
  reasoning effort is a deliberate per-call choice, never a default.
- **D13 — The structured-output request nests the schema under `json_schema.schema`** (the standard
  OpenAI convention), with `strict: true` beside `name`. Confirmed accepted and enforced.
  **Reason:** the research doc flagged the Nebius example as suggesting a flat shape; it is not.
  This was a prerequisite of T2.4's central request shape.
- **D14 — `EMBED_DIM = 1024` is confirmed live, not assumed.** `dimensions: 1024` returns exactly
  1024 floats; omitting it returns 4096. **Both are L2-normalized to 1.0**, so truncated vectors are
  re-normalized server-side and `vector_cosine_ops` is correct.
  **Reason:** the dimension is the one fact migration 0003 bakes into the database, and M1
  deliberately left the vector columns dimensionless so it would be measured rather than guessed.

## 2026-10-03 — Every `llm_calls` row records which provider served it

- **D15 — Migration 0003 adds `provider` (text, NOT NULL, default `'nebius'`) to `llm_calls`, and
  `LlmCallRow` carries it.** `brain/llm.py` sets it from configuration, never from a caller.
  **Reason:** every other part of a provider swap is reversible — `base_url`, the API key and the
  four `MODEL_*` ids are configuration, and call sites name a tier (`fast`/`mid`/`deep`), never a
  model id. Provenance on rows *already written* is the one thing that cannot be reconstructed
  afterwards. If development traffic ever runs through a second provider (NVIDIA NIM's free
  credits are the live candidate) while the demo path stays on Token Factory, a ledger without
  this column can never afterwards distinguish real spend from free spend, and the `TOTAL_BUDGET_USD`
  sum becomes unauditable. 0003 is already open in T2.0 and already adding four columns, so the
  cost today is one line; after wave 0 it is a fifth migration.
  **Not decided here:** whether to actually use NIM. This only preserves the ability to answer the
  question later. The hackathon requires runtime calls to Nebius Token Factory with Nemotron
  models, so the demo path stays on Token Factory regardless.

## 2026-10-03 — Nebius budget raised to $29; the M5 money blocker is gone

- **D16 — The lifetime LLM budget is raised from $1 to $29** (founder, 3 Oct 2026).
  `TOTAL_BUDGET_USD` and `DAILY_BUDGET_USD` are set by the founder in `.env`; no code default
  changes, because both still have **no default** and calls refuse to run until they are set (D1).
  **Reason:** the $1 cap was sized when the account had no credits, and it made every milestone
  after M2 blocked on money rather than on code. The M2 plan's standing risk - "once the smoke run
  is spent, every further live call is refused... M5's first-radar run is blocked on money, not
  code" - no longer applies. M5's first radar needs roughly 2-3 clients x ~10 candidates of
  discovery, extraction and verification calls, which is a few dollars on the fast tier, not a few
  cents.
  **Unchanged by this:** the four-level guard (call / run / day / total) still hard-stops and never
  silently degrades (D2); every attempt still writes an `llm_calls` row (D4); `provider` still
  records which API served each call (D15). A larger cap makes the ledger more important, not less.
  **Still worth having:** the free NVIDIA NIM credits remain useful for development iteration, but
  they are now a convenience rather than the thing standing between the project and a demo.

## 2026-10-03 — "Did you already know?" is a scale, and deal size sets the bar

- **D17 — The reach label has three states, not two.** The one-tap question on every case
  (ARCHITECTURE §0.1) becomes: *never heard of them* / **knew the company, not the moment** /
  *already working on it*.
  **Reason (founder, 3 Oct):** knowing is continuous, not binary. The middle state is both the
  most common outcome and the one the radar is best at - it is pure timing value. A yes/no tap
  collapses it into "already knew" and scores zero for exactly the capability being sold. The
  headline metric stays net-new reach; it now counts the middle state as a partial win rather
  than discarding it, and the three states are separately reportable.
- **D18 — Optimise for reach over precision, because deal size dominates.** In the target
  segment (export, manufacturing, distribution, logistics) a single deal is worth thousands to
  tens of thousands. Expected value is hit-rate x deal size, so a false positive costs the owner
  one minute while a miss costs a year's worth of one deal.
  **Reason:** this is why "reach, not rank" is the right north star and not a slogan. It also
  sets the sensible operating point: a modest hit rate over a wide, novel candidate set beats a
  high hit rate over companies the owner already tracks. Scoring exists to protect owner time,
  not to maximise precision.
  **What this does not relax:** evidence correctness. A wrong *claim* costs credibility with a
  buyer, which is not recoverable by volume. Rule #2 and the release gate on evidence
  correctness stand unchanged (§18.1).

## 2026-10-03 — Signal availability probed live: follow the award chain, not the product CPV

Full evidence in `docs/integrations/signal-availability-probe-2026-10-03.md`. Cost $0.

- **D19 — Sensors search the works that consume the client's offer, not only the offer itself.**
  Measured EU-wide over three months: stone/paving products 36 notices, refrigeration equipment
  158, packaging machinery 26 - but road construction works 6,112, of which 1,190 award notices
  in two months each **name the winning contractor**. That is ~600 named, dated prospects a
  month for a paving supplier, against 12 from the product CPV.
  **Reason:** the organisation publishing a notice is almost never the buyer of materials. The
  contractor who won the work is. Searching only what the client sells finds the trickle.
  **Consequence for onboarding:** O must learn *which works create demand for this offer* from
  the owner, as data. No industry words in code (CLAUDE.md #1).
- **D20 — The award -> winner hop is pulled forward from M6 into the first radar.** The project
  graph as a whole stays in M6, but the single hop from an award notice to the winning company
  is what makes M5's candidate pool real rather than thin.
  **Reason:** without it M5 would be evaluated on ~12 candidates a quarter and would look like a
  failure of the idea rather than of the query.
- **D21 — The TED sensor is an API client, never a page fetcher.** `POST
  https://api.ted.europa.eu/v3/notices/search` works with no key, free, returning structured
  publication dates, deadlines, buyer and winner names. Both the TED notice page and its PDF
  fetched **empty** - the site is JavaScript-rendered.
  **Reason:** a page-fetching sensor would have silently produced nothing and looked like a
  coverage problem rather than a transport one.
- **D22 — Client fit is a selection criterion, not an engineering problem.** The radar is
  strongest where buyers are public bodies, or where public works create private buying moments;
  weakest in private-to-private niches whose only signals are unstructured trade press. Say so
  when choosing demo clients rather than trying to engineer around it.

## 2026-10-03 — Repeat winners are accounts, not leads; watch three stages, learn which converts

Measured live (TED, CPV 45233000 awards, Jan-May 2026). In a 250-notice sample - only 9% of the
2,839 awards in the window - **8% of the 421 distinct winners had already won more than once**.
Because the sample is small, that materially *understates* the true repeat rate. Examples:
EUROVIA CZ 7x, COLAS FRANCE 3x, PORR 3x, SWIETELSKY 3x.

- **D23 — The radar outputs qualified accounts as well as timed moments.** A contractor that
  wins public works repeatedly is a durable buyer of materials, verified by public record,
  whether or not any single job's timing is caught.
  **Reason (founder, 3 Oct):** a lead is a prospect you can sell to; right timing raises the
  odds but is not the only value. Missing one job's window still leaves a named, active,
  provably-buying business that a person can build a relationship with - and the next win is
  coming. This makes the product robust to the timing risk rather than dependent on solving it.
- **D24 — Watch three stages, and learn which one converts for this client.** Planning ->
  tender published -> award. The hypothesis to test is that *tender published* is the hot moment,
  because contractors price materials while bidding, weeks before an award is public - 6,112
  notices a quarter against 1,190 awards in two months. This is **not** hardcoded: the stage that
  converts is learned from outcomes via W's lag densities (ARCHITECTURE §11), seeded by the
  owner's own experience of whether buyers came to him before or after award.
- **D25 — The handoff to a person is the point, not a limitation.** The system's job ends at
  putting a qualified, sourced, dated company in front of a human, who then finds mutual
  contacts and negotiates. CLAUDE.md #5 stands: AI never negotiates. The evidence discipline is
  what makes that handoff worth acting on.

## 2026-10-03 — The product, in the founder's words

- **D26 — Northvaine is an assistant that does the laborious research a business's own sales
  team would have missed.** Not a replacement for salespeople: a tireless, multilingual
  researcher working beside them.
  **Founder, 3 Oct, verbatim in substance:** *"we just want to give an assistant who will do the
  laborious research for them that they would have missed - their team of 20 salesmen have
  missed."*
  **Why this is the right framing, and load-bearing rather than marketing:**
  - It is **honest about the claim**. Twenty capable salespeople still cannot read Latvian,
    Romanian and Polish procurement portals every morning. That is not a failing of theirs; it
    is a limit of human attention. The claim is tirelessness and language reach, not superior
    judgement.
  - It is **already the metric**. "What the team missed" is exactly net-new reach (ARCHITECTURE
    §0.1), and the one-tap "did you already know about this?" (D17) is its test. The headline
    claim and its measurement are the same quantity - so the product cannot drift into claiming
    something it does not measure.
  - It **sets the bar correctly**. A good lead the owner already had is worth little. The
    product is only working when it surfaces something a competent team would have missed.
  - It **keeps the human in the deal** (CLAUDE.md #5). The assistant researches; a person calls,
    finds who they know, and negotiates.

  **Use this sentence** as the opening line of the README and the demo video. The temptation
  when writing those will be to claim more; claiming more would make the headline unmeasurable.

## 2026-10-03 — The sweet spot is measured, not guessed: watch tenders, not awards

Measured live from 52 matched stone procurements (TED, CPV 44912000, since Jan 2024), joined
tender-to-award on `procedure-identifier`:

| Interval | Median | Range |
|---|---|---|
| tender published -> bid deadline | **30 days** | -31 to 67 |
| winner decided -> award published | **50 days** | 7 to 242 |
| tender published -> award published | **120 days** | 35 to 621 |

- **D27 — The radar's primary signal is the contract notice (`cn-standard`), not the award.**
  Watching awards arrives a median of **120 days** after the tender published and **50 days after
  the winner was already privately decided**. Materials were priced into the winning bid months
  earlier. The ~30-day bidding window that opens the day a tender publishes is the only moment
  when a contractor is actively pricing materials and has committed to no supplier - the one
  window where being new costs the buyer nothing.
  **Awards are not dropped**: they identify winners, build the account list (D23) and supply the
  outcome labels. They are intelligence, not opportunity. This supersedes the hypothesis in D24
  with a measurement.
- **D28 — Lag is learned from the public record before any outcome exists.** The tender ->
  deadline -> decision -> publication chain is fully present in history, so W's lag densities can
  be calibrated per CPV, per country and per client on day one, with no closed deals. This is a
  partial answer to cold start (ARCHITECTURE §17): the *timing* half needs no customer history,
  only the *conversion* half does.
  **Method:** join notices on `procedure-identifier`, which links every notice of one procurement.
  `winner-decision-date` on the award exposes the private decision date and therefore the
  publication blind spot.
- **D29 — Real notice data is messy and the sensor must not trust it.** Observed deadlines up to
  31 days *before* their notice's publication date (corrections and amended notices), and award
  publication lags up to 242 days. The TED sensor validates and flags rather than assuming
  monotonic dates; `available_at` is what gates replay, never the stated date.

## 2026-10-03 — Two signal streams, not one: the specification window and the pricing window

Founder: for a stone exporter, a new hotel, a new development or an architect's project are
signals too. Probed live, 3 Oct.

| Stage | Lead time | Source | Enumerable | Prize |
|---|---|---|---|---|
| planning approved / project announced | 12-24 months | trade press, planning portals | **no** | **specification** |
| tender published (`cn-standard`) | **30 days** (D27) | TED API | **yes** | quote into the bid |
| award (`can-standard`) | already late | TED API | yes | account intelligence (D23) |

- **D30 — The radar runs two streams with different economics, not one pipeline.** The *pricing
  window* (TED tenders, D27) is enumerable, structured and complete: ask for every tender in a
  country and get all of them. The *specification window* (project announcements) is earlier and
  worth far more - in building materials, being in the architect's specification wins the job
  before bidding exists - but it is **not enumerable**: you find some projects, never all, and
  you cannot know what you missed.
  **Evidence it is worth the mess:** the Apex City of Bath hotel facade consumed **over 1,000
  tonnes** of Bath stone. One specification win is worth a year of quotes.
  **Consequence:** recall is honestly reportable for the TED stream and *not* for the
  announcement stream. Never present them with the same confidence; ARCHITECTURE §18.1's recall
  metric applies to the enumerable stream only.
- **D31 — The contact target changes by stage, and so must the brief.** At award stage the
  contractor is named. At planning stage the useful contact is the architect or developer, who is
  often not named in the announcement, so investigation cost per candidate is higher. The brief
  template must carry *who to approach and why now*, which differs per stage - as data from O,
  not as code (CLAUDE.md #1).
- **D32 — `planning.data.gov.uk` is not usable for a live radar (checked 3 Oct 2026).** Genuinely
  open, well structured, no key - but covering roughly four local authorities with its most
  recent entry dated September 2025. Commercial alternatives (Glenigan, Barbour ABI, Searchland)
  are paid. **Do not design a sensor around the official planning API** without re-checking
  coverage first; the UK early-stage stream must come from trade press and announcements until
  that changes.

## 2026-10-03 — "Not hardcoded" is the pitch, not just an invariant

- **D33 — CLAUDE.md #1 is the commercial differentiator, and the §0.2 demo is how it is proved.**
  Competitors ship a fixed taxonomy - SIC codes, intent topics, prebuilt filters decided by
  someone who has never sold the customer's product. Northvaine cannot have categories: the
  moment an industry word enters the code, the engine serves one business.
  **So everything the owner knows enters as answers, not code:** which works create demand for
  the offer (D19), who to approach at which stage (D31), what must be known before calling. A
  freight forwarder answers differently and gets a different radar from identical machinery.
  **Every other tool claims "it learns your business." This one is architecturally forced to
  mean it** - which is the whole value of the invariant being an invariant.
  **The claim is only credible if demonstrated:** ARCHITECTURE §0.2's proof - the radar runs for
  2-3 very different sample clients **with no code changes** - is therefore not a nice-to-have in
  the demo video. It *is* the pitch. Without it the generality claim is an assertion.
- **D34 — Adaptation must feel like a conversation, not configuration.** If "it adapts to you"
  means a long setup interview before anything useful appears, the product has sold flexibility
  and delivered homework. The first brief should arrive fast and imperfect and sharpen as the
  owner corrects it; VOI question selection (ARCHITECTURE §6.3) should earn each question rather
  than front-loading a form. Watch this when M8's onboarding chat is built.
