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
