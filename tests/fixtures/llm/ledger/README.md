# Recorded evidence-ledger LLM calls

One file per sample client (`<client>.json`, named after `tests/fixtures/clients/`) plus `web.json`
for the website fixtures in `tests/fixtures/web/`. They hold the real model calls the evidence
ledger makes (extraction, support check, embeddings), so tests replay them offline for free.

**Recording is an orchestrator-only step.** It needs `.env`, the network and a database at head
0005, and it spends money (an upper bound is printed first):

```
uv run python scripts/tasks.py record-llm                 # print the plan, call nothing
uv run python scripts/tasks.py record-llm -- --yes        # record (add --client <id> for one)
```

Builders and test engineers never record. Nothing here is hand-written or hand-edited.

## Format

Each file is an `LlmRecording` (`northvaine/brain/replay.py`):

| field | meaning |
|---|---|
| `recorded_at` | UTC time of the run |
| `models` | tier -> model id used (`fast`, `mid`, `deep`, `embed`) |
| `settings` | the settings that shape requests (`extract_max_tokens`, `support_max_tokens`, ...) |
| `exchanges` | list of `LlmExchange`: `kind` (`chat` or `embed`), `key`, `prompt_version`, `request`, `response` |

`request` is the exact body sent, with fence nonces replaced by `<NONCE>`. `response` keeps only
what `llm.py` reads: `choices[0].message.content`, `finish_reason`, `usage`, and for embeddings
`data[0].embedding`. Vectors are rounded to 6 decimals. Retries made by `complete_json` (the
repair prompt carries the validation error) are separate exchanges and replay like any other.

## The key rule

`key` = sha256 of the canonical JSON (sorted keys, no whitespace) of `kind` and the normalized
request body. The same prompt and variables give the same key on every render, because the
per-call fence nonce is normalized away. Any other change gives a different key: one character in
a variable, a prompt edit, `max_tokens`, the model id.

**A prompt or max_tokens change invalidates its recordings: re-record, never hand-edit.** A replay
miss raises `LlmReplayMismatch` naming the key and (when known) the prompt version; it never falls
back to the network.

## Using a recording in a test

```python
from northvaine.brain import llm
from northvaine.brain.replay import ReplayClient, load_recording, replay_environment

recording = load_recording("tests/fixtures/llm/ledger/web.json")
with replay_environment(recording), llm.client_override(ReplayClient(recording)):
    ...  # call radar.ledger.build_evidence(...), llm.complete_json(...), llm.embed(...)
```

`replay_environment` makes the test independent of `.env` and the shell: it sets `MODEL_FAST`,
`MODEL_MID`, `MODEL_DEEP` and `MODEL_EMBED` to the recorded ids (tiers the recording does not use
are left alone), pins the recorded `settings`, sets the four budget caps high enough for any
recording, clears the `get_settings` cache, and restores everything on exit, also after an
exception. The budget guard and the `llm_calls` row per attempt still run: only the client behind
`llm.py` is swapped (CLAUDE.md #8). No `NEBIUS_*` value is needed.

## Redaction

Before writing, every recording goes through `scripts/smoke_llm.redact`. The recorder refuses to
write anything (all files, none partially) if a request would be changed by redaction, or if a
secret-shaped value, email address or phone number survives anywhere. Source text is also checked
before any money is spent. Read each new recording by eye before committing.
