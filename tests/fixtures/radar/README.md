# Radar recordings

One folder per client: a radar run recorded once from the live sources, replayed offline forever
(D65). Nothing here is written by hand, and nothing here is recorded by a builder: only the
orchestrator has `.env` and the network.

## Layout

```
tests/fixtures/radar/<client>/
  meta.json   client id, as_of (the run date), recorded_at, the date-shifted queries that were sent
  http.json   sensor HTTP exchanges (TED, Tavily): a list of RecordedExchange, in request order
  pages.json  one UpgradedPage per lead that was fetched or refused, keyed by lead_url
  llm.json    model exchanges (extract, support, embed, gate, skeptic): an LlmRecording
```

`<client>` is a file stem in `tests/fixtures/clients/`. The same four files exist for every client.

## Commands

```
uv run python scripts/tasks.py radar -- --client stone_supplier                  # replay (default)
uv run python scripts/tasks.py record-radar -- --client stone_supplier           # prints the plan
uv run python scripts/tasks.py record-radar -- --client stone_supplier --yes     # records (spends)
```

Replay needs no `.env` and no network, and writes `brief.md`, `scorecard.md` and `run.json` under
`reports/radar/<client>/<date>/` (gitignored, D66). Re-running it gives byte-identical files.
A missing recording exits with code 2 and says to record it.

## Who records

The orchestrator only, once per client (Recording R), then re-records whenever a prompt, a
setting that shapes a request, or a client's queries change: any such change makes the recording
stale, and replay fails loudly (`LlmReplayMismatch`, `ReplayMismatch`, or "spec no longer matches")
instead of skipping. Recording needs `DAILY_BUDGET_USD`, `TOTAL_BUDGET_USD`, `MODEL_FAST`,
`MODEL_MID`, `MODEL_EMBED`, `TAVILY_API_KEY` (when the client has Tavily queries) and `--yes`.

## Redaction rules

- HTTP: the sensor recorder's rules (`scripts/record_sensor_fixtures.py`): no auth header or key,
  contact-like keys dropped, TED `links` stripped, Tavily `request_id` removed.
- Pages: contacts are stripped by `strip_contacts` before a page becomes text (D59).
- Model exchanges: `smoke_llm.redact` over every response; a request that redaction would change
  is refused, never rewritten (its key is the hash of the exact request).
- The recorder refuses to write any file if an email address, a phone number or a secret-shaped
  value survives anywhere in the recording.
- After recording, read every page and the brief by eye (sole traders, bylines, staff names)
  before committing. The reports are never committed.

## Never hand-edit

Editing a recording by hand breaks the hash keys and hides a real bug. Record it again.
