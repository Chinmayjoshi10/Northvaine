---
id: T1.2
title: Short imperative title
milestone: 1
role: builder            # builder | test-engineer | researcher
lane: backend            # backend | frontend | data | infra
wave: 1                  # 0 = contracts
depends_on: [T1.1]
writes:                  # the ONLY paths this ticket may change (files or dirs)
  - northvaine/brain/llm.py
  - tests/brain/test_llm.py
reads:                   # what the builder must read first
  - docs/ARCHITECTURE.md#20
  - northvaine/core/models.py
status: proposed         # proposed | approved | in_progress | review | done | blocked
---

## Goal
One paragraph: what this ticket delivers and why it matters for the milestone.

## Contract
The interfaces this ticket implements or relies on (names, signatures, models). Contracts are
frozen for the milestone; changes go through a contract change request.

## Acceptance criteria
- [ ] Each criterion is observable and proven by a named test or command.

## Invariants touched
Which rules from CLAUDE.md / ARCHITECTURE §3.1 apply here and how the ticket keeps them.

## Notes
Edge cases, pitfalls, links to `docs/integrations/`.
