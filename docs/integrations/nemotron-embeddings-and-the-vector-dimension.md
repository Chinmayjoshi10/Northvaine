# Nemotron embeddings and the vector dimension

Date checked: 2026-10-03. Researcher notes for the Northvaine factory (see `docs/FACTORY.md`).

## Summary

- **There is no Nemotron-branded embedding model on Nebius Token Factory today.** Token
  Factory's live model catalog (`tokenfactory.nebius.com/model-catalog.md`) lists exactly
  **one** embedding model: `Qwen/Qwen3-Embedding-8B`. Nebius's own Nemotron models page lists
  only text-generation Nemotron models (Lightning, Super, Ultra, Nano) — none is an embedder.
  NVIDIA does publish a `nemotron-3-embed-1b` model (on `build.nvidia.com` / Hugging Face), but
  it was not found served through Token Factory's `/v1/embeddings` endpoint. **This blocks
  `MODEL_EMBED` from being a literal "Nemotron" model id** unless the founder confirms Token
  Factory has added one since this check (see Open questions #1).
- Until that's resolved, the closest sourced candidate for `MODEL_EMBED` on Token Factory is
  **`Qwen/Qwen3-Embedding-8B`**: native dimension **4096**, supports a `dimensions` request
  parameter for truncation (Matryoshka-style, 32–4096), L2-normalized output (cosine is the
  right metric), 32K max sequence length (Token Factory's catalog page shows "41K tokens"
  context — the two sources disagree slightly; treat 32K as the floor), price **$0.01 per 1M
  input tokens**, no output-token cost.
- The endpoint is `POST /v1/embeddings` (base `https://api.tokenfactory.nebius.com/v1/`),
  OpenAI-compatible. `input` accepts a string, a token-id array, or a list of either (so batch
  requests work); no explicit batch-size cap is documented. `dimensions` (integer) is accepted
  and lets you request a smaller output size than the model's native dimension.
- This directly answers the pgvector question (`docs/integrations/pgvector.md`): if we request
  `dimensions <= 2000` from Qwen3-Embedding-8B (or whatever model is finally chosen), the
  embedding column can be declared `vector(N)` with `N <= 2000` and indexed with a plain
  pgvector HNSW `vector_cosine_ops` index — no `halfvec` or expression-index workaround needed.
  If the model's native dimension were used uncapped (e.g. 4096, no truncation), `vector` HNSW
  would reject it (`vector` indexable up to 2,000 dims per `pgvector.md` fact #8) and we'd need
  `halfvec` (indexable to 4,000) instead.

## Facts

| # | Fact | Source | Confidence |
|---|------|--------|------------|
| 1 | Token Factory's model catalog lists one embedding model: `Qwen/Qwen3-Embedding-8B`, type `embedding`, context ~41K tokens, region `eu-north1`, `input_price_per_million_tokens=0.01`, `output_price_per_million_tokens=0` | https://tokenfactory.nebius.com/model-catalog.md | confirmed in docs (fetched today; catalog can change) |
| 2 | Nebius's "NVIDIA Nemotron models inference" page lists only: `nvidia/Nemotron-3_5-Lightning`, `nvidia/nemotron-3-super-120b-a12b`, `nvidia/Nemotron-3-Ultra-550b-a55b`, `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` — all text generation, no embedder | https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference | confirmed in docs |
| 3 | `POST /v1/embeddings` request schema: `model` (string, required), `input` (string, int-array, string-array, or nested int-arrays — so batching is supported), `encoding_format` (`float`\|`base64`, default `float`), `dimensions` (optional integer), `service_tier`, `user`, `ai_project_id` | https://docs.tokenfactory.nebius.com/api-reference/inference/create-embeddings | confirmed in docs |
| 4 | No explicit batch-size limit or max-input-token limit stated on the endpoint reference page itself | same as #3 | confirmed absence (not found, not necessarily nonexistent) |
| 5 | Worked example uses model `BAAI/bge-en-icl`, `POST https://api.tokenfactory.nebius.com/v1/embeddings`, body `{"model": "BAAI/bge-en-icl", "input": "...", "encoding_format": "float"}`; response is OpenAI-style `{"object":"list","data":[{"object":"embedding","embedding":[...],"index":0}],"model":...,"usage":{"prompt_tokens":8,"total_tokens":8}}` | https://docs.tokenfactory.nebius.com/api-reference/examples/create-embeddings | confirmed in docs |
| 6 | `Qwen/Qwen3-Embedding-8B`: native output dimension **4096** | https://huggingface.co/Qwen/Qwen3-Embedding-8B | confirmed in docs |
| 7 | Qwen3-Embedding-8B "supports user-defined output dimensions ranging from 32 to 4096" (Matryoshka Representation Learning) | https://huggingface.co/Qwen/Qwen3-Embedding-8B | confirmed in docs |
| 8 | Qwen3-Embedding-8B example code L2-normalizes embeddings (`F.normalize(embeddings, p=2, dim=1)`) before computing similarity, i.e. output is meant to be used normalized and cosine similarity is the intended metric | https://huggingface.co/Qwen/Qwen3-Embedding-8B | confirmed in docs (model card sample code) |
| 9 | Qwen3-Embedding-8B max sequence length 32K tokens; license Apache 2.0 | https://huggingface.co/Qwen/Qwen3-Embedding-8B | confirmed in docs |
| 10 | pgvector: `vector` type indexable (HNSW/IVFFlat) up to 2,000 dims; `halfvec` up to 4,000 dims | `docs/integrations/pgvector.md` fact #8 (sourced from pgvector README) | confirmed in docs (cross-referenced from our own prior research) |
| 11 | NVIDIA separately publishes `nemotron-3-embed-1b` (native dim 2048, per NVIDIA/third-party pages) as a model card on `build.nvidia.com`, served via NVIDIA NIM — this is a different delivery path than Nebius Token Factory and was not confirmed to be mirrored on Token Factory | https://build.nvidia.com/nvidia/nemotron-3-embed-1b/modelcard (page did not yield full detail on this fetch — see Open questions) | **unconfirmed** — treat the 2048 figure as unverified until re-checked with a working fetch |

## Examples (copied/paraphrased from docs)

```http
POST https://api.tokenfactory.nebius.com/v1/embeddings
Authorization: Bearer <NEBIUS_API_KEY>
Content-Type: application/json

{
  "model": "Qwen/Qwen3-Embedding-8B",
  "input": "Wake up, Neo...",
  "encoding_format": "float",
  "dimensions": 1024
}
```

```json
{
  "object": "list",
  "model": "Qwen/Qwen3-Embedding-8B",
  "data": [
    { "object": "embedding", "embedding": [0.0023, -0.0093, -0.0029], "index": 0 }
  ],
  "usage": { "prompt_tokens": 8, "total_tokens": 8, "completion_tokens": 0 },
  "service_tier": "auto"
}
```

## Limits

- Price: $0.01 / 1M input tokens for `Qwen/Qwen3-Embedding-8B`; no output-token cost for
  embedding calls.
- Native dimension 4096; `dimensions` parameter lets you request less (documented range for the
  underlying model: 32–4096). Choosing `EMBED_DIM <= 2000` keeps us on plain `vector(N)` +
  HNSW (`vector_cosine_ops`) — no `halfvec` migration needed.
- Max input: 32K tokens per the Hugging Face model card (Token Factory's own catalog page shows
  "41K tokens" for context — unreconciled; use 32K as the safe planning number until a live call
  confirms the actual Token Factory-side truncation point).
- No documented hard batch-size cap on `input` as a list; confirm empirically before relying on
  large batches (see live-check command below).

## Open questions

1. **Does Token Factory actually serve a Nemotron-branded embedder?** Not found in the live
   catalog or the Nemotron models page as of 2026-10-03. Confirm directly:
   ```sh
   curl -s https://api.tokenfactory.nebius.com/v1/models \
     -H "Authorization: Bearer $NEBIUS_API_KEY" | python -c "import sys,json; [print(m['id']) for m in json.load(sys.stdin)['data'] if 'embed' in m['id'].lower()]"
   ```
   If this lists no `nvidia/*embed*` id, the founder needs to decide: use `Qwen/Qwen3-Embedding-8B`
   (sourced above) as `MODEL_EMBED`, or source a Nemotron embedder another way. **This is a
   decision for `docs/DECISIONS.md`, not something to guess past.**
2. **Exact native dimension and `dimensions`-parameter behavior for whichever model is chosen**,
   confirmed by one live call before migration 0003 is written:
   ```sh
   curl -s https://api.tokenfactory.nebius.com/v1/embeddings \
     -H "Authorization: Bearer $NEBIUS_API_KEY" -H "Content-Type: application/json" \
     -d '{"model": "Qwen/Qwen3-Embedding-8B", "input": "northvaine test", "dimensions": 1024}' \
     | python -c "import sys,json; d=json.load(sys.stdin); print(len(d['data'][0]['embedding']))"
   ```
   Expect `1024`. Repeat without `dimensions` to confirm the native size is `4096`. Also check
   the vector's L2 norm is ~1.0 to confirm normalization:
   ```sh
   python -c "
import math
# paste the embedding list from the response as `v`
print(math.sqrt(sum(x*x for x in v)))
"
   ```
3. **Batch limits.** Not documented. If migration/ingestion code ever sends many texts in one
   `input` array, test with a batch of e.g. 100 short strings against the live endpoint and
   record the actual limit (HTTP 4xx, or a documented cap) before relying on it.
4. **The "41K tokens" (catalog) vs "32K" (Hugging Face model card) discrepancy** for
   Qwen3-Embedding-8B's context/sequence length was not reconciled. If exact chunk sizing
   matters, confirm with a live call using a long input near 32K tokens.
5. **`nemotron-3-embed-1b`'s own specs** (dimension, Matryoshka support, normalization) were not
   fully extracted on this pass (the `build.nvidia.com` fetch returned only page chrome). If the
   founder wants this model specifically and finds it reachable via Token Factory or a direct
   NVIDIA NIM endpoint, re-run this research against its actual model card /
   `build.nvidia.com/nvidia/nemotron-3-embed-1b/modelcard` content (try fetching the API
   reference tab specifically, not just the model card landing page).
