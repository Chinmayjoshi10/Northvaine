# Recorded LLM fixtures

Written by `uv run python scripts/tasks.py smoke -- --yes` (scripts/smoke_llm.py), the one code
path in this repository that spends money. One sub-cent run buys the responses every later
milestone replays offline for free.

**Nothing here is hand-written.** A fixture that was not recorded from the live API is worse
than no fixture: it encodes a guess about the response shape, and the tests that replay it then
pass against a shape the API never produces. That exact failure is why T2.5 was split - see
`factory/board/M2/PLAN.md`, "Why the T2.5 split matters".

## Files

| File | Written by | Contains |
|---|---|---|
| `list_models.json` | `llm.list_models()` | every model id the catalog served, and when |
| `complete_json.json` | `llm.complete_json()` | request body + validated value, usage, model |
| `embed.json` | `llm.embed()` | model, dimensions, usage, vector length and first 8 floats |

Each file carries `recorded_at` (UTC). The vector itself is stored head-only: 1024 floats would
dominate the diff of every later change for no test value.

## Redaction

Everything is passed through `scripts/smoke_llm.redact()` before being written. It removes:

- any value under a key that names a credential (`authorization`, `api_key`, `token`,
  `account_id`, ...);
- any literal known secret - the API key and both database URLs - wherever it appears, including
  inside a URL or a nested body field;
- anything *shaped* like a key (`nvapi-...`, `sk-...`, a JWT), even if unrecognised.

That last rule makes the helper fail closed: these files go to a public repository, so an
unknown credential format must still be caught. `tests/brain/test_smoke_redaction.py` proves all
three paths offline against synthetic payloads.

**Before committing a new fixture, read it.** The redaction is tested, but a human check costs
seconds and the hackathon checklist requires no secrets in the repo or its history.
