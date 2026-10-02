# Northvaine — How to start and run the project with the agent factory

This guide is for the founder: what you do, what the agents do, and what to do when something
goes wrong. The rules themselves are in `docs/FACTORY.md`; this is the practical walkthrough.

---

## 1. The picture in one minute

You talk to **one** Claude Code session, the **orchestrator**. You never manage agents
directly. The orchestrator runs two workflows that spin up specialist agents:

```
YOU ──"plan milestone 1"──▶ ORCHESTRATOR ──runs──▶ factory-plan
                                                    ├─ Architect: drafts tickets + contracts
                                                    ├─ Researchers (parallel): confirm API facts from docs
                                                    ├─ Reviewer: critiques the plan
                                                    └─ Architect: writes factory/board/M1/
YOU ◀── plan + questions ── ORCHESTRATOR
YOU ──"approved" (or changes)──▶ ORCHESTRATOR marks tickets approved, commits
YOU ──"build milestone 1"──▶ ORCHESTRATOR ──runs──▶ factory-build
                                                    for each wave (0 = contracts, then 1, 2 …):
                                                    ├─ Builder per ticket (parallel, own git worktree)
                                                    ├─ Reviewer per ticket → up to 2 fix rounds
                                                    └─ Integrator: merges into main, runs gate
                                                    └─ Reviewer: verifies the whole milestone
YOU ◀── report: merged, blocked, questions ── ORCHESTRATOR
```

Two moments need you, every milestone: **approving the plan**, and **answering questions**
(spec changes, credentials, anything public or paid). Everything else is automatic.

---

## 2. One-time setup

### 2.1 Tools (already on this machine unless marked)
| Tool | Status | Why |
|---|---|---|
| git | installed | worktrees for parallel builders |
| uv | installed | Python envs and packages; installs Python 3.12 itself |
| Node 22 | installed | frontend (milestone 13) |
| Postgres + pgvector | **missing** | decided in the milestone 1 plan (hosted vs local) |
| make, Docker | missing | not required; every task runs via `uv run` |

### 2.2 Accounts and keys (you create these; agents never do)
| Key | Where from | Needed by |
|---|---|---|
| `NEBIUS_API_KEY` | Nebius Token Factory console | milestone 2 (`llm.py`) |
| `TAVILY_API_KEY` | tavily.com dashboard | milestone 3 (sensors) |
| `DATABASE_URL` | your Postgres choice | milestone 1 (migrations) |
| TED API | public; no key for search (researcher will confirm) | milestone 3 |

Put them in `D:\hack\.env` (copy `.env.example`). `.env` is git-ignored, and the gate scans
for leaked secrets. **Never paste keys into chat or into tickets.**

### 2.3 Check the factory works
```powershell
cd D:\hack
uv run python scripts/check_invariants.py   # should print 0 violations
uv run python scripts/gate.py               # once milestone 1 lands, should print GATE PASSED
```

---

## 3. The milestone loop (what you actually do)

### Step 1: Ask for a plan
Say: **"plan milestone 2"** (add notes if you want, e.g. "use Nemotron Super for the gate").
The orchestrator runs `factory-plan`. This takes ~10–20 minutes; watch it with `/workflows`.

### Step 2: Read the plan
Open `factory/board/M2/PLAN.md` and skim the ticket files next to it. Check:
- **Goal:** does it deliver the milestone in `docs/MILESTONES.md`?
- **Waves:** wave 0 = contracts (shared interfaces); later waves build on them.
- **Tickets:** each has `writes:` (the only files it may touch) and testable acceptance
  criteria.
- **Research:** `docs/integrations/*.md` has the confirmed API facts. Anything marked
  *unconfirmed* is a risk.
- **Questions for founder:** answer these.

### Step 3: Approve or redirect
- **"approved"**: the orchestrator sets the tickets to `status: approved` and commits.
- **"approve all except T2.4"** or **"change T2.3 to …"**: the orchestrator edits, or re-runs
  the plan.
- **Answers to questions** become entries in `docs/DECISIONS.md`.

### Step 4: Build
Say: **"build milestone 2"**. The orchestrator runs `factory-build`. For a milestone of ~6
tickets expect ~30–90 minutes and ~20 agent runs. You can keep talking to the orchestrator
while it runs.

### Step 5: Read the report
`factory/reports/M2.md`: what merged, what's blocked and why, gate output, unmet criteria,
follow-ups. The orchestrator summarizes it and asks you anything it needs.

### Step 6: Retro (2 minutes)
The orchestrator updates `DECISIONS.md`, parks new ideas in `LATER.md`, and notes what the
next milestone should know. Then: "plan milestone 3".

---

## 4. What each agent does, step by step

### Architect (planning)
1. Reads ARCHITECTURE, MILESTONES, SPEC sections, schema, DECISIONS, the current code, and
   earlier reports.
2. Splits the milestone into waves:
   - **wave 0** is the *contracts*: Pydantic models, function signatures, DB tables,
     settings, written as real code with stub bodies and contract tests.
   - later waves implement against those contracts.
3. Gives every ticket a disjoint `writes:` list, so parallel builders can't collide.
4. Lists every external fact it relies on, for the researchers.

### Researcher
- One per external topic (e.g. "Nebius Token Factory models", "TED search API").
- Reads official docs only and writes `docs/integrations/<topic>.md`: facts, source URLs,
  dates, examples, limits.
- If something needs your API key to confirm (e.g. listing model ids), it gives you the
  exact command instead of guessing.

### Builder / test engineer
1. Starts in a **fresh git worktree** (its own copy of the repo, its own branch), so ten can
   run at once without touching each other or `main`.
2. Reads its ticket and contracts, writes tests from the acceptance criteria, then code.
3. May only change the paths in `writes:`. If it needs more, it files a *contract change
   request* instead of improvising.
4. Runs the gate until green, commits on its branch, and reports (branch, commit, files,
   tests, questions).

### Reviewer
1. Reads the builder's diff (`git diff main...branch`) and runs the tests and the gate in that
   worktree.
2. Checks acceptance, scope, invariants (sources, untrusted text, no industry words, LLM
   calls only through `llm.py`, no network in tests, no secrets), correctness and simplicity.
3. Approves, or sends findings back. The builder gets up to **2 fix rounds**; after that the
   ticket is *blocked* and comes to you.

### Integrator
1. Works only in the main checkout. Merges approved branches in order.
2. Runs the gate after **every** merge. If a merge breaks `main`, it undoes just that merge
   and blocks the ticket.
3. Resolves only mechanical conflicts (imports, lists). Real disagreements are blocked and
   escalated.
4. Removes merged worktrees and marks tickets `done`.

### Orchestrator (the main session)
- Runs the workflows, keeps `main` committed before builds, relays questions, records
  decisions.
- Doesn't write feature code during a build.

---

## 5. Where to look

| You want to know… | Look at |
|---|---|
| What's planned / its status | `factory/board/M<n>/` (status in each ticket's header) |
| What happened in a build | `factory/reports/M<n>.md` |
| Live progress | `/workflows` in Claude Code |
| Confirmed API facts | `docs/integrations/` |
| Why something changed from the spec | `docs/DECISIONS.md` |
| Ideas we parked | `docs/LATER.md` |
| The design | `docs/ARCHITECTURE.md` |
| The factory rules | `docs/FACTORY.md` |
| The code history | `git log --oneline --graph` |

---

## 6. When things go wrong

| Situation | What happens | What you say |
|---|---|---|
| A ticket is **blocked** (failed review twice, missing fact, conflict) | the others still merge; reason in the report | "re-plan T2.3", "build only T2.3 again", or answer its question |
| A builder needs a **contract change** | listed in the report; nothing changed silently | "accept the change" (architect updates the contract) or "no, do X" |
| **Main's gate is red** after a wave | the build stops before the next wave | "fix main" (orchestrator runs a single fix ticket) |
| A workflow **crashed or was stopped** | finished agents are cached | "resume the build". Completed steps are not repeated |
| You dislike something that already **merged** | — | "revert T2.3". It's a normal git revert on `main`, with a new ticket for the redo |
| An **external API changed** | tests use recorded fixtures, so they stay green; the live smoke script fails | "re-research <topic>" |
| You want to **rebuild one ticket** | — | "build milestone 2 only T2.3" (runs with `only: ["T2.3"]`) |

---

## 7. House rules for you

1. **Don't edit files in `D:\hack` while a build is running.** The integrator needs a clean
   `main`. Edit between milestones, or ask the orchestrator to make your change as a ticket.
2. **Keys only in `.env`.** Never in chat, tickets, fixtures or commits.
3. **New ideas mid-milestone go in `LATER.md`.** Say "park this: …". Scope stays frozen until
   the milestone ends.
4. **Anything public is your call:** deploy, push to GitHub, the demo URL, the video. Agents
   never do these without you saying so.

---

## 8. Starting right now (milestone 1)

1. ✅ Repo, factory, gate and docs are committed (`e141b6d`).
2. ⏳ `factory-plan` for milestone 1 is running. When it finishes, you get the plan and its
   questions (including where Postgres should run).
3. You: read `factory/board/M1/PLAN.md`, answer the questions, say "approved".
4. You: create the Postgres database you chose and put `DATABASE_URL` in `.env`.
5. You: "build milestone 1". At the end you'll have a working skeleton with migrations, the
   job queue, settings, and a green gate.
6. Before milestone 2: create your Nebius Token Factory key and put it in `.env`. The
   researcher will need it to confirm the real Nemotron model ids.

### Cheat sheet
| Say | Does |
|---|---|
| `plan milestone N` | runs factory-plan → board + questions |
| `approved` / `approve all except …` | marks tickets approved, commits |
| `build milestone N` | runs factory-build → merged code + report |
| `build milestone N only T…` | rebuilds specific tickets |
| `resume the build` | continues a stopped workflow from cache |
| `status` | summary of board + latest report |
| `park this: …` | adds to LATER.md |
| `revert T…` | undoes a merged ticket on main |
