# NVIDIA Nemotron model ids, limits and prices on Nebius Token Factory

Date checked: 2026-10-03
Researcher note: no `NEBIUS_API_KEY` was available in this environment, so nothing here was
confirmed against the live `GET /v1/models` endpoint. Everything below comes from Nebius's own
public catalog page and site, cross-checked against two independent third-party aggregators.
Treat model ids and prices as high-confidence; treat max-output-token and minimum-charge answers
as **unconfirmed** and verify live before relying on them (command given in Open Questions).

## Summary

Nebius Token Factory serves four NVIDIA Nemotron chat/completions models today. Two of them —
**Nemotron-3-Nano-30B-A3B** and **Nemotron-3.5-Lightning** — are tied for the lowest per-token
price, both at $0.06 / 1M input and $0.24 / 1M output tokens. Pick between them by context
window (Lightning: 1,024K tokens vs Nano: 262K tokens) rather than price, since price is
identical. No official source found a per-model minimum charge, a separate reasoning-token
price, or distinct "fast"/"base" flavor pricing for any of the four ids — one secondary
aggregator summary asserted such a split exists, but it could not be corroborated on Nebius's
own catalog, pricing table, or GitHub cookbook, and is recorded below as unconfirmed/likely
incorrect.

## Facts table

| Tier (role) | Exact model id (verbatim) | Context window | Max output tokens | Input price / 1M tok | Output price / 1M tok | Confidence |
|---|---|---|---|---|---|---|
| Fast candidate (Nano) | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 262K tokens | not stated in any source found | $0.06 | $0.24 | Confirmed in docs (id, context, price) |
| Fast candidate (Lightning) | `nvidia/Nemotron-3_5-Lightning` | 1,024K tokens (1M) | not stated in any source found | $0.06 | $0.24 | Confirmed in docs (id, context, price) |
| Mid (Super) | `nvidia/nemotron-3-super-120b-a12b` | 256K tokens | not stated in any source found | $0.30 | $0.90 | Confirmed in docs (id, context, price) |
| Deep (Ultra) | `nvidia/Nemotron-3-Ultra-550b-a55b` | 1,024K tokens (1M) | not stated in any source found | $1.00 | $3.00 | Confirmed in docs (id, context, price) |

Notes on ids:
- Casing is exactly as published — Nebius's own catalog is inconsistent (`NVIDIA-Nemotron-3-Nano-30B-A3B`
  uses a different casing convention than `Nemotron-3_5-Lightning` and `nemotron-3-super-120b-a12b`).
  Use the id strings above verbatim in API calls; do not normalize casing.
- The `3_5` in the Lightning id is a literal underscore, not a dot (`Nemotron-3_5-Lightning`,
  not `Nemotron-3.5-Lightning`) — the underscore form is what Nebius's catalog and pricing page
  both show as the API model id. The dot form (`Nemotron-3.5-Lightning`) appears on
  third-party sites (e.g. OpenRouter) describing the same underlying model but is not confirmed
  as the Nebius API id.
- No separate id was found for the model family's non-MoE/base checkpoints; Nebius appears to
  serve one id per tier.

### Lowest-price candidate for the smoke script

`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and `nvidia/Nemotron-3_5-Lightning` are tied at
$0.06 input / $0.24 output per 1M tokens — the lowest of the four. Recommend
**`nvidia/Nemotron-3_5-Lightning`** for the smoke script: same price as Nano, but a much larger
context window (1,024K vs 262K tokens), so one id covers both the cheap-smoke-test case and any
accidental large-context call without a second fallback id.

## `pricing.json` candidate values

```json
{
  "source": "https://tokenfactory.nebius.com/model-catalog.md",
  "date_checked": "2026-10-03",
  "models": {
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": {
      "tier": "fast",
      "input_usd_per_1m": 0.06,
      "output_usd_per_1m": 0.24,
      "context_window_tokens": 262144
    },
    "nvidia/Nemotron-3_5-Lightning": {
      "tier": "fast",
      "input_usd_per_1m": 0.06,
      "output_usd_per_1m": 0.24,
      "context_window_tokens": 1048576
    },
    "nvidia/nemotron-3-super-120b-a12b": {
      "tier": "mid",
      "input_usd_per_1m": 0.30,
      "output_usd_per_1m": 0.90,
      "context_window_tokens": 262144
    },
    "nvidia/Nemotron-3-Ultra-550b-a55b": {
      "tier": "deep",
      "input_usd_per_1m": 1.00,
      "output_usd_per_1m": 3.00,
      "context_window_tokens": 1048576
    }
  }
}
```

Context window token counts above convert the catalog's "K tokens" figures (262K, 256K, 1024K)
to integers using 1K = 1024 tokens; if the founder prefers the catalog's own rounding
(262,000 / 256,000 / 1,024,000) that is an equally defensible reading — the catalog page itself
only gives the "K" figures, not exact integers.

## Request/response examples

No request/response example could be captured from official docs in this pass: the
`docs.tokenfactory.nebius.com` pages for the model list and base-model catalog either redirected,
404'd, or returned pages with no model-listing content when fetched (see Open Questions for the
exact commands to get this directly). The GitHub cookbook at
`https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md` documents
usage via Jupyter notebooks (OpenAI-compatible client) but the fetched page did not include a
copyable code block in this pass — re-fetch directly if a usage example is needed.

## Limits

- Context windows: see table above (confirmed).
- Max output tokens per model: **not found** in any Nebius-controlled source (catalog page,
  pricing page, or docs site). Third-party aggregator pages suggested figures such as 32,768 or
  65,536 output tokens for Lightning, but these were attributed to OpenRouter's own deployment
  limits, not to Nebius's, and are not used here.
- Minimum charge per call/model: **not found**; no Nebius source mentions one.
- Reasoning-token pricing: **not found** as a separate price. The underlying Nemotron models are
  reasoning-capable (a `reasoning` request parameter is accepted per third-party docs), but no
  source shows reasoning tokens billed at a different rate than output tokens on Nebius.
- "Fast" vs "base" flavor pricing: **not found** on any Nebius-controlled source. One
  aggregated web-search summary asserted this distinction exists; it could not be corroborated
  against `tokenfactory.nebius.com/model-catalog.md`, the Nebius Nemotron product page, or the
  GitHub cookbook, all of which list exactly one id and one price per tier. Treat as unconfirmed
  and likely a confusion with "fast"/"base" distinctions some *other* provider makes for
  *other* models.

## Open questions (need a live check, API key required)

1. **Max output tokens per model.** Run, with a real `NEBIUS_API_KEY`:
   ```
   curl -s -H "Authorization: Bearer $NEBIUS_API_KEY" \
     "https://api.tokenfactory.nebius.com/v1/models?verbose=true" | \
     jq '.data[] | select(.id | test("Nemotron"))'
   ```
   (Base URL per Nebius quickstart docs; confirm `NEBIUS_BASE_URL` matches before running —
   the docs site uses `https://api.tokenfactory.nebius.com` or `https://api.studio.nebius.com`
   depending on when the account was created; check whichever is in `.env`.) The verbose model
   listing is documented as the source of per-model parameter limits including max output.
2. **Minimum charge / reasoning-token pricing / fast-base flavors.** Same `/v1/models?verbose=true`
   call, plus a check of the account's billing page at `https://tokenfactory.nebius.com` after
   one real call, to see if invoiced tokens match raw usage 1:1.
3. **Exact id casing/spelling confirmation.** The founder should run
   `curl -s -H "Authorization: Bearer $NEBIUS_API_KEY" https://api.tokenfactory.nebius.com/v1/models | jq '.data[].id'`
   once, and diff against the four ids in the facts table above before they're hardcoded into
   `pricing.json` — catalog pages and API responses occasionally drift.
4. Whether `nvidia/Nemotron-3_5-Lightning` (confirmed API id) and the `nvidia/nemotron-3.5-lightning`
   dotted spelling seen on third-party sites are the same served model under two names, or two
   different things — only matters if a dotted id is ever typed by hand from a non-Nebius source.

## Sources

- https://tokenfactory.nebius.com/model-catalog.md — Nebius's own machine-readable catalog;
  primary source for ids, context windows, and prices used above.
- https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference — Nebius
  product page for the Nemotron family; corroborates ids, context windows, and prices.
- https://mastra.ai/models/providers/nebius — third-party aggregator; used only to
  cross-check the catalog figures (ids match, confirms no 4th flavor/variant appears).
- https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md —
  Nebius's own cookbook repo; confirms three of the four models exist and gives parameter-count
  descriptions, but was not used for pricing (none given there).
- https://docs.tokenfactory.nebius.com/ and sub-pages — attempted for request/response examples
  and max-output-token docs; returned no Nemotron-specific content in this pass (see Open
  Questions for the direct API call to use instead).
