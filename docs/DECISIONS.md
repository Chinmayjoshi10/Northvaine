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
