# Codex task cards (16 Oct 2026)

Rules: `AGENTS.md` (repo root). Claude reviews each branch and merges what passes. Give Codex one
card at a time. Cards are independent; none touches the engine.

---

## Card A: `landing` (frontend only)
**Goal:** the locked landing page inside the app as its home screen.
- Port `docs/design/final/landing.html` (locked design, D98) into `frontend/src/` as a React page.
  Keep its look and copy exactly; reuse the tokens in `frontend/src/nv/nv.css` (dark and light).
- Route: `#/` shows the landing page. Its primary button links to `#/onboarding`; a secondary
  "See a live example" links to `#/app/coldchain_maker/latest`. The current clients list moves to
  `#/clients` (keep it working).
- `#/onboarding`: a simple placeholder screen that says onboarding is coming, with a link back.
  No backend calls.
- The `#intro` replay in the design file must still work.
- Allowed files: `frontend/src/**` only.
- Done: typecheck and build pass; old links (`#/c/...`, `#/m/...`, `#/app/...`) still open.

Result:

---

## Card B: `sidebar` (frontend only)
**Goal:** the app frame matches the locked design without dead links.
- In `frontend/src/nv/Shell.tsx`, show the full sidebar from `docs/design/final/station.html`
  (Station, Decisions, Situations, Back in motion, Accounts, Territory, Connections, Editions,
  Outcomes, What I've learned, Your business). Station and Leads stay working; every other item
  is visibly disabled with a small "Soon" tag and is not clickable.
- Allowed files: `frontend/src/nv/Shell.tsx`, `frontend/src/nv/nv.css`.
- Done: typecheck and build pass; keyboard focus never lands on a disabled item.

Result:

---

## Card C: `readme` (docs only)
**Goal:** a submission-ready README draft.
- Rewrite `README.md`: what Northvaine does (one paragraph), who it is for, how a lead is found
  (five steps), setup (`uv run python scripts/tasks.py setup`, `dev`, `test`, `gate`), and a
  section "Where Nemotron, Token Factory and Tavily are used" pointing to the real files
  (`northvaine/brain/llm.py`, `northvaine/radar/gate.py`, `northvaine/radar/court.py` or the
  skeptic module, `northvaine/sensors/tavily.py`, `northvaine/radar/fit.py`). Read the code to
  confirm each claim; never describe anything that is not built.
- Add an empty "Feedback on Nebius, Token Factory and NVIDIA tools" section with headings only.
- Allowed files: `README.md`.
- Done: every file path in the README exists; no client names; no secrets.

Result:

---

## Card D: `secrets-scan` (report only)
**Goal:** know whether the git history is safe to make public.
- Scan the full git history (all branches) for secrets and personal data: API keys, tokens,
  passwords, connection strings, private emails and phone numbers, real client names from
  `.refs/` (do not open `.refs/`; instead flag any company or person name that appears in
  committed specs or fixtures for Claude to judge).
- Use only tools already installed (git, ripgrep, Python stdlib). Do not install scanners.
- Write findings to `docs/SECURITY_SCAN.md`: commit, file, line, kind. Mask every value
  (first 4 characters, then `…`). Do not rewrite history.
- Allowed files: `docs/SECURITY_SCAN.md`.

Result:

---

## Card E: `format` (mechanical)
**Goal:** `ruff format --check` passes on the whole repo.
- Run `uv run ruff format` on exactly these files, nothing else: `scripts/gate.py`,
  `scripts/smoke_llm.py`, `tests/brain/test_budget.py`, `tests/core/test_db.py`,
  `tests/core/test_migration_0003_offline.py`, `tests/core/test_queue.py`, `tests/db/conftest.py`,
  `tests/db/test_budget_db.py`, `tests/db/test_queue_db.py`, `tests/scripts/test_gate.py`.
- Formatting changes only; no edits by hand.
- Done: `uv run python scripts/tasks.py lint` passes and the gate passes.

Result:

---

## Card F: `docker` (deploy prep, no deploy)
**Goal:** a container that runs the API and serves the built frontend, ready for Nebius.
- Write `Dockerfile` and `.dockerignore` following `docs/DEPLOY.md` (Python 3.12, `uv sync
  --frozen`, build the frontend, serve it with the API). Environment variables by name only; no
  values, no `.env` copied into the image (`.dockerignore` must exclude `.env`, `.refs/`,
  `reports/`).
- Do not build or push to any registry and do not create cloud resources.
- Allowed files: `Dockerfile`, `.dockerignore`, and a short "Container" section appended to
  `docs/DEPLOY.md`.
- Done: the files exist and are consistent with `docs/DEPLOY.md`; note any assumption.

Result:
