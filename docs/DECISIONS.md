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

## 2026-10-04 — Milestone 3 sensors (from factory/board/M3/PLAN.md, founder answers 4 Oct)

Founder confirmed the three proposed sample clients (stone supplier into UK+EU; EU cold-chain
equipment maker; packaging supplier to cosmetics brands, announcement stream only) and that
redacted, contact-free TED and Tavily fixtures may be committed to the public repo. No UK Find a
Tender sensor in M3 (parked). Migration 0004 approved by the orchestrator (technical, reversible).

- **D35** Sensors speak a generic query language (`SensorQuery`: EventType kinds, scheme-prefixed
  codes, ISO 3166-1 alpha-2 countries, ISO 639-1 languages, free text, a date range). Each sensor
  maps it to its own vocabulary inside its module; client values exist only as data (rule #1, D33).
- **D36 (provisional)** TED `available_at` = 00:00 UTC of `publication-date + ted_availability_lag_days`
  (default 1), derived only from `publication-date`. Deadlines and decision dates are stored, never
  used for availability (D29). Provisional until the API indexing lag is measured by an hourly poll.
- **D37** Live web and Tavily documents get `available_at = fetched_at`; claimed dates go to
  `published_on` flagged `claimed_date_untrusted`. Sensors raise `ReplayUnsupported` for an
  `as_of` they cannot honour (ARCHITECTURE §23).
- **D38** Messy dates are flagged with `DateFlag` values stored on the document, never dropped or
  corrected (D29).
- **D39** A notice's document text is a deterministic plain-text rendering of its PII-free search
  record, so code quote checks (rule #2) have real text; the structured fields live in
  `documents.meta` (`schema_ver` 1). Raw TED XML is never persisted.
- **D40** Migration 0004: `documents.external_id`, `documents.group_key`, `documents.meta jsonb`,
  indexes on (source_id, group_key), (source_id, external_id), (available_at), and
  `UNIQUE (sources.name)`. Sources stay **global provider rows** ('ted', 'tavily', 'website',
  'order_history'); privacy lives in `documents.workspace_id`, not in sources. Before `migrate`
  on production, the orchestrator checks `SELECT name FROM sources GROUP BY name HAVING count(*) > 1`.
- **D41** Every sensor declares `enumerable`, carried on every `SensorResult`. Recall and
  coverage are reported only for enumerable sensors (D30).
- **D42** Sensor fixtures are recorded once from the live API by the orchestrator through T3.1's
  recorder, redaction first, and are never hand-written. Synthetic HTML is allowed only for
  fetch/SSRF/robots/website tests, which test our own code, not an API shape.
- **D43** Sensor HTTP uses `httpx` (promoted to a runtime dependency), called directly. No Tavily SDK.
- **D44** TED requests only the research allow-list of fields (`TED_SAFE_FIELDS`), paces at
  >= 1.5 s, uses PAGE_NUMBER pagination, de-duplicates on (publication-number, notice-version),
  and never sends unconfirmed body parameters.

- **D36 note (PF2, 4 Oct):** TED search returns only the latest version of a changed notice,
  dated by the change. The replay risk is therefore *loss* of the original notice from its date
  window, not early leakage of new content. Documents with `notice-version > 1` are flagged, and
  old fixture windows are never re-recorded to "refresh" them (a re-record returns a different set).

## 2026-10-04 — Milestone 4 evidence ledger (from factory/board/M4/PLAN.md)

Founder answered both questions on 4 Oct: Q1 yes (code-only verification for structured
official records, a spec change to SPEC §5 for that source class only), Q2 yes (snippet-only
results are leads, not evidence).

- **D45** A document is evidence only by an explicit, data-driven source rule
  (`evidence_source_rules`): `structured` (TED), `full_text` (website), `raw_only` (Tavily with
  `text_kind='raw'`). Everything else, including snippet-only results and unknown sources or
  text kinds, is a **lead**: no extraction, no claims, no LLM spend (fail-closed). M5's discover
  stage upgrades a lead by fetching the publisher URL through `safe_fetch` into a website document.
- **D46 (founder Q1)** Structured official records (TED, D39 rendering) yield claims and events
  by code. `source_quote` is one exact rendered line, the statement is a generic template over the
  same field, the quote check is a whole-line exact match, and `verified_by='code'`. No LLM
  extraction or support check.
- **D47** Extraction and normalization are one fast-tier call per full-text document. The support
  check is one fast-tier call per document, batching only claims whose quotes passed; it sees
  statements and quotes only (no document, no goal), all fenced. A missing verdict = unsupported.
- **D48** Quote check, extracted mode: NFKC + quote/dash/whitespace normalization, exact match
  first, then a stdlib `difflib` window fallback at ratio >= 0.95, minimum 20 characters.
  Structured mode: exact whole-line match, no minimum. `quote_offset` indexes the original
  `documents.text`. No new dependency.
- **D49** Every extracted claim is stored with a status (verified or a rejection reason) to measure
  extraction precision. Consumers read only the `verified_claims` view. CHECKs tie `verified` to its
  status and require `quote_offset` and `verified_by`. `check_invariants` forbids SQL on claims and
  `ClaimRow` imports outside `core/ledger.py`. `save_events` refuses unverified claim ids.
- **D50** The LLM never decides a fact on an event. Dates are written text parsed by code
  (`sensors.dates.parse_date`), and every event field (date text, subject, country, string slots)
  is kept only if it appears in a verified quote of that event; otherwise it is dropped. The event
  description is composed by code from verified statements. `available_at` = the latest
  `available_at` of its claims' documents (in M4: its document's).
- **D51** Concepts: the extractor picks the level-0 type from the seeded labels (data, minus
  `extract_excluded_event_types`). Level 1 = nearest child at cosine >= 0.80, else a `proposed`
  child named by the extractor (its first event's embedding seeds it). Dedup: events share a
  cluster when type matches, subject key or group_key matches, the date window holds, and cosine
  >= 0.85; events without embeddings cluster deterministically on (type, group_key) or (type,
  subject key, window). Candidates are filtered by `as_of`. Thresholds are settings in M4.
- **D52** Migration 0005 as in the frozen contracts (claims status/meta/fingerprint and two CHECKs;
  events available_at/description/embedding/fingerprint; the `verified_claims` view). Events are
  idempotent on `fingerprint`.
- **D53** LLM fixtures are recorded only by the orchestrator (`tasks.py record-llm`) through
  `llm.client_override` + `RecordingClient`, redacted with `smoke_llm.redact`, never hand-edited.
  Replay is keyed by sha256 of the nonce-normalized request body (a prompt change needs a
  re-record) and pinned to the recorded model ids by `replay_environment`. Vectors stored rounded
  to 6 decimals.
- **D54** Entity resolution is deferred to M5. Subjects are stored as mentions (name, ISO2 country,
  generic role) in `claims.meta` and `events.slots`; `company_id` stays NULL in M4.


## 2026-10-04 — Milestone 4 close-out (from the T4.6 replay suite)

- **D55 — A fuzzy quote match stores the document's words, and never changes a number.** The
  T4.6 golden set found that a quote saying "250 staff" passed at ratio 0.987 against a page that
  says "240 staff", and the model's text was then stored and sent to the support check, which
  cannot see the page. Now (a) a fuzzy match whose numbers differ from the matched span is a
  `quote_not_found`, and (b) after any fuzzy match `source_quote` is replaced by the document's
  own span, so the support check and every reader judge the statement against what the source
  actually says (a dropped "not" is then caught by the support check). Tightens D48.
- **D56 — An award notice that names no winner yields verified claims but no event.** The
  `contract_awarded` event exists to identify a winner (D23); with no winner there is no account
  to learn. T4.6's acceptance wording "every TED notice produces an event" is superseded; the suite
  asserts instead that the only silent notices are winnerless awards.
- Derived slots `subject_key` and `group_key` are computed by code (for TED, the procedure id
  from the record), not model output; an extracted `group_hint` is kept only when a verified
  quote contains it (D50).

## 2026-10-05 — Milestone 5 First Reviewable Radar (from factory/board/M5/PLAN.md)

Founder answered 5 Oct: generated briefs are shared privately and never committed (D66); an
honest 'sources are thin' packaging brief with no padding is a pass. Brief source: ChatGPT's M5
brief with Claude's five corrections (docs/COLLAB.md).

- **D57 — Extractor v2 names the company.** `subject_name`, `subject_role` and `date_text` (claims
  and events) become required-nullable fields of the strict schema, and the prompt requires the
  quote to contain the organisation's name (otherwise grounding drops it, D50). An event type is
  used only when its seeded description fits; otherwise no event. Re-record, never hand-edit (D53).
- **D58 — Entity resolution in M5 is one explicit code rule.** Match key = NFKC, casefold,
  punctuation stripped, legal-form tokens removed (a settings list, not industry words), plus the
  ISO2 country. A country-less mention joins the single countried key with the same name, else it
  stays separate. No LLM pair resolution, no domains, no merging across different countries.
- **D59 — A lead is upgraded once by fetching its publisher page.** Robots.txt, the deny list
  (rule #9) and `safe_fetch` apply; emails and phone numbers are stripped from the text before it
  becomes a `website` document (`available_at = fetched_at`, `meta.upgraded_from` = lead URL);
  at most `radar_max_lead_upgrades` per run; every refusal is kept with its reason.
- **D60 — Three streams on every brief entry.** `tender` (enumerable; window = publication to the
  earliest stated deadline, else +30 days marked *estimated*, D27), `award` (enumerable; account
  intelligence, D23; no window), `announcement` (not enumerable; specification window; date only
  as stated). Recall is reported only for enumerable streams (D30). A company seen in several
  streams is one entry with a primary stream (tender > announcement > award).
- **D61 — M5 persists the radar run as a JSON run record; database cases wait for their first
  reader.** `run.json` keeps every candidate, passed and rejected, with `rejected_as`, reason and
  `by`, never deleted. Writing `companies`/`cases`/`case_evidence` (and a `rejected_as` column)
  lands with the case file in M6, mapped from this record. Keeps M5 offline and DB-free.
- **D62 — Gate and skeptic.** Code rejects candidates with no named company (`unidentified`)
  before any model call. The gate is one mid-tier call per candidate over its verified claims and
  the client's offer, choosing buyer / competitor / reseller / publisher / not_a_buyer /
  not_an_organisation; a natural person is rejected and their name withheld from reports. The
  skeptic runs only on passed candidates (mid tier) and must cite claim refs, else `unknown` with
  open questions. No judge / deep model in M5.
- **D63 — Model-written brief sentences cite claims and never introduce a number.** Demand
  reason, buyer reason, suggested action, skeptic reasons and open questions must cite valid claim
  refs, and every number in them must appear in a cited verified quote; otherwise the sentence is
  shown as "not stated". Facts are rendered only as verified statements with verbatim quotes.
- **D64 — Ranking is lexicographic and explained.** Order by (evidence strength, window urgency or
  recency, direct buyer); each component is printed as a reason line. No numeric score.
- **D65 — Radar runs are fresh and replayable.** Query date ranges are shifted to end at the run
  date (same length); a radar recording (HTTP exchanges, fetched pages, LLM exchanges, meta with
  `as_of` and the shifted queries) lives in `tests/fixtures/radar/<client>/`. Replay is the
  default; only the orchestrator records. M3/M4 fixtures stay as they are (except T5.1's re-record).
- **D66 — Generated reports are not committed** (founder, 5 Oct: shared privately, never committed): `reports/radar/` is in
  `.gitignore`.

- **D67 — Radar modules take the HTTP client as `Any`.** Network imports stay confined to
  `northvaine/sensors/` (check_invariants); `discover.py` and `run.py` receive a client built by
  sensor helpers rather than importing httpx, even for type hints (T5.0 contract note).
- **D68 — Checkpoint A passed on prompt v3 (5 Oct): 5/6 = 83% of extracted events carry a
  grounded company, 0 misses.** v2 reached 50%: the model named the company but tied events to
  quotes that did not contain the name, so grounding (correctly) dropped it. v3 requires the
  exact name inside the claim's own quote, an event to cite at least one claim naming its
  subject, and no events from general profile or strategy statements. Event typing is still loose
  on news-index pages; judging that is the M5 gate's job, not the extractor's.
- **D69 — A live radar recording logs every model call and obeys every cap.** T5.6 recorded with
  no database session, so calls skipped `llm_calls` and the per-day and lifetime caps (CLAUDE.md
  #8). `run_radar` now takes `session` and passes it to extraction, gate and skeptic; `record-radar`
  opens `session_scope` like `record-llm`. Replay still passes no session.
- **D70 — The recording secret scan needs a word boundary and a real key prefix.**
  `smoke_llm.KEY_PATTERN` matched "sk" inside ordinary words ("maersk-nimmt-neues-..."), which
  refused a whole live radar recording. It now needs a non-alphanumeric character before
  `nvapi-`, `sk-` or `eyJ`. Keys actually in use are still caught by exact match (known secrets).
  Same fix as check_invariants on 4 Oct.
- **D71 — Radar queries are focused on what a seller can still act on.** The first live stone
  brief listed only closed tenders: TED returns oldest first, the run read one page of 10 (57
  matched), and the tender lookback was 4 months against a ~30-day bidding window (D27).
  `focus_queries` now limits tender-stream queries to `radar_tender_lookback_days` (45) and asks
  enumerable sources for up to `radar_enumerable_max_results` (100). Both settings are stored
  with each recording and pinned on replay, so a recording replays with what was actually sent.
- **D72 — A notice's title is a verified claim on its event.** The first readable stone brief
  showed buyer, dates and CPV codes but not what the tender is for, so the founder could not judge
  relevance. Structured evidence now adds one `Title [..]` line (English when present) as a
  code-verified claim on tender and award events.
- **D73 — One document or candidate the model cannot answer is a note, not a failed run.** The
  packaging recording crashed when Nemotron's extraction was cut off mid-JSON three times.
  `extract_max_tokens` rises from 1500 to 3000 (8 claims with long quotes need it), and
  `run_radar` turns `LlmInvalidOutput`, `LlmTimeout` and `LlmTransportError` on one item into a
  "skipped" note. Replay mismatches still fail loudly.
- **D74 — The gate judges whether what an organisation did creates the need, not whether it
  announced a purchase.** The first packaging run rejected all 17 named cosmetics brands as
  "no claim indicates X purchases packaging", although a brand launching a range is exactly what
  creates packaging demand. Tenders passed only because they state the purchase. Gate prompt v2
  defines buyer by need created (building, opening, expanding, launching, commissioning). The
  packaging sample offer also lost a stray test note ("Announcement stream only.").
- **D75 — The gate reasons before it decides.** Gate v2 still contradicted itself ("street
  surface works, which indicates demand for paving" -> not_a_buyer) because `GateOutput` asked
  for `verdict` first. `GateOutput` now starts with `what_it_did` and `needs_the_offer` (never
  shown), and prompt v3 makes the verdict follow from them. A live probe on 12 previously
  rejected candidates (under $0.01) passed the open stone tenders and the launching cosmetics
  brands; two buyer verdicts with no cited claim were still held back by code. The packaging
  offer drops "private" (the model read it as "private label").
- **D76 — Names of natural persons in TED notices are withheld at parse time.** The cold-chain
  and stone recordings held about nine winners whose legal form makes them natural persons
  (German `e.K.` sole traders, `GbR` partnerships), several named after their owner. The repo will
  be public. `parse_notice` now replaces buyer and winner names carrying a
  `ted_natural_person_markers` legal form with a stable "[natural person, name withheld <hash>]"
  placeholder. The radar recorder applies the same function, so replay equals live. Such names
  never become candidates. Firm names such as "ETS GIFFARD" are kept.
- **D77 — A citation is read by its leading ref.** Nemotron sometimes copies the whole claim line
  into `cited_refs` ("C1: ... / quote") instead of "C1". Code dropped those as unknown refs and
  held 9 of 11 packaging buyers back as insufficient evidence. `ref_of` now takes the leading ref
  before a colon; only refs the candidate actually has are kept, in the gate and the skeptic.
- **D78 — In a radar run, nothing is available after the run's own moment; open questions need
  no citation.** T5.7 found search results stamped with the parse-time clock, so on replay they
  were "available" after `as_of` and `run.json` differed between replays. `run_radar` now caps
  every document's `available_at` at `as_of`. D63's citation rule covers statements (demand,
  buyer, action, evidence against); the skeptic's open questions are questions, not facts, and
  stay number-grounded against the entry's quotes without a citation.

## 2026-10-05 — Scope for the rest of the build (founder)

- **D79 — The full learning system is in scope; simulated data is allowed, labelled as
  simulated, and real public history comes first.** The founder: build the product fully, and use
  invented data where real customer data cannot arrive in time. CTO rules for this:
  1. **Real public history first.** Tender -> award chains on TED are real outcomes (D28): who
     won what, after which signals and with what lag. The buying-pattern and world-state learners
     train on these before anything is simulated.
  2. **A simulated owner** (ARCHITECTURE M10) gives feedback where no customer exists yet. Its
     preferences are written down as data, and every result it drives is marked `simulated`.
  3. **Never presented as customer evidence.** Demos, the README and the pitch say which results
     come from public history, which from simulation, and which from real users.
  4. **Learners are swappable**, so real partner outcomes replace simulated ones without code
     changes.
  Order: Phase 0 first (ROADMAP.md), then the learners on public history, then the simulated owner.

## 2026-10-08 — M5.1 brief quality (T5.8), shaped by ChatGPT's review and the WOS field test

- **D80 — Briefs say what is known, who buys, and what to do, and nothing more certain than the
  evidence.**
  1. **Requirement stated or inferred, decided by code.** It is `stated` only when a verified
     quote names a content word of the client's own offer text (generic stopwords in settings).
     The model plays no part, and no gate change or re-record was needed. It ranks first.
  2. **Ranking order:** requirement, then window (open with at least `radar_min_days_left`
     days, then recent, then undated, then too late, then closed), then evidence strength, then
     direct buyer.
  3. **Action status, from the WOS method:**
     - *watch only* for any tender before award, because the authority is a demand source and
       not the material buyer;
     - *contact now* for an award or announcement with a stated requirement;
     - *qualify first* otherwise.
  4. **A one-screen summary.** "Accounts to approach" and "Tenders to watch" are kept apart,
     with what, requirement, why now and caution per row, all code-composed.
  5. **A short main list.** Full write-ups only for stated or strong entries, capped at
     `radar_brief_main_entries` (5). The rest go in "Also found, weaker". Thin sources means
     fewer than 3 full write-ups.
  6. **Plain wording.** One sentence from the record's own lines; "who buys" and "next step"
     per stream, plus an opening question that tests a hypothesis rather than claiming a need.
     These come from settings, generic and never industry words.
  7. **Contract values** carry "value of the whole contract, not the share for what you sell".
  8. **The scorecard gains an "after contact" table** with the field-test loop: known already?
     New intelligence? Contacted? Outcome?

  Not done here, recorded as next: tracing award winners into named contractors' accounts
  (D23), import and shipment data, and a cross-check against the company's own catalogue. All
  three are in the WOS method and are new sensors or learners, not brief changes.
- **D81 — Likely bidders: for each open tender, who won similar awards in that country
  recently.** This answers "who buys the material before the award" (D23, the WOS method, step 3)
  and is the first connect-the-dots feature (ROADMAP vision).
  - **The search:** one TED award search per distinct (tender codes, country), over the last
    `radar_bidder_lookback_days` (365), capped by `radar_bidder_max_queries` (8).
  - **The winners:** parsed through the structured evidence path, so they are code-verified with
    no model call and no cost. Withheld natural persons are excluded.
  - **Ranking:** winners are counted and ranked by wins and recency; the top
    `radar_bidder_max` (5) are kept.
  - **In the brief:** tender entries list them with their latest award notice, and the summary
    caution names the top two.
  - **Failures:** a failed search is a note. The settings are stored with each recording, so
    replay equals live.
- **D82 — The independent review of M5.1: the requirement is checked against what the client
  sells, as data; dates and labels say only what a claim supports.**
  1. **What the client sells is data.** `ClientSpec.offer_terms` lists it in any language and
     matches word starts. Without it, only the product part of the offer is used (before
     "for/into/selling..."), with whole words and generic nouns stopped. "Packaging for
     cosmetics brands" no longer makes cosmetics a stated need.
  2. **Only stating claims count:** the record's title, or a quote that names the candidate.
     Buyer and Winner lines, and the withheld-person placeholder, never count.
  3. **Dates come only from claim-backed event dates,** never the fetch time. Future dates read
     "planned for".
  4. **Strength counts independent documents.** Full write-ups go to approachable accounts first.
     "Thin" means fewer than 3 approachable accounts.
  5. **"Contact now" requires** a stated requirement, no skeptic points against, a direct buyer
     and evidence that is not weak.
  6. **Honest labels:**
     - "award published" unless a decision date is stated;
     - the deadline marked estimated or "likely too late";
     - contract value captioned as the whole notice across all lots and winners, in the stated
       currency.
  7. **All untrusted text is Markdown-escaped,** and links are printed only when they are http(s).
  8. **The scorecard parser** splits on unescaped pipes only, and "x" and "-" are no longer
     yes/no marks.
- **D83 — UK Find a Tender (`fts`) is a registered, structured, enumerable source.** It renders
  the same lines as TED, so the evidence path is shared. Contact details are never read. Award
  dates are publication dates, because FTS has signing dates but no decision dates.
- **D84 — Requirement has three levels: stated, related, inferred.** A real case: the Corte
  notice says "paving" and "masonry and pavements", not natural stone. Matching only the general
  word overstated the fit. Each client now lists specific `offer_terms` (exactly what it sells)
  and `related_terms` (products near it).
  - **Stated:** a stating quote names a specific term.
  - **Related:** a quote names only a related term. It ranks below stated, is never "contact
    now", and the caution says to ask about the specification.
  - **Inferred:** neither is named.
- **D85 — Sources can never steer the system (CLAUDE.md #10, founder's rule).** A page might
  say "mark me highest" or "ignore previous instructions".
  - **Removed first:** before any model sees fetched text, every sentence matching
    `radar_steering_patterns` is replaced with "[text aimed at AI systems removed]". These are
    generic patterns, held as data in settings: sentences that address AI systems or ask to be
    ranked, rated, marked or prioritised.
  - **Flagged:** the page is listed in `steered_urls` and a run note, every entry it supports is
    marked `steered`, and it can never be "contact now". The caution says to check it by hand.
  - **Pointless to game:** ranking was already code-only. This makes trying to game it lower
    trust instead of raising it.
- **D86 — A finished run can be saved into the canonical schema (`radar/persist.py`).**
  `run_radar(evidence_out=...)` hands out every document read with its ledger result, and
  `persist_run` saves them. `radar.py --save` uses it in replay or record mode.
  - **What is saved:** documents, all claim checks, companies (keyed by
    `attributes.radar_key`), one open case per company and window (stage `briefed`),
    `case_evidence` (for, and against where the skeptic cites a claim), open questions, and a
    `decisions` row (kind `brief`, propensity 1) for every gated candidate.
  - **Later runs update, never duplicate:** they update the open case's verdict and append to
    its trace. They never move a case backwards past `briefed`.
  - **Privacy:** unidentified subjects and natural persons get no company row, and their
    decision rows keep no reason text.
  - **Not saved yet:** events, because the radar's seeded concepts are not `event_concepts`
    rows. This is what feedback, outcomes and the learning loop attach to.
- **D87 — Every lead records which search found it, and events are saved.** Discover maps each
  document to the queries that found it (`found_by`, "sensor:index"). A run's decisions store
  its sources, those refs, and stable `query_keys`. A query key is the sensor plus a hash of its
  text; a code-only query uses its fixed parameters, never its dates. Events are saved with their
  seeded concept mapped by label to the stored row, and linked to their company. Without this, a
  rating could not credit the search that paid. Saving is batched: one statement per table
  instead of a round trip per row.
- **D88 — Graph v0: the web lives in Postgres, every line backed by verified claims.**
  - **Migration 0006:** `company_identifiers` (scheme, value), where companies are found by the
    `name_country` key first; and `links`. A link has two ends among company, event and
    procedure ('<source>:<the source's own id>'), a relation, a derivation (stated, related or
    inferred), non-empty verified `claim_ids` (checked by code), a confidence for inferred links
    only, two times (`valid_from`, `available_at`), and an idempotent fingerprint, with more
    evidence merged into the same line.
  - **A run writes:**
    - stated company -[buyer|winner]-> procedure, from official records;
    - inferred procedure -[likely_bidder]-> company, with the verified winner lines as proof,
      and confidence = wins / (wins + 1), capped at 0.9 and stated in `details`.
  - **No model ever proposes a line;** graph frameworks (GraphRAG and similar) were rejected for
    that reason (docs/research/graph_connect_the_dots.md).
  - **Reading:** `neighbourhood()` returns nodes and edges, each edge with its quotes and URLs,
    and can hide lines not yet knowable at `as_of`.
- **D89 — Learning loop v0, and labels say who gave them.**
  - **Migration 0006:** `feedback.source`, `feedback.weight` and `outcomes.source`
    (owner, simulated or judge).
  - **Maths (`radar/learning.py`):** weighted Beta posteriors for query, source and country
    yields. A query shrinks to its source, and a source to the pooled rate. `wrong_facts` moves
    source reliability only; `later` moves nothing.
  - **Strategy versions (`radar/strategy.py`):** each version writes `beliefs` and
    `strategy_versions` rows, with a trust region per version. Rollback is loading an earlier
    version. A query is paused, never deleted, when it is very probably below its source with
    enough labels.
  - **Behaviour:**
    - a strategy with enough labels chooses each run's searches by Thompson sampling, with an
      exploration floor; propensities are logged;
    - the learned yield breaks ranking ties only;
    - one brief slot is a uniform random pick from below the cut (`radar_exploration_slots`,
      propensity 1/m), shown as "exploration pick", and never counted as approachable.
  - **Simulation:** owner labels and simulated labels never mix. The SIMULATED owner study
    (`eval/simulate.py`, `tasks.py learn-sim`, owners as data in tests/fixtures/owners) compares
    learning with a random choice on the same budget and with all searches. On the stone
    recording, learning beat random for owners whose taste is learnable. On cold-chain there was
    no difference, because the pool is uniform. Starting numbers are guesses, to be re-set from
    real labels.
- **D93 — Local-language searches are proposed, never applied.** `radar/expand.py` makes one
  fast-tier call (`query_expand.v1`; the seller's existing words and searches are fenced as
  untrusted) for searches and "what we sell" words in the target languages. Code drops:
  - targets not asked for;
  - web addresses and odd lengths;
  - text aimed at AI systems (D85);
  - duplicates.

  The result is a proposal for a person to approve. It never edits a client spec.
- **D91 — World Bank procurement notices sensor (`sensors/worldbank.py`, source `worldbank`).**
  Open calls and contract awards for World Bank financed projects in 100+ countries, as
  OFFICIAL documents in the TED and FTS line format, so `radar/structured.py` reads them
  unchanged. Registered in `SENSOR_NAMES`, `radar_enumerable_sources` and
  `evidence_source_rules` (`structured`). All settings sit in one `worldbank_*` block.
  - **Endpoint (confirmed by live keyless probes, 2026-10-09; no official parameter page
    exists):** `GET https://search.worldbank.org/api/v2/procnotices?format=json&rows=&os=&fl=
    &notice_type=&qterm=`. Newest first. `rows` is capped at 1000 and `os` at 100000. There is
    **no date filter** (date parameters are ignored or rejected), so the window is applied here:
    a stream stops at the first page older than `published_from`, and a window far in the past is
    found by bisection on `os` with one-row probes. Error bodies come back as HTTP 400, or 200
    with an `error` key; both raise a body-free `SensorError`.
  - **Licence:** the dataset "World Bank Procurement Notices" (World Bank Data Catalog 0037795)
    is Creative Commons Attribution 4.0, classification Public. Commercial reuse is allowed with
    attribution to the World Bank. The API gives no rate limit; we pace at 1 request a second.
  - **Notice types read** (`worldbank_notice_types`, data): Invitation for Bids and Request for
    Expression of Interest are `tender_published`; Contract Award is `contract_awarded`. General
    Procurement Notices (early plans, no deadline or buyer) are not read.
  - **Structured vs text:** title, dates, deadline, project, method, group, reference and the
    implementing agency (`contact_organization`, the buyer) are fields. Winner, winner country,
    signed price and award date exist only inside the HTML `notice_text` of awards. They are
    read from the "Awarded ..." section by fixed patterns and written as rendered lines. The
    rule stays `structured` because every quoted line is deterministic code output, but those
    four lines are only as good as the pattern: a notice that does not match gets no winner (a
    note says so), never a guess. An award notice names no buyer, so none is stated.
  - **Privacy:** `fl=` never asks for `contact_*` fields. The text of open calls is not
    requested at all (contact names sit unlabelled inside it). Award text is read only in its
    "Awarded" section: bidder addresses, evaluated and rejected bidders and beneficial-owner
    tables are never read. Individual-consultant contracts (`INDV`) are dropped. Winners of
    direct-selection consultancies (`CDS`) are always withheld, since they are often one
    person. Other names pass through `withhold_natural_persons` (D76) with
    `worldbank_natural_person_markers` added. **Limit:** a sole trader named like a company
    ("X & FRIENDS SME", a bare personal name under a goods method) cannot be detected.
  - **Not built:** the Projects API (`/api/v3/projects`, CC BY 4.0, borrower, implementing
    agency, amount, board approval date, abstract). Projects are the earliest signal, but no
    existing event type fits "project approved", and one source name cannot be `structured` for
    notices and `full_text` for abstracts. Follow-up: a new event type plus a second sensor name.
  - **Source quirks handled:** some text fields are UTF-8 read as cp1252 and are repaired;
    country names differ from ISO (`worldbank_country_aliases`); regions give no country; an
    award's "decision date" may be years older than the notice (flagged `extreme_lag`).
- **D90 — US federal contract awards come from USAspending (`sensors/usaspending.py`).**
  Keyless `POST /api/v2/search/spending_by_award/`, awards only, enumerable, official tier,
  `evidence_source_rules["usaspending"] = "structured"`, in `radar_enumerable_sources`.
  - **Same evidence path:** records render the TED/FTS line format (Title, Buyer, Winner, value
    in USD, decision date, public award page URL). `structured.py` gained two generic code lines,
    `NAICS:` and `PSC:` (slots `naics_codes`, `psc_codes`), so the existing path works otherwise
    unchanged. Buyer is the sub-agency first, then the agency.
  - **Dates:** `Published` is the record's last-modified date (plus a 3-day lag for
    `available_at`), so a later amendment never leaks into a replay. The decision date is the
    base obligation date. The window uses `new_awards_only`.
  - **Privacy (D76):** recipients that are natural persons are withheld, by markers held in
    settings, redaction text, and a conservative person-shaped name check. Addresses, contacts,
    UEI and DUNS are never requested. Limit: the API gives no recipient type in search results,
    so a sole trader trading under a business-style name is not detected.
  - **Not done:** `likely_bidders` still queries TED only. US use needs a country-to-sensor
    setting and `naics:` codes on US tenders, which arrive with the SAM.gov sensor.
- **D92 — Small classifier experiment: not a gate pre-filter now (research only, no product change).**
  Question: can a small trained classifier imitate or pre-filter the Nemotron gate?
  - **Data:** the three recorded runs give only 98 LLM-decided gate rows: 89 passed, 9
    `not_a_buyer`, and no competitor, reseller or publisher rows. 41 more were rejected by code
    (all `unidentified`) and are not labels.
  - **Result:** TF-IDF and embedding + logistic regression did not beat "always passed" (90.8%
    agreement). At a threshold keeping 95% of passed rows they skip about 4 to 6% of gate calls;
    at 99% kept, 0%. A gate call costs under a tenth of a cent, so the saving is negligible.
  - **Recommendation:** no pre-filter now. Reconsider after about 500 real gate decisions that
    include the other verdicts (50 or more per rejection class), with a spot-check of skipped
    candidates. The better use is an owner-rating classifier in the learning loop (after about
    100 ratings per workspace).
  - **"JEV":** most likely Jev by TypeSafe AI, a proprietary hosted classifier API (new signups
    paused 22 Sep 2026, no open weights, licence unknown). Not run and not adopted.
  - **Left behind:** `scripts/experiments/gate_classifier.py`, an `experiments` dependency group
    (never in runtime deps) and `docs/research/classifier_experiment.md`.
- **D94 — Who the account is, and how strong its buying evidence is (CEO priorities, 9 Oct).**
  `radar/account.py`, code only.
  - **Contract nature:** supplies, works or services, as the source states it. TED reads
    `contract-nature` (confirmed live 9 Oct); FTS reads OCDS `mainProcurementCategory`; the
    World Bank reads its procurement group code. It is a quotable "Contract nature:" line, so
    it becomes a verified claim. Otherwise it is derived from the CPV division (a mapping in
    settings) and labelled derived.
  - **Account role:**
    - a supplies-tender authority is a direct purchaser;
    - a works or services authority is a demand source and never the material buyer;
    - a works or services award winner is the awarded contractor, the account to approach;
    - a supplies award winner is a supplier (a competitor or a channel);
    - anything else is unresolved.
  - **Evidence level:** explicit purchase, project requirement, company fit (website check,
    next), generic mention, or no evidence. The level is the first ranking key.
  - **Status:** "contact now" needs an explicit purchase plus the existing no-doubt rules. A
    supplies tender with an explicit purchase is "bid now"; every other tender is
    "watch only".
  - **Brief:** the summary's column is now "Evidence". Each write-up shows the account role,
    the nature and the level. An awarded contractor gets a cited chain: authority → project →
    awarded to this company.
- **D95 — The outcome data contract: owner answers become labels without parsing Markdown.**
  - **Capture:** the web app stores each answer as a structured record, now with
    `accepted_for_contact` (the salesperson's disposition) next to the closed-set failure
    reason and the after-contact fields.
  - **Mapping (`radar/labels.py`, `rating_of`):** a wrong fact means `wrong_facts`; a positive
    outcome or acceptance means `good`; any other failure reason, or not relevant or not
    actionable, means `not_relevant`; anything else is no label, because unknown is not
    negative.
  - **Import (`scripts/import_feedback.py`):** writes `feedback` rows on the saved cases,
    idempotent on case and received time.
- **D96 — Company fit from the company's own website (CEO priority 2, 9 Oct).** `radar/fit.py`,
  code only, no model call.
  - **What it answers:** does a shortlisted account (an awarded contractor, or an unresolved
    announcement) handle what the client sells, in its own words? A fit is not a purchase, so it
    is shown separately and never replaces dated demand evidence.
  - **Method:** one Tavily search for the company name. A result counts as the official site only
    when its registrable domain contains a distinctive token of the normalised name (code check).
    Then one search restricted to that domain for the client's `offer_terms`. The first pages are
    fetched through the run's PageFetcher (robots respected, replayable).
  - **Quotes:** code finds sentences naming an `offer_terms` word (stated fit) or a
    `related_terms` word (related fit). Each is a verbatim quote at an offset in the stored page
    text, so it is a verified claim by construction. A sentence must read as prose (6+ words, at
    most half capitalised), so menus and link lists never count.
  - **Effect:** a stated fit lifts the evidence level from generic mention or no evidence to
    "company fit". It never lifts it above project requirement or explicit purchase.
  - **Caps (settings):** `radar_fit_max_accounts` 5, `radar_fit_pages` 2, `radar_fit_quotes` 3.
    They are recorded shaping settings, so a replay uses the recorded values.
  - **Only a company's own claims count:** a claim whose subject is another organisation on the
    same page no longer counts toward an account (`entities._own_claims`).
  - **Recording:** the radar recorder now saves every page fetched (fit pages included), not
    only upgraded leads. The sensor-fixture recorder withholds natural-person names in TED
    notices before writing.
  - **Known weak spots:** sites are found, but stated fit is still rare; page selection needs
    work. Prefix matching of offer terms is loose ("tube" matches "tubing").
- **D97 — The run graph: the web of one saved run, served with no database.**
  `radar/graph.run_graph` and `GET /api/clients/{client}/runs/{day}/graph`.
  - **Why:** the demo API reads run records on disk (no database), and the frontend hero is the
    web itself. D88's `links` table stays the store for saved runs; this is the same picture
    built from a run record alone.
  - **Nodes:** companies, and one event node per source document (a run record keeps no
    procedure ids, so the document stands in for the buying process). Two companies quoted from
    the same document meet at the same event.
  - **Lines:** stated company -[its role]-> event, carrying that document's verified quotes; and
    inferred event -[likely_bidder]-> company, carrying the bidder's own verified award quote,
    with D88's confidence (wins / (wins + 1), capped at 0.9, now `bidder_confidence`).
  - **Never:** a line without a quote and URL, a quote that is not a claim of that document, or
    a node for a natural person (D76).
  - **Not yet:** company-fit lines (D96). No recorded run has a stated fit yet, and there is no
    node kind for the client's offer.
- **D98 — The design is locked (founder, 13 Oct).** `docs/design/final/`: the Station (dark and
  light), Leads with the case as a sheet, the case, Connections, and a clickable prototype on real
  run data. Tokens live in `docs/design/final/nv.css`.
  - **Look:** dark by default, warm off-white as the light mode, each designed rather than
    inverted. One signal colour (vermilion) that only means "a window is open". A serif for
    Northvaine's voice, a sans for the interface, mono for facts.
  - **Evidence marks everywhere:** solid = on record (a verified quote), hollow = inferred,
    dashed = not yet known.
  - **Editorial layer:** an edition per morning, datelines, headlines, pull quotes. Headlines are
    built from verified fields only; a model may phrase one only if code finds every name, number
    and date in the verified quotes. Judgement sits below the headline, marked as inferred.
  - **Interaction:** the Leads list shows each lead's type; a lead opens as a sheet over the list
    (↑/↓ to move, Esc to close); decisions are one tap and are the feedback. Motion is spring-based
    and quiet, and respects "reduce motion".
  - **Contacts:** company-level routes only (official site, the notice's procurement contact, the
    role to ask for). No personal emails or phone numbers of named people.
  - **Lead types are data, not code:** the list, filters and chain read the type from the lead,
    so a new kind of signal needs a registry entry and a chain template, not new screens.
- **D99 — Station shows only what the run records (14 Oct).** The built Station keeps the locked
  look (D98) but drops the mock's Team and Back-in-motion blocks: they need CRM and team data the
  product does not have yet, and a screen must not show invented records. In their place, "This
  edition" shows what the run read (documents → companies → set aside → on record).
  - **Map:** leads are placed by country, because that is the most precise place the record
    states. The view fits the countries with leads; with none, it shows the world and says how
    many leads state no country.
  - **Decisions:** at most four, most urgent first: act-now leads, tenders closing within 7 days,
    awards from the last 14 days, tenders closing within 14, then leads still to qualify by rank.
    One per project (co-winners are one decision). A "no" opens the case to ask for its reason.
  - **Masthead:** the newest award, else the most urgent decision, assembled from stated fields;
    the lede is counts and dates, never model text. "New" means not in the previous edition by
    company identity.
- **D100 — The learning loop runs from the saved answers, and says what each one changed
  (14 Oct).** Answers in the app were saved but never reached a run. Now
  `radar/lessons.py` turns the feedback file into the same labels as the database path (D89,
  D95), fits them, and a live run (`scripts/radar.py --record`) uses that strategy to choose its
  searches once `learning_min_labels` answers exist. Replays stay exact reproductions.
  - **"Not now" is timing:** relevant but not actionable now, with no failure reason, is
    `later`, which never moves a search's or a source's rate. This changes the D95 table.
  - **Each answer is explained** by fitting the beliefs without it and with it, and naming the
    largest real move ("I moved the search “…” down: 50% → 38%"; a wrong fact lowers trust in
    its source). If nothing moved, it says so. The page also shows how many answers remain
    before the answers choose the searches.
  - **Follow-ups:** after taking a lead, "What happened?" records the outcome (D95 fields); any
    quoted chain step can be flagged as a wrong fact. The latest answer per lead counts.
- **D101 — Buyer intent comes before more frontend (14 Oct).** A hand search for a
  design-partner exporter showed the radar finds public-works contractors but misses the buyers
  an exporter lives on (importers, distributors, merchants), and that a lead searched once is
  either too early or too late. The founder: "if we can't find real opportunities for the client
  continuously they won't pay us". The objective, in the founder's words: find who the client
  should target. Plan and lessons: `docs/BUYER_INTENT_PLAN.md`.
  - A per-client **buyer model** (data) decides who is a buyer; the gate uses it, so a
    distributor can be a buyer for one client and a competitor for another.
  - **Official import records** (UK HMRC, free and keyless) are the first source of proof of
    buying for exporter clients; a **company register** check removes hauliers and agents.
  - **Cases are watched across editions**, each naming the step it is waiting for, with two
    scores (potential and now) and states such as hold, too late and back in motion.
  - Every step is accepted only if a rerun matches the verified hand-made list kept in `.refs/`.
- **D102 — Official import records are a stream of their own: `trade` (14 Oct).** Step 1 of
  D101. A UK importer of the client's own product codes is a **proven buyer**: it buys the
  product, though nothing says from whom or whether it wants a new supplier.
  - **New generic event type `imports_recorded`** (SPEC §1 amended; seeded by migration 0007;
    code-only, so it is excluded from the extractor's list and recorded LLM replays are
    unchanged).
  - **New stream `trade`**, enumerable (the register lists every importer HMRC does not
    suppress). Role `importer_of_record`; new evidence level `proven_buyer`, ranked below
    `explicit_purchase` and above `project_requirement`. The record line naming the product
    code states the requirement, since the sensor only lists the client's codes.
  - **Status:** "qualify first" until the importer's own site names what the client sells
    (company fit, D96, now run for importers too), then "contact now". In the field test half
    the raw new importers were not buyers (a haulier, a machinery dealer).
  - **New importers lead:** half the sensor's slots (`hmrc_new_importer_share`) go to
    companies not recorded importing these codes last year, and they rank first among importers
    (BUYER_INTENT_PLAN lesson 5). Ranked by codes and months alone, 40 slots for the field-test
    codes were all established importers and the hand list's best lead was cut; with the share
    it is second.
  - **Sensor `hmrc`** (`api.uktradeinfo.com`, OGL v3.0): one document per importer per run,
    ranked (most requested codes, most months, new this year) and capped by `max_results`.
    **Company-level only:** a name without a legal form (`hmrc_company_markers`) may be a sole
    trader and is dropped before storage; only the postcode of the address is kept. HMRC's
    address for non-UK sellers is dropped.
  - **Availability:** a month counts as known 70 days after it ends (`hmrc_availability_lag_days`;
    July 2026 was public by 14 Oct). An estimate for the time machine, not an official calendar.
  - **Existing customers** (`ClientSpec.existing_customers`) are left out of the candidates
    before the gate; the run notes only a count.
- **D103 — The register check and the daily edition (16 Oct).** Step 1b of D101.
  - **Register check:** before the gate, UK candidates (proven importers first, at most
    `radar_register_max_lookups`) are looked up at Companies House by **exact** name (legal form
    and spacing ignored; no fuzzy matches). Their register lines become verified claims:
    - status;
    - incorporation date;
    - activity codes with official SIC 2007 descriptions (shipped as `core/data/sic2007.json`);
    - previous names;
    - controlling companies.
  - **Code rejections, before any model call:** a company that is not active, or whose
    activities are all in the client's `not_buyer_codes` (data per client, e.g. `sic:49410`).
    A code that is never a buyer for one client can be another client's customer.
  - **Company-level only:**
    - a controller is named only when it is a company;
    - for a person, only the date control was notified;
    - recordings strip individuals' details before they are saved.
  - **Runs only when the client has a buyer model and a key is set**, so other clients replay
    unchanged.
  - **Labels** (code only), on every entry:
    - *act now*: status "bid now" or "contact now";
    - *just changed*: set up within 18 months, or renamed or control changed within 12 months,
      or started importing this year;
    - *account to work*: a proven buyer with no fresh change.
  - **The daily edition:** up to 5 labelled entries in rank order, at most 1 act now,
    2 just changed and 2 accounts to work, never padded. Station's "To decide" shows it when
    present.
  - **HMRC lag lowered to 45 days:** August data was public on 15 Oct.
- **D104 — One free radar, then "talk to us" (16 Oct, founder).** For the hackathon there is no
  pricing page and no payment.
  - **Free limit:** one free radar build per email (`POST /api/trial`; a second claim is refused
    with 409). Emails the founder lists in `_subscribers.txt` are not limited.
  - **Talk to us:** `#/contact` sends a request (name, company, work email, website, what they
    sell) to `POST /api/contact`; a person replies. A hidden field drops simple bots.
  - **Storage:** JSON-lines files in the reports folder, never committed, like owner feedback.
    Hosting must give that folder persistent storage, or move these files and feedback to the
    database, before the public demo.
  - **After the hackathon:** pricing, payments and accounts (`docs/LATER.md`).
- **D105 — Onboarding: "Build my radar" (16 Oct, founder).** A new business builds its own radar
  in four steps at `#/onboarding`, without industry words in code.
  - **Start:** company, website and work email. This claims the one free radar (D104); a used
    email goes to "talk to us".
  - **Catalogue (optional, with Skip):** a PDF up to 25 MB, read for text. A catalogue under
    200 characters per page is flagged as mostly images.
  - **Suggested answers:** the website (Tavily search and extract, same site only) and the
    catalogue are cleaned (contacts and steering text removed), fenced as untrusted, and read
    by one model call. Code then keeps only what it can check:
    - product words must appear in the site or catalogue text;
    - markets must be ISO country codes;
    - HS and CPV codes must be well formed, and HS codes must exist in the UK tariff.
    Dropped items are shown to the person.
  - **The person confirms or edits the answers.** They become a client spec with generated
    queries: HMRC for GB with HS codes, Find a Tender for GB with CPV codes, TED for EU markets
    with CPV codes, and up to 6 Tavily searches.
  - **One live run at a time;** the page polls and opens the first edition when done.
  - **Storage:** session files in the reports folder, never committed (same hosting note as
    D104).
- **D106 — Lead quality comes into the hackathon (17 Oct, founder).** The automatic run found
  about 2 of the 13 buyers the WOS hand research found. Five improvements close that gap and are
  now in the hackathon plan, after Station and the case page:
  - **A. Company fit and contact:** Tavily reads each shortlisted company's own site to confirm
    it buys this kind of product, and takes the company email and phone from its contact page
    (company only, never a person).
  - **B. Customers like yours:** from the client's best customers, find companies with the same
    activity codes, imports and site words.
  - **C. Timing signals** (buyer-intent step 3), **D. watching over time** (step 2), **E. an
    investigating agent** for the top 10, with a budget; every fact is still a checked quote.
  - **Scoreboard:** the WOS catalogue run blind against the 13 buyers sent (target 8 or more).
    An improvement that does not raise the count is not kept.
  - **Cut order if late:** E, then C, then D. Hosting by 23 Oct and the demo path never move.
  - **F. Distributors** (added 17 Oct, founder): with "distributors" chosen at onboarding, the gate
    keeps companies that sell the client's kind of product without making it, as candidate
    partners ranked by evidence of size; the owner decides partner or competitor. After A and B;
    cut after C, D and E.

- **D107 — A wider import net, gated in parallel (18 Oct).** Replaying the WOS run showed that 7
  of the 12 UK buyers it missed were in the import records it had already downloaded (ranked 5th
  to 191st among 400 to 1,100 importers), but each search kept only its top 8 to 16. Import
  records are the strongest buying evidence and are read by code, so the fix comes before
  lead-quality A:
  - each import search keeps at least `hmrc_min_kept` (100) importers, half new this year;
  - the gate and the register check take up to 200 candidates (were 40);
  - candidates are gated `radar_gate_concurrency` (8) at a time; the budget check and the cost
    ledger take turns under a lock on the run, and outcomes keep the gate order, so the record is
    the same as a one-at-a-time run (tested). A run can overshoot its cap by at most the calls
    already in flight;
  - recordings made before this pin the old limits on replay (`LEGACY_SETTINGS`).
  Cost: about $0.0005 a gate call, so roughly $0.15 to $0.25 a run instead of $0.07.

- **D108 — Company fit moves the ranking, and the company's own contact (18 Oct).** On the WOS
  run, real buyers ranked 86th to 134th of 170 because proven importers fell back to recency.
  - Company fit is one Tavily search a company (its name plus up to 3 offer terms), not two; the
    pages read are the results on the company's own domain, plus its home page if needed.
  - 15 companies are checked (was 5): trade importers by import depth (product-code families,
    then months imported), then the other eligible entries by rank. Discovery uses about 4 Tavily
    calls and fit 15, so 19 of the 20 (`tavily_max_calls_per_run`).
  - Within an evidence level, stated fit now ranks first, related fit second, unchecked third,
    and "its site does not name what you sell" last; the reason is added to `rank_reasons`.
  - The company's own contact (company only, never a person): a role address (`info`, `sales`,
    ...) on its own domain and its first phone number, verbatim from its pages or `/contact`
    (one extra fetch). Shown on the case page with the page it came from.
  - Recordings made before this replay unchanged (`radar_fit_single_search` False, 5 accounts).

- **D109 — Customers like yours (19 Oct).** The client's current customers, and the leads it
  marks "Approach them" (`accepted_for_contact`), show what a good buyer looks like.
  - A candidate that shares a registered business activity (SIC code, from the free Companies
    House lookup of up to `radar_seed_max_lookups` = 10 of those names) or the same imported
    product families (from this run's import records) gets short `like_customers` reasons. An
    existing customer is never named; an approved lead may be.
  - Within an evidence level, likeness breaks ties after company fit, and it puts a candidate
    first in the company-fit check order. The reasons show on the case page.
  - The approved names a run used are recorded in the recording's meta, so replay is the same.
    Older recordings replay with no seed lookups (`radar_seed_max_lookups` pinned to 0).
  - No Tavily search and no model call is added.

- **D110 — Back in motion (20 Oct).** A company seen in an earlier run that now shows something new is the most actionable lead, so the brief compares a run with all the client's earlier runs (`radar/watch.py`, code only).
  - A change is: an event fingerprint no earlier entry had, a better evidence level than any earlier one, company fit that was absent before, or a daily-edition label it did not have. The API also adds "Now on record: {slot}" when a chain slot was unknown or inferred on the latest earlier entry and is stated now.
  - Only earlier runs strictly before this run's day and within `radar_watch_days` (90) count; at most `radar_watch_runs` (30) are loaded. A later run is never read, so the time machine stays honest.
  - Seen before with no change is only `returning`, which works as before. No model call, no search, no database.

- **D111 — Timing signals from free official records (20 Oct).** A proven buyer that is also changing right now is the one to call this week; two signals close together beat one.
  - New Companies House reads for UK companies already found, at most `radar_timing_max_lookups` (60) a run, trade importers first: `/charges` (only each charge's date and status) and the address filing history (only the date of the latest registered-office change). Never a name, an address or `persons_entitled`. A 404 means none; any other error is a note.
  - `radar/timing.py` (code only) lists signals dated within `radar_timing_days` (180) of the run day: charge registered, office moved, control changed, renamed, incorporated, started importing this year. Each is a short line with its date, on the candidate and shown on the case page.
  - Within an evidence level the order is fit group, then two or more signals before fewer, then likeness (D109). No model call, no Tavily search.
  - Older recordings replay unchanged: `radar_timing_max_lookups` is pinned to 0, which also leaves signals off.

- **D112 — Importers ranked by breadth, not by newness alone (20 Oct).** Among proven importers,
  every company new this year used to outrank every regular one, and a product-code count read an
  empty field, so a regular stockist importing five of the client's codes every month sat at
  117th (WOS live run). Now importers are ordered by how many of the client's own product codes
  they import, then months active; being new this year counts as two more codes. A new importer
  still leads one of the same breadth. Also: the site check always reads the company's contact
  page once its own site is found, so a replay matches the live run (the text that decided it is
  never recorded); and common business words ("solutions", "group") never identify a site.

- **D113 — Find a company's own site for free first (20 Oct).** One Tavily search per company, capped at 15, missed most sites (10 of 15 on the latest live run), and a confirmed own site is what lifts a proven buyer into the top 5.
  - Before searching, code guesses up to `radar_site_guess_per_company` (6) hosts from the registered name (distinctive words joined, first two, first alone, hyphenated; `.co.uk`/`.com`/`.uk` for GB, else `.com` and the country code) and fetches them through the run's PageFetcher (free, robots respected). It never guesses from words of the client's market or common business words.
  - A host is accepted only when its home page, or its `/contact` page, carries the company's registration number or its full registered name. The proof is kept (`site_proof`) and shown on the case page.
  - Up to `radar_site_guess_max_companies` (60) companies are tried, `radar_gate_concurrency` at a time. Tavily covers only the companies still without a site, within its cap. Run notes give counts only. No model call.
  - Older recordings replay unchanged: `radar_site_guess_max_companies` is pinned to 0.

- **D114 — Onboarding fills the client's non-buyer activity codes (21 Oct).** The register check (D103) was off for every client because nothing filled `not_buyer_codes`; a warehousing firm reached a test client's #7.
  - Onboarding offers three pre-ticked logistics roles (hauliers and forwarders including customs agents; warehousing and storage; cargo handling and port services). Each is a list of UK SIC 2007 codes in `northvaine/data/intermediary_roles.json`. The person unticks a role if those firms buy from them; the spec gets the codes of the ticked roles as `sic:<code>`. No model call.
  - Lead quality F (distributors, row 8b) and E (investigating agent, row 13) move to after the hackathon. WOS already counts distributors, and E enriches leads but does not find new ones. 21-22 Oct go to this, to linking companies across sources by registration number, and to lead quality on a second, non-stone client.

- **D115 — Link the same company across sources by its registration number (21 Oct).** The same company appears under different spellings in customs records, contract awards and news, so its events never met.
  - After the register lookups and before the gate, candidates with the same Companies House number become one (`merge_by_register`, code only): the trade candidate is primary (else the one with most claims), the others' names become aliases, their claims follow the primary's (refs renumbered, event refs remapped, shared register lines not repeated), events, streams, likeness and timing signals are unioned, and the window spans both. Every claim keeps its own document and verified quote.
  - Awards, tenders and announcements are looked up before trade importers under the lookup cap, so a contract winner is not left out by a long importer list.
  - Within an evidence level the order is fit group, then seen in two or more kinds of source, then timing (D111), then likeness (D109). The API gives `sources_seen`; the app shows a "2 SOURCES" tag and "Seen in" on the case page.
  - Older recordings replay unchanged: `radar_link_by_register` is pinned to False (no reorder, no merge, no ranking change). No model call, no search.

- **D116 — Distributors as a channel, done in the hackathon after all (21 Oct).** A manufacturer that sells through distributors was losing its best partners: the gate rejects every reseller of its kind of product.
  - `ClientSpec.channel` is `direct` (default, today's behaviour), `distributors` or `both`. With `distributors` or `both`, a candidate the model judges a `reseller` passes the gate as a possible distributor (`GateDecision.partner`, set by code after the verdict). Competitors, publishers and non-buyers are still rejected; end buyers still pass; the skeptic still runs. New onboarding asks "Who do you sell to?" and defaults to both.
  - Size, free: Companies House `accounts.last_accounts.type` (type of the last filed accounts, no figures) is kept as a verified register claim ("Accounts type: small"). Within an evidence level, possible distributors are ordered larger first as the last tie-break (dormant, micro, small or exempt, medium, full or group). The app shows a "Possible distributor" tag and a line asking the owner to decide partner or competitor.
  - No model call, no prompt change, no search. Older recordings replay unchanged: specs without `channel` read as `direct`, and `radar_register_accounts_type` is pinned to False.
