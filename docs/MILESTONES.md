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
3. Sensors with `available_at`: safe fetch, TED, Tavily, website snapshot; fixtures + tests.
4. Evidence ledger (claims + code quote check + LLM support check); event normalization, seed
   concepts, clustering.
5. Point-in-time timeline builder, pattern DSL evaluator, decision log (with propensities).

## Week 2 (to 15 Oct) — learners, first pass
6. World-state learner: dynamics on TED/news (concept → proxy lift, lag densities), expectations.
7. Org-context learner: belief slots, VOI questions, "which of these 8?" onboarding chat.
8. Buying-pattern learner: LLM priors, case-control with controls, proxy chain, ledger behind
   its interface.
9. Replay harness + simulated owner + golden set.

## Week 3 (to 22 Oct) — learning changes behaviour
10. Research policy + attention allocator: search programs from patterns, value-per-cost
    allocation, watches, investigation VOI, query-template evolution.
11. Feedback chips (+ "already knew?") → routed updates → behaviour change → lessons →
    strategy versions + rollback.
12. Missed-opportunity post-mortems.
13. Frontend: Today (net-new reach), Case file, Setup chat, What I learned.

## Week 4 (to 30 Oct) — Gateway-lite + ship
14. Gateway-lite: JSON-LD, catalog, agent card, read-only MCP, receptionist + red-team set.
15. Deploy (Nebius); README; licence; secrets scan of history.
16. 3-minute video; submit by 29 Oct.
