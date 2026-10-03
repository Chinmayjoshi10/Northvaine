# The Northvaine Software Factory

How this project is built by a team of Claude Code subagents working in harmony.
The human (founder) is the product owner. The main Claude session is the **orchestrator**.

```
 founder ──approves──▶ PLAN ──▶ CONTRACTS ──▶ BUILD (parallel, isolated) ──▶ REVIEW ──▶ INTEGRATE ──▶ VERIFY
                        ▲                                                                              │
                        └────────────── reports, decisions, board state, retro ◀──────────────────────┘
```

## 1. Roles

Role definitions live in `.claude/agents/`. Each agent reads only what its role needs.

| Role | File | Does | Never does |
|---|---|---|---|
| Orchestrator | (main session) | runs workflows, talks to the founder, owns `main`, approves merges | writes feature code itself during a build |
| Architect | `architect.md` | turns a milestone into contracts + tickets with disjoint write scopes | writes implementation code |
| Researcher | `researcher.md` | confirms external facts (APIs, model ids, limits) from official docs, with URLs | guesses; writes code |
| Builder | `builder.md` | implements one ticket in its own git worktree, with tests | edits outside its ticket's `writes`; changes contracts |
| Test engineer | `test-engineer.md` | fixtures, golden cases, replay checks, contract tests | weakens a test to make it pass |
| Reviewer | `reviewer.md` | checks a ticket's diff against acceptance, invariants, architecture | fixes code (it reports; the builder fixes) |
| Integrator | `integrator.md` | merges approved branches in order, runs the gate, resolves trivial conflicts | merges red builds; resolves design conflicts alone |

## 2. The rules of harmony

1. **One source of truth.** Work exists only as tickets in `factory/board/M<n>/`. Status lives
   in the ticket file. Nothing is built that has no ticket.
2. **Contracts before code.** Each milestone's first wave lands the shared interfaces
   (Pydantic models, protocols, function signatures, DB tables, fixtures format). They are then
   **frozen** for the milestone. A builder who needs a change files a *contract change request*
   in its report; the architect decides; the orchestrator asks the founder if it changes the
   spec.
3. **Disjoint ownership.** Every ticket lists the paths it may write (`writes:`). Tickets in the
   same wave never share a write path. Shared files (`pyproject.toml`, `schema.sql`, migrations,
   `core/models.py`) belong to the contracts ticket or the integrator.
4. **Isolation.** Each builder works in its own git worktree on its own branch. `main` only
   changes through the integrator.
5. **Small tickets.** One concern, reviewable in one sitting (aim < 400 changed lines).
6. **Tests travel with code.** No network in tests; fixtures in `tests/fixtures/`. Live checks
   are scripts or `@pytest.mark.live`, never in the default run.
7. **Facts, not guesses.** External API shapes, model ids and limits come from the researcher's
   notes in `docs/integrations/`, each with a source URL and the date checked.
8. **Escalate, don't improvise.** Spec questions, contract changes, and anything outward-facing
   (deploy, push, sending, paid services) go back to the orchestrator → founder.
9. **Acceptance must be satisfiable inside the ticket.** Every acceptance criterion must be
   reachable using only that ticket's `writes:` paths, **against the tests already on `main`**.
   A criterion that needs a file another ticket owns is a planning defect, not a build problem:
   the builder cannot fix it and the gate can never go green. The architect checks this before
   the board is saved; the orchestrator checks it before flipping tickets to `approved`.
   **Whoever changes a shared artefact owns every test that asserts it.** Change `schema.sql`
   or a migration, and every test file asserting the old DDL joins your `writes:`. The
   mechanical check, before approving a board: check out the branch, run
   `pytest -m "not live and not db"`, and confirm every failure is in a file the ticket owns.
   Cost of skipping it, twice on 3 Oct: T2.0 added four `LlmCallRow` fields whose columns lived
   in T2.1a's `schema.sql`; then, after that was fixed, 0003 sized the vector columns while two
   M1 test files still asserted they were dimensionless and no M2 ticket owned them. Both times
   all eight tickets blocked, ~16 minutes each. The prose version of this rule was written after
   the first failure and did not prevent the second - only running the suite does.
10. **Leave a trail.** Every agent ends with a structured report saved in `factory/reports/`.
   Decisions that change the spec go in `docs/DECISIONS.md`.

## 3. Definition of done (per ticket)

- [ ] Every acceptance criterion in the ticket is met and shown by a test or a command.
- [ ] Only paths in `writes:` changed.
- [ ] `uv run python scripts/gate.py` passes in the worktree.
- [ ] Reviewer verdict: approve.
- [ ] Report written; ticket status set to `done`.

## 4. The gate (`scripts/gate.py`)

Runs, in order, and fails on the first red step:
1. `scripts/check_invariants.py`: no industry words in code, LLM SDKs only in `brain/llm.py`,
   network clients only in `sensors/` and `brain/llm.py`, no sending libraries, no secrets.
2. Lint (`ruff check`).
3. Unit tests (`pytest -m "not live"`).
4. Golden set (once `tests/golden/` exists).
5. Frontend build (once `frontend/package.json` exists).

## 5. Lifecycle of a milestone

| Step | Who | Output | Human gate |
|---|---|---|---|
| 1. Plan | Workflow `factory-plan` (architect → researchers → architect → reviewer critique → architect) | `factory/board/M<n>/PLAN.md` + ticket files, all `status: proposed` | **Founder approves the plan** |
| 2. Approve | Orchestrator | tickets → `status: approved` | — |
| 3. Build | Workflow `factory-build` (waves by dependency; per ticket: builder → reviewer → fix ≤ 2 rounds; per wave: integrator) | merged commits on `main`, reports | — |
| 4. Verify | Final reviewer pass + gate + demo path | `factory/reports/M<n>.md` | Founder sees the summary |
| 5. Retro | Orchestrator | DECISIONS, LATER, next milestone notes | — |

Blocked tickets don't stop the wave. They are reported, and the orchestrator decides with the
founder.

## 6. Ticket format

See `factory/templates/ticket.md`. Key fields: `id`, `title`, `role`, `wave`, `depends_on`,
`writes`, `reads`, `acceptance`, `status` (proposed → approved → in_progress → review → done |
blocked).

## 7. Running it

- Plan a milestone: ask the orchestrator "plan milestone N". It runs the `factory-plan` workflow
  with `{milestone: N}`.
- Build it: after approving, "build milestone N". It runs `factory-build` with `{milestone: N}`.
- Progress: `/workflows` in Claude Code.
- Models per role (lean mode): architect = Opus; reviewer = Opus for contract tickets (wave 0) and the milestone check, Sonnet for other tickets; builder, test engineer, researcher, integrator = Sonnet; board loader = Haiku. Research only for external facts new to the milestone; aim for 4-7 tickets per milestone. Start each milestone in a fresh session so the orchestrator context stays small. Override any role with `args.models`, e.g. `{reviewer: "opus"}`.
