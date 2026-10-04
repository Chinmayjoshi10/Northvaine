# Nebius Token Factory: API surface and client

Date checked: 2026-10-03
Researcher pass. Source: official Nebius Token Factory docs (`docs.tokenfactory.nebius.com`)
unless marked otherwise. No API key was used for this pass — a few facts (exact model ids,
live pricing, live rate-limit allocation) need a one-time authenticated check; the exact
command is given in each case.

## Summary

Token Factory exposes an OpenAI-compatible REST API at `https://api.tokenfactory.nebius.com/v1/`.
The standard `openai` Python package works as the client with just `base_url` and `api_key`
overridden — no Nebius-specific SDK exists or is needed. Structured outputs are supported via
`response_format: {"type": "json_schema", ...}` (schema-following) as well as
`{"type": "json_object"}` (free-form JSON); model-by-model support is not published as a table —
check the model's card for a "JSON mode" tag, or test directly. Chat completions return the
standard OpenAI shape (`choices`, `usage.prompt_tokens/completion_tokens/total_tokens`); no cost
figure is included in the completion response itself, but `GET /v1/models?verbose=true` returns
a `pricing` object per model that we can use as our cross-check table. Rate limits are dynamic
(start at 60 RPM / 400k TPM per docs' example, auto-scale up to 20x with sustained usage) and are
reported live via `x-ratelimit-*` response headers; 429 responses carry `Retry-After`. 5xx error
body shape is not documented — treat as standard HTTP, retry with backoff on any 5xx. Reasoning/
thinking control for the Ultra tier is not documented on Token Factory's own pages for Nemotron
specifically; community usage elsewhere in the vLLM/NIM ecosystem suggests `reasoning_effort` or
`chat_template_kwargs: {enable_thinking: bool}`, but this is **unconfirmed for Token Factory** and
must be tested against the live endpoint before relying on it.

## Facts table

| # | Question | Answer | Confidence | Source |
|---|---|---|---|---|
| 1 | Base URL | `https://api.tokenfactory.nebius.com/v1/` | confirmed in docs | [Introduction](https://docs.tokenfactory.nebius.com/api-reference/introduction), [Quickstart](https://docs.tokenfactory.nebius.com/quickstart) |
| 2 | Auth | `Authorization: Bearer <NEBIUS_API_KEY>` header; the `openai` client's `api_key=` param sends this automatically | confirmed in docs | same |
| 3 | Client SDK | Standard `openai` Python package (`pip install openai`), pointed at the Token Factory `base_url`. No version pin is stated in the docs and no Nebius-specific SDK exists | confirmed (no SDK), inferred (no version pin given) | [Quickstart](https://docs.tokenfactory.nebius.com/quickstart) |
| 4 | `scripts/check_invariants.py` `LLM_SDKS` | Only `openai` needs to be present/allowed — there is no separate Nebius package to add | confirmed (absence) | same |
| 5 | Structured outputs | Both `response_format: {"type": "json_schema", "json_schema": {...}}` (schema-following) and `{"type": "json_object"}` (arbitrary JSON) are supported. Docs do not formally name a "strict" mode as a flag, though an example schema in the docs includes `"strict": true` as a property inside the schema object | confirmed (two modes exist), unclear (strict-mode semantics) | [Structured output & JSON](https://docs.tokenfactory.nebius.com/ai-models-inference/json) |
| 6 | Per-model structured-output support | Not published as a table. Docs say some models are "better... due to their training data" and point to per-model "JSON mode" tags on model cards | unconfirmed — check model card or test | same |
| 7 | Chat completion response shape | Standard OpenAI shape: `object`, `created`, `model`, `choices[].{index, message, finish_reason}` | confirmed | [Introduction](https://docs.tokenfactory.nebius.com/api-reference/introduction) |
| 8 | `usage` object fields | `prompt_tokens`, `completion_tokens`, `total_tokens` | confirmed | same |
| 9 | Cost figure in response | Not present in the completion response. A per-model `pricing` object (`pricing.prompt`, `pricing.completion`, `pricing.request`, `pricing.image`, `pricing.price_per_video_second`) is returned by `GET /v1/models?verbose=true` and should be our cross-check source, cached locally rather than parsed per call | confirmed (absent from completions), confirmed (present in verbose model listing) | [List of models](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models) |
| 10 | Rate limits | Dynamic per-account allocation, not a fixed published number. Docs' own illustrative baseline: 60 RPM / 400,000 TPM. Every 15-minute window: usage ≥ 80% of current limit → limit ×1.2 for next window; usage ≤ 50% → limit ÷1.5. Grows up to 20x the base allocation before an Enterprise plan is required | confirmed mechanism; **exact starting numbers for this account are unconfirmed** — see "Open questions" for the command to check | [Rate Limits & Scaling](https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits) |
| 11 | Rate limit scope (per key vs per model) | Not stated explicitly in the page fetched | unconfirmed | same |
| 12 | Rate limit response headers | `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`, `x-ratelimit-over-limit` | confirmed | same |
| 13 | 429 body shape | Not documented beyond "HTTP 429 returned". A `Retry-After` header **is** documented: "time in seconds to wait before making another request" | confirmed (header), unconfirmed (body JSON shape — assume OpenAI-standard `{"error": {...}}` until seen live) | same |
| 14 | 5xx handling | Not documented on the rate-limits page. Other pages mention 403/404/409/422 for specific endpoint classes (dedicated endpoints troubleshooting), not generic 500/502/503 for chat completions | unconfirmed | [FAQ & Troubleshooting](https://docs.tokenfactory.nebius.com/ai-models-inference/dedicated-endpoints/faq) |
| 15 | Reasoning/thinking params for Ultra tier | Not documented on Token Factory's own API reference pages for Nemotron. A marketing page states the "live Token Factory catalog lists tool calling and reasoning for the highlighted Nemotron models" but gives no parameter name. Community/ecosystem precedent (vLLM, Qwen3 on Token Factory, NIM) uses `reasoning_effort` (e.g. `"none"/"low"/"medium"/"xhigh"`) or `chat_template_kwargs: {"enable_thinking": bool}` — **neither confirmed for Nemotron on Token Factory specifically** | unconfirmed — test against live endpoint before use | [Nemotron models inference](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference) (marketing, not API ref); ecosystem precedent is blog/forum-level, last resort |
| 16 | Does reasoning change billed tokens | Not documented for Token Factory. General LLM-industry pattern is that reasoning/thinking tokens are counted inside `completion_tokens` — **assume this but verify** by checking `usage` on a live reasoning call before relying on it for budget math | unconfirmed | n/a |
| 17 | List models (free check) | `GET /v1/models` lists ids only, no cost; add `?verbose=true` for pricing + rate-limit metadata per model. Whether this call itself is billed is not stated, but model-listing endpoints are free on essentially every OpenAI-compatible provider and nothing in the docs suggests otherwise | inferred (free), confirmed (shape) | [List of models](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models) |

## Request/response examples (from docs)

### Chat completion (basic)

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=os.environ.get("NEBIUS_API_KEY"),
)

response = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-R1-0528",
    messages=[
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    ],
)
print(response.to_json())
```

### Structured output — `json_schema` mode

```json
{
  "model": "Qwen/Qwen3-235B-A22B",
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "type": "object",
      "properties": {
        "title": { "type": "string" },
        "year": { "type": "integer" }
      },
      "required": ["title", "year"]
    }
  },
  "messages": [
    { "role": "system", "content": "Respond with JSON following the provided schema." },
    { "role": "user", "content": "Jack Nicholson" }
  ]
}
```

Note: the docs' example nests the schema body directly under `json_schema` rather than under
a `json_schema.schema` key the way OpenAI's own spec does — **confirm the exact nesting against
a live call** before wiring `brain/llm.py`'s Pydantic-to-schema path to it, since a mismatch here
would silently fall back to unstructured output.

### Usage object (chat completion)

```json
{
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

### List models (free, no key needed to run — key needed to authenticate)

```bash
curl https://api.tokenfactory.nebius.com/v1/models \
  -H "Authorization: Bearer $NEBIUS_API_KEY"
```

```json
{
  "object": "list",
  "data": [
    { "id": "model-name", "object": "model", "created": 1724480826, "owned_by": "system" }
  ]
}
```

Verbose form (pricing + rate-limit cross-check — this is the call the orchestrator should run
to get real model ids for `MODEL_FAST` / `MODEL_MID` / `MODEL_DEEP` / `MODEL_EMBED`):

```bash
curl -s 'https://api.tokenfactory.nebius.com/v1/models?verbose=true' \
  -H "Authorization: Bearer $NEBIUS_API_KEY" \
  -H 'accept: application/json' \
  -X GET | jq '.data[] | {id, context_length, quantization, pricing, per_request_limits}'
```

Verbose response adds, per model: `context_length`, `quantization`,
`pricing.{prompt,completion,request,image,price_per_video_second}`, and
`per_request_limits.{requests_per_minute,tokens_per_minute,burst_ratio}`.

## Limits

- Rate limits are **dynamic per-account**, not a fixed number we can hardcode: baseline example
  60 RPM / 400k TPM, auto-scaling ±20%/15-min-window based on utilization, capped at 20x base
  without an Enterprise plan.
- On 429: back off and retry, honoring the `Retry-After` header; also track
  `x-ratelimit-remaining-requests` / `x-ratelimit-remaining-tokens` proactively rather than
  waiting to be throttled.
- 5xx handling has no documented body shape — retry with exponential backoff as a generic
  safety net, same as any HTTP API, but don't assume a specific error JSON schema for 5xx.

## Open questions (need the founder's key to resolve)

1. **Exact model ids for `.env`** (`MODEL_FAST`, `MODEL_MID`, `MODEL_DEEP`, `MODEL_EMBED`).
   Marketing pages suggest ids like `nvidia/Nemotron-3_5-Lightning`,
   `nvidia/nemotron-3-super-120b-a12b`, `nvidia/Nemotron-3-Ultra-550b-a55b`, but these are from a
   non-API-reference page and must not be trusted as literal ids. Run:
   ```bash
   curl -s https://api.tokenfactory.nebius.com/v1/models \
     -H "Authorization: Bearer $NEBIUS_API_KEY" | jq '.data[].id' | grep -i nemotron
   ```
   and copy the exact strings into `.env`.
2. **This account's actual starting rate limit** (not the docs' illustrative 60/400k) — check the
   Token Factory dashboard's Rate Limits section, or read the `x-ratelimit-limit-*` headers off a
   real response.
3. **Whether `json_schema` nests the schema under `.schema` or directly under `.json_schema`** —
   the docs example nests it directly; confirm with one live structured-output call before
   `brain/llm.py` depends on it.
4. **Reasoning/thinking parameter name for Nemotron Ultra on Token Factory**, and whether
   reasoning tokens land inside `completion_tokens` for budget purposes — make one live call to
   the Ultra-tier model with a candidate parameter (`reasoning_effort`, then
   `chat_template_kwargs.enable_thinking`) and inspect both the response and `usage`.
5. **Exact 429/5xx error body shape** — capture one real 429 (e.g. by deliberately exceeding the
   per-minute limit in a throwaway script) and save it as a fixture under `tests/fixtures/` so
   retry-handling code in `brain/llm.py` can be tested without guessing the shape.

---

## Pre-flight probe results — live, confirmed 2026-10-03

Run by the orchestrator with the founder's key against `https://api.tokenfactory.nebius.com/v1/`.
Approved under M2 PLAN.md "Pre-flight probe". Total spend: 44 input + ~96 output tokens on
Lightning and 8 embedding tokens — **under $0.0001**. These supersede every "unconfirmed" row above
that they touch.

### P1 — `GET /v1/models?verbose=true` (free, HTTP 200)

25 models in the catalog. The five that matter:

| id (exact, case-sensitive) | ctx | $/1M in | $/1M out | region | features |
|---|---|---|---|---|---|
| `nvidia/Nemotron-3_5-Lightning` | 1,048,576 | 0.06 | 0.24 | eu-north1 (FI) | tools, reasoning |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 262,144 | 0.06 | 0.24 | eu-north1 (FI) | tools, reasoning |
| `nvidia/nemotron-3-super-120b-a12b` | 262,144 | 0.30 | 0.90 | us-central1 (US) | tools, reasoning |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | 1,048,576 | 1.00 | 3.00 | us-central1 (US) | tools, reasoning |
| `Qwen/Qwen3-Embedding-8B` | 40,960 | 0.01 | — | eu-north1 (FI) | text->embedding |

Confirmed notes:

1. **Pricing is per *token*, not per million** (`"prompt":"0.00000006"`). Multiply by 1e6 for the
   table above. `pricing.json` must store the per-million figure and the loader must not re-scale.
2. **There is no `max_output_tokens` field.** The verbose listing gives `context_length` only. The
   budget guard's output upper bound must come from our own `max_tokens` request value, not from
   the catalog. (This closes the P1 question in the plan as "the API does not expose it".)
3. **Per-model rate limits are returned** in `per_request_limits`
   (`tokens_per_minute`, `requests_per_minute`, `burst_ratio`), and they differ sharply per model:
   Lightning 400k TPM / 600 RPM, Nano 800k TPM / **100 RPM**, Super and Ultra effectively unlimited,
   embeddings 600k TPM / 10,000 RPM. The docs' illustrative "60 RPM / 400,000 TPM" is not this
   account's allocation.
4. Super and Ultra are **US-region only**; Lightning, Nano and the embedder are EU (FI). Relevant to
   data residency for any client content sent to the mid/deep tiers.
5. `supported_sampling_parameters` is returned per model: temperature, top_p, top_k,
   repetition_penalty, frequency_penalty, presence_penalty for all four Nemotrons; **empty** for the
   embedder.
6. The catalog ids do **not** follow one convention — `nvidia/Nemotron-3_5-Lightning` uses an
   underscore for the decimal point, `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` repeats the vendor, and
   `nvidia/nemotron-3-super-120b-a12b` is lowercase. They must be copied verbatim; guessing fails.

### P2 — structured output on `nvidia/Nemotron-3_5-Lightning` (HTTP 200)

**The schema nests under `json_schema.schema`** — the standard OpenAI convention, not the flat shape
the Nebius doc example suggested. `"strict": true` sits beside `name` inside `json_schema` and is
accepted. Confirmed working request body:

```json
"response_format": {
  "type": "json_schema",
  "json_schema": {
    "name": "capital",
    "strict": true,
    "schema": {"type": "object",
               "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
               "required": ["city", "country"],
               "additionalProperties": false}
  }
}
```

**The decisive finding is not the schema shape — it is reasoning.** The Nemotron 3.x models are
reasoning models and think *by default, into `message.content`*:

- First attempt, `max_tokens: 60`, no reasoning parameter: the reply was
  `"Here's a thinking process:\n\n1. **Analyze User Input:** ..."`, `finish_reason: "length"`,
  `usage.completion_tokens_details.reasoning_tokens: 60`. **The JSON schema did not constrain the
  output at all** and every token was spent on visible thinking. Under a $1 lifetime cap this
  failure mode alone could drain the budget on repair retries.
- Second attempt, identical but with **`"reasoning_effort": "none"`**: `finish_reason: "stop"`,
  content exactly `{"city": "Paris", "country": "France"}`, **14 completion tokens** instead of 60+.

So `reasoning_effort` **is honoured on Nemotron via Token Factory** (closing open question 15 above,
which the research could only source to ecosystem precedent). `brain/llm.py` must send
`reasoning_effort: "none"` by default on every structured call and only raise it deliberately.
`reasoning_content` and `reasoning` are returned as separate `null` fields — thinking is *not*
separated into them on this model, it goes into `content`.

Response shape is otherwise standard OpenAI, plus Nebius extras:
`prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` in `usage`, and
`stop_reason`, `token_ids`, `prompt_logprobs`, `prompt_token_ids`, `kv_transfer_params`,
`ec_transfer_params` as nulls. **No cost field in the response** — confirmed; cost must be computed
from `usage` x `pricing.json`.

### P3 — `POST /v1/embeddings` on `Qwen/Qwen3-Embedding-8B` (HTTP 200)

| request | returned vector length |
|---|---|
| no `dimensions` parameter | **4096** (native, as documented) |
| `"dimensions": 1024` | **exactly 1024** |

The `dimensions` parameter is honoured exactly. **Both vectors are L2-normalized to 1.0** (measured:
norm = 1.000000 at 4096 and at 1024), so Matryoshka truncation is re-normalized server-side and
`vector_cosine_ops` is the correct operator class. `usage` reports `prompt_tokens: 4` for a
three-word input and `completion_tokens: 0`.

**This confirms the plan's primary path.** `EMBED_DIM = 1024`, column `vector(1024)`, plain HNSW
`vector_cosine_ops` — comfortably under pgvector's 2,000 index limit. The 4096 native dimension is
confirmed unindexable (above the 4,000 `halfvec` ceiling), so the `dimensions` parameter is not an
optimization here, it is what makes indexed vector search possible at all.

- **Strict structured output (2026-10-04):** which JSON Schema keywords Token Factory honours with `strict=true` - see `nebius-token-factory-strict-structured-output-which-json-schema-features-are-honoured-needed-by-the-extractor-and-support-check-schemas-.md`.
