# Northvaine — Milestones (v2, follows docs/ARCHITECTURE.md §22)

Each milestone is planned with `factory-plan`, approved by the founder, then built with
`factory-build` (docs/FACTORY.md). After every milestone: the gate passes and the demo path
still works.

## Week 1 (to 8 Oct) — substrate
1. Skeleton (fix the existing partial one): settings, DB engine, schema with ARCHITECTURE §21
   changes via Alembic, Pydantic models, jobs queue, task runner usable on Windows, gate green.
2. `brain/llm.py`: Token Factory client, model routing, validated JSON, retries, budgets,
   `llm_calls` logging. Model ids confirmed, not guessed. One live smoke script (not pytest).
   **De-risk deployment now:** Postgres + pgvector where the demo will run.
3. Sensors with `available_at`: safe fetch, Tavily, website snapshot, and official registries
   and tender sources (researched first, chosen by sample-client geography: e.g. Companies House,
   SEC EDGAR, TED, Find a Tender / Contracts Finder, SAM.gov); fixtures + tests.
4. Evidence ledger (claims + code quote check + LLM support check); event normalization, seed
   concepts, clustering.
5. **First radar (multi-client):** a rough end-to-end slice (discover → filter → extract →
   verify → buyer-or-seller gate → brief) for 2–3 very different sample clients, about 10
   candidates each with sources. The founder rates them. This is the go/no-go on core quality
   before the learners.
6. Point-in-time timeline builder, pattern DSL evaluator, decision log (with propensities),
   and the **project graph**: `projects` + `relationships` (organisation, role such as
   client, contractor, designer or supplier, project or other organisation, since, source
   claim), so the radar can follow funding → design → tender → contractor (the buyer).

## Week 2 (to 15 Oct) — learners, first pass  (milestone 6 may start in week 2)
7. World-state learner: dynamics on TED/news (concept → proxy lift, lag densities), expectations.
8. Org-context learner: belief slots, VOI questions, "which of these 8?" onboarding chat.
9. Buying-pattern learner: LLM priors, case-control with controls, proxy chain, ledger behind
   its interface.
10. Replay harness + simulated owner + golden set.

## Week 3 (to 22 Oct) — learning changes behaviour
11. Research policy + attention allocator: search programs from patterns, value-per-cost
    allocation, watches, investigation VOI, query-template evolution.
12. Feedback chips (+ "already knew?") → routed updates → behaviour change → lessons →
    strategy versions + rollback.
13. Missed-opportunity post-mortems.
14. Frontend: Today (net-new reach), Case file, Setup chat, What I learned.

## Week 4 (to 30 Oct) — Gateway-lite + ship
15. Gateway-lite: JSON-LD, catalog, agent card, read-only MCP, receptionist + red-team set.
16. Deploy (Nebius); README; licence; secrets scan of history.
17. 3-minute video; submit by 29 Oct.
