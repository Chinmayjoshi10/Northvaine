# Techniques and technology that would make Northvaine leads better

Date checked: 2026-10-09. Researcher notes for the Northvaine factory. No code written, no other file changed.
Confidence tags: **[confirmed]** = stated in an official page I fetched; **[inferred]** = my reasoning or a secondary/blog source; **[unknown]** = could not be established, command given.

## Summary

Our pipeline is already strong on trust (quote check, gate, skeptic, code-only rank). The biggest lead-quality losses are upstream and sideways, not in the judges:

1. **Identity is string-based** (`company_key` = normalised name + country). The same buyer under a registry id, a local-language name or a trade name becomes several candidates, and a buyer and its winning contractors are never linked.
2. **Documents are not linked into projects.** A plan, a tender and an award about one project are three separate pieces of evidence, so "why now" and "who will buy" are weaker than they could be.
3. **Retrieval is keyword/query only.** The only embedder on Token Factory is `Qwen/Qwen3-Embedding-8B`; there is no reranker, guard or classifier on Token Factory today.
4. **Scoring is code-only and unlearned**, which is right for now (no labels), but timing and calibration are the next real gain once feedback exists.

Hard platform facts that shape everything below:

- Token Factory's live catalog (25 models) has exactly one embedding model (`Qwen/Qwen3-Embedding-8B`, $0.01/1M in) and **no reranker, no guard/safety model, no classifier**. Nemotron there = Nano-30B-A3B, Super-120B-A12B, Ultra-550B-A55B, 3.5-Lightning, all text. [confirmed] https://tokenfactory.nebius.com/model-catalog.md (checked 2026-10-09; page says `/api/public/models_info` is the machine-readable source of truth.)
- So anything NVIDIA-branded beyond the chat models (Nemotron embed/rerank, NemoGuard, NeMo Retriever) means a second host (build.nvidia.com hosted API or self-hosted NIM), which does not satisfy "runtime calls via Token Factory" for that call and adds a key/ops surface. [inferred from catalog + NVIDIA docs]

## Ranked top 10 upgrades

Ranking = (quality gain x certainty) / effort, for a hackathon demo that must stay honest ("no source, no claim") and cheap.

### 1. Registry-id-first entity resolution, with LLM-adjudicated fuzzy tier  (Effort S-M, gain HIGH)
- **What:** Carry every identifier a source gives (TED organisation id/registration number, UK Companies House number, OCDS `parties[].identifier.scheme+id`, LEI where present) onto the claim/candidate and merge on `scheme-id` before falling back to `company_key`. Add a second fuzzy tier (token-set similarity + same country + shared domain/URL) whose only output is a *proposed merge* that one cheap LLM call (Nano/Lightning, strict schema, both claim sets fenced) confirms or rejects. Never auto-merge on name alone across different countries.
- **Why it helps:** removes duplicate leads and fixes split evidence (one buyer with three weak candidates becomes one strong one); also the foundation for #2 and #6.
- **Facts:**
  - OCDS gives each party a primary `identifier` with `scheme` and `id`, and suggests party ids of the form `{scheme}-{id}`; related processes link by `ocid`; contract -> award via `awardID`. [confirmed] https://standard.open-contracting.org/latest/en/schema/reference/
  - org-id.guide is the register of identifier-list codes, combined as e.g. `GB-COH-09506232`. [confirmed] https://org-id.guide/about
  - GLEIF API: LEI search with filters, full-text, single-field and fuzzy matching, parent/child relationship data, built on the Golden Copy. [confirmed] https://www.gleif.org/en/lei-data/gleif-api . Rate limit, licence text (CC0?) and whether it is free: **[unknown]** from that page; third-party pages claim CC0 but conflict. Check https://api.gleif.org/docs and the LEI Data Terms of Use.
  - LEI coverage skews to financial and larger entities; most small exporters and municipal buyers will have none. [inferred] so LEI is an enrichment, not a key.
  - Splink: probabilistic record linkage (Fellegi-Sunter), trainable unsupervised, DuckDB/Spark backends; a Postgres backend is described only by a third-party wiki. [confirmed for method/backends] https://moj-analytical-services.github.io/splink/ ; [inferred] Postgres backend and MIT licence (check the repo LICENSE).
- **Judgement:** Splink is the right tool at millions of records; at our volume (tens to hundreds of candidates per run) it is over-engineering. Rules + registry ids + one LLM adjudication is cheaper and explainable. Revisit Splink only if we build a cross-run entity table. [inferred]
- **Risks:** wrong merges are worse than duplicates (a merged buyer pollutes the quote check provenance). Keep merges reversible (store `merged_from` and the reason) and log the LLM verdict in `llm_calls`.
- **Plugs into:** `radar/entities.py` (`company_key`, `build_candidates`), `core/models.py` (`SubjectMention` gains `identifiers: list[{scheme,id}]`), `sensors/ted.py` and the UK FTS sensor (they already see the ids), `core/standards.py`.

### 2. Project-centric linking: plan -> tender -> award -> winners (Effort M, gain HIGH)
- **What:** Introduce a `project`/process key above candidates: group documents by procedure identifier / `ocid` / "previous notice" reference, then treat each stage as an event on one timeline. Output per project: stage, dates (bi-temporal: when it happened vs when we learned it), buyer, winner(s), lots. This is a small relational table, not a graph database.
- **Why it helps:** turns three weak leads into one with a stage ("planning, no tender yet" = earliest and best moment; "awarded, losers exist" = a different play); gives `bidders.py` ground truth for "who won similar awards"; fixes "why now" timing.
- **Facts:** OCDS links stages by `ocid`, `relatedProcesses` and `awardID` (see #1 source). TED eForms BT-04 Procedure Identifier exists [confirmed] https://docs.ted.europa.eu/eforms/1.13/reference/business-terms/BT-04.html ; BT-125 (previous planning link) and BT-501 [unknown], read their BT pages first.
- **Scope note:** graph storage, GraphRAG, temporal knowledge graphs (including Graphiti's bi-temporal model) and visualisation are covered in `docs/research/graph_connect_the_dots.md`; this report only proposes the small relational project key. Bi-temporal columns (world time vs knowledge time) are the one idea to borrow. [inferred]
- **Risks:** TED notices only link when the buyer fills the reference; non-EU/UK sources often have no ids, so link coverage will be partial. Show "linked by id" vs "linked by LLM guess" differently, and never link by LLM alone into a claim.
- **Plugs into:** `radar/entities.py` (new grouping step before candidates), `radar/bidders.py`, `radar/brief.py` (`_window_line`, `_why_now`), `radar/persist.py` and `schema.sql` (needs a decision entry, per CLAUDE.md "keep field names").

### 3. NLI-style entailment check after the exact quote check (Effort M, gain MED-HIGH for trust)
- **What:** The quote check proves the words exist; it does not prove the claim *follows* from them ("tender for pumps" quoted, claim says "buying pumps now"). Add a second, non-generative gate: a small entailment/grounding classifier (MiniCheck family) scoring (source_quote + surrounding context, claim) before the LLM check. Fall back to a cheap-tier LLM entailment call if we do not want a local model.
- **Facts:** MiniCheck (EMNLP 2024, Tang/Laban/Durrett): 770M model reaches GPT-4-level accuracy on LLM-AggreFact at about 400x lower cost (authors' claim). [confirmed, paper/abstract via search] https://arxiv.org/abs/2404.10774 . MiniCheck-RoBERTa-Large is MIT-licensed and sentence-level. [confirmed] https://huggingface.co/lytang/MiniCheck-RoBERTa-Large . English-centric (RoBERTa); multilingual quality: **[unknown]**.
- **Risks:** local model means PyTorch in the app image (tests must stay no-network/no-DB; a stub keeps `tasks.py test` fast); English-only will misjudge Spanish/Italian tenders. Mitigation: run on the English claim vs the quote only when quote language is English; otherwise use the existing LLM check.
- **Plugs into:** `radar/quote_check.py`, `radar/verify.py`. Tests: golden set cases with true-quote/false-claim pairs.

### 4. Hybrid retrieval over our own ledger + per-client multilingual query expansion (Effort M, gain MED-HIGH)
- **What:** (a) Embed claims/documents with `Qwen/Qwen3-Embedding-8B` into pgvector, combine with Postgres full-text via reciprocal-rank fusion, use it for "find related evidence for this candidate" and lookalike clients. (b) Per client, one fast-tier call generates query variants in the local language of each target country (and synonyms), stored as data (rule 1), then fed to Tavily/TED. This is where most recall is lost on multilingual tenders.
- **Facts:**
  - Only embedder on Token Factory: Qwen3-Embedding-8B, native dim 4096, `dimensions` parameter, 41K context, $0.01/1M. [confirmed] catalog above and `docs/integrations/nemotron-embeddings-and-the-vector-dimension.md`. Ask for `dimensions <= 2000` so plain HNSW works (already in our notes).
  - NVIDIA `llama-nemotron-embed-1b-v2`: 26 languages, up to 2048 dims (Matryoshka), 8192 tokens; on long documents BM25 beats it (59.55% vs 71.39% MLDR recall@5). [confirmed] https://huggingface.co/nvidia/llama-nemotron-embed-1b-v2 . Not on Token Factory. [confirmed by catalog]
  - Hybrid (dense + BM25) is the common recommendation, supported by the BM25 result above. [inferred]
- **Risks:** `MODEL_EMBED` is not a Nemotron model (submission narrative: Nemotron is for the generative steps, Qwen for embeddings; disclose). Embedding drift if the model changes: store model id with every vector.
- **Plugs into:** `radar/discover.py` `prepare_queries`, `radar/concepts.py`, `brain/llm.py` (`embed`), `docs/LATER.md` items on batch embeddings and HNSW.

### 5. Cheap-tier relevance triage before the gate (LLM pointwise "reranker") (Effort S, gain MED, saves cost)
- **What:** Between candidates and gate, one Nano/Lightning call per candidate returns a 0-3 relevance label with a one-line reason against the client's offer; use it to order the gate budget and drop obvious noise. Only a triage: never a score shown to the user.
- **Facts:**
  - No reranker on Token Factory. [confirmed]
  - NVIDIA's reranker `llama-nemotron-rerank-1b-v2` is a 1B cross-encoder, 26 languages, 8192 tokens, available as NIM / self-host (OpenMDW + Llama 3.2 licence). [confirmed] https://huggingface.co/nvidia/llama-nemotron-rerank-1b-v2
  - LLM rerankers: pointwise scales linearly with candidates, scores can be unstable run to run; dedicated rerankers are reported 10-30x cheaper by a vendor and slightly better (0.74 vs 0.68 NDCG@10) in a vendor benchmark. [inferred, vendor blog] https://www.zeroentropy.dev/articles/llm-as-reranker-guide/
- **Judgement:** at $0.06/$0.24 per 1M tokens, a pointwise triage of 100 candidates at ~1.5K tokens each is about $0.01 [inferred arithmetic]; far below the engineering cost of a second host. Use cross-encoder only if candidate counts reach thousands.
- **Plugs into:** `radar/run.py` (between `build_candidates` and `gate_candidate`), `brain/prompts/`, golden set.

### 6. Calibrated, learned scoring with a timing model (Effort L, gain HIGH later, LOW now)
- **What:** Keep code-only rank as the prior. When founder feedback exists (accept/reject/won), (i) calibrate the rank into a probability (Platt when labels are very few, isotonic when more), (ii) model time-from-signal-to-purchase with a discrete-time hazard or Cox model so unconverted leads still count as censored data, (iii) report ranges, not point values. Learning-to-rank is premature with sparse labels; a monotonic logistic over our existing features (stage, recency, value, evidence strength) is enough.
- **Facts:** I found no authoritative source for B2B lead scoring with few labels; survival modelling of sales time exists in the literature (title only seen) and conformal survival analysis exists (arXiv 2410.24136, abstract not read). [unknown to inferred] Conformal prediction needs exchangeable data; pipelines drift. [inferred]
- **Risks:** fake precision. ARCHITECTURE's attention allocator and learners already own this; do not duplicate. Display "n=… labelled outcomes" next to any probability.
- **Plugs into:** `radar/brief.py` `rank`, `radar/learning.py`, `radar/questions.py`, `docs/ARCHITECTURE.md` learners.

### 7. Tavily Map/Crawl-with-instructions for buyer pages; Research only for the top few (Effort S-M, gain MED)
- **What:** For candidates that pass the gate, replace one-page publisher fetch with a bounded Tavily Crawl (`instructions` = "find tenders, suppliers, projects, expansion"; `select_paths`; `max_depth`<=2, `limit`<=20) to collect evidence the site itself states; send results through the same ledger/quote check. Use `/research` with an `output_schema` only for a final dossier of the top 3-5 leads.
- **Facts:** Crawl: `instructions`, `max_depth` 1-5, `max_breadth` 1-500, `limit` default 50, `select_paths`, `extract_depth`, `chunks_per_source` 1-5; cost 1 credit/10 pages (2 with instructions) plus extraction 1 credit/5 pages basic. [confirmed] https://docs.tavily.com/documentation/api-reference/endpoint/crawl . Research: `model` mini/pro/auto, `output_schema`, `citation_format`, async (HTTP 201 + request id), include/exclude domains up to 20; cost mini 4-110 credits, pro 15-250 credits; pay-as-you-go $0.008/credit, free tier 1,000 credits/month. [confirmed] https://docs.tavily.com/documentation/api-reference/endpoint/research and https://docs.tavily.com/documentation/api-credits . The research report's final result format is not documented on that page. [unknown]
- **Risks:** Tavily Research output is another LLM's prose: **it must never become a claim without our own quote check** (rule 2); treat as leads for fetching only. Crawl must still respect robots/deny list (rule 9) which Tavily does not do for us: [unknown], ask Tavily or keep our `safe_fetch` for the final page.
- **Plugs into:** `sensors/tavily.py`, `radar/discover.py` (upgrade step), budget caps in `brain/budget.py` (credits as a budget too).

### 8. Prompt-injection hardening by architecture, not by detector (Effort S, gain risk-reduction)
- **What:** Make the extractor a *quarantined* LLM: untrusted text in, strict schema out (enums, maxItems, quotes), and code (not a privileged LLM) decides every action. Never feed raw fetched text to the gate/skeptic/brief: they see only verified claim lines (already the case). Add canary tests: pages with embedded instructions must change nothing.
- **Facts:**
  - Design-patterns paper (arXiv 2506.08837): plan-then-execute, action-selector, dual-LLM/quarantine, context-minimisation patterns; core premise: once an agent ingests untrusted input it must be constrained so the input cannot trigger consequential actions. [confirmed via search of paper abstract/summaries] https://arxiv.org/abs/2506.08837
  - Our own live probe: strict schema `enum` and `maxItems` were enforced against an injected instruction (one case each). [confirmed live, `docs/integrations/nebius-token-factory-strict-structured-output...md`]
  - NeMo Guardrails / NemoGuard: `nemoguard-jailbreak-detect` (classifier on `/v1/classify`), `llama-3.1-nemotron-safety-guard-8b-v3` (23 safety categories, chat-completions), `llama-3.1-nemoguard-8b-topic-control`; deployed as NIMs needing 1 GPU each. [confirmed] https://docs.nvidia.com/nemo/microservices/latest/guardrails/tutorials/deploy-nemoguard-nims.html . None are on Token Factory. [confirmed by catalog]
- **Judgement:** the detectors are a poor fit (extra GPU host, English jailbreak-oriented, we already forbid actions on external text). Architecture is stronger. Mention NeMo Guardrails in the README as a considered-and-deferred option. [inferred]
- **Plugs into:** `brain/fencing.py`, `radar/extract.py`, `tests/golden/` red-team set, `scripts/check_invariants.py`.

### 9. Bounded, verified agentic investigator for the top-K only (Effort M-L, gain MED, cost HIGH)
- **What:** For the 3-5 leads the user will actually open, run a planner -> search/fetch -> verifier loop that tries to answer the open questions the skeptic wrote ("who is the decision-maker department?", "is the budget approved?"). Each step's output is a fenced document that enters the ledger; the loop ends on budget or when open questions are answered or marked unknown. A fixed pipeline remains the default.
- **Facts:**
  - Anthropic's orchestrator-worker research system: lead + parallel subagents beat a single agent by 90.2% on their internal research eval; the commonly cited "about 15x tokens vs chat" is not in the excerpt I could access (a blog says 4x). [confirmed for 90.2%, **[unknown]** for the multiplier] https://www.anthropic.com/engineering/multi-agent-research-system
  - NVIDIA NeMo Agent Toolkit (formerly AgentIQ), Apache-2.0, framework-agnostic; has ReAct, Reasoning, ReWOO, Router agents, evaluation, profiling, MCP and A2A. [confirmed for features, docs nav; licence via forum/GitHub summary] https://docs.nvidia.com/nemo/agent-toolkit/latest/index.html ; whether arbitrary OpenAI-compatible endpoints (Token Factory) work out of the box: **[unknown]**; check the "LLMs"/"Using local LLMs" pages.
- **When an agent beats a pipeline:** open-ended, branching questions on a few high-value items (our "open questions"); not for gate/skeptic/rank, which need determinism and per-call budgets. [inferred]
- **Judgement:** do not add NeMo Agent Toolkit; it duplicates `llm.py` budget/validation and bypasses invariants. A 60-line loop on our own primitives suffices. Possibly mention it as an eval/profiling option in the README. [inferred]
- **Risks:** cost, nondeterminism, injection surface (see #8); needs a hard per-lead budget and a golden test.
- **Plugs into:** new `radar/investigate.py` after `skeptic`, `radar/questions.py`, `brain/budget.py`.

### 10. Nemotron tiering and reasoning control, plus self-consistency on borderline gates (Effort S-M, gain MED)
- **What:** Route by step: extraction and triage = Lightning/Nano with reasoning off; gate and skeptic = Super with reasoning on (we already found gate v2 needed to reason first, D75); deep tier (Ultra, 1M context) only for cross-document project summaries. For gate decisions near the threshold, take 2 independent samples and require agreement, else "unknown -> ask a person". Spend at the margin only.
- **Facts:**
  - Nemotron 3 Super: reasoning on by default and toggled with chat-template arg `enable_thinking`; also a `reasoning_budget`; recommended temperature=1.0, top_p=0.95. [inferred; SGLang/NVIDIA RAG-blueprint docs via search, not Token Factory] https://docs.nvidia.com/rag/2.6.0/enable-nemotron-thinking.html
  - Token Factory parameter name for reasoning on Nemotron: our probe used `reasoning_effort: "none"` on Lightning successfully for structured output (`docs/integrations/nebius-token-factory-strict-structured-output...md`); whether `enable_thinking`/`reasoning_budget` is accepted: **[unknown]**. Command to test (founder, needs key; do not print the key): POST `/v1/chat/completions` with `"chat_template_kwargs":{"enable_thinking":false}` vs `"reasoning_effort":"low"` and compare `usage.completion_tokens`.
  - Context: Lightning and Ultra 1M tokens, Nano 262K, Super 256K; prices $0.06/0.24, $0.06/0.24, $0.30/0.90, $1/3 per 1M (in/out). [confirmed] catalog above.
  - Guided JSON for Nemotron 3 Super is not documented anywhere I could find; our own strict-schema probe is the evidence. [unknown officially / confirmed live]
- **Risks:** reasoning tokens bill as output (assumed, unverified, see integration note #16); sampling at temperature 1.0 makes outputs noisier, so record seeds and use replay fixtures for tests.
- **Plugs into:** `brain/llm.py` model routing, `gate.py`, `court.py`, `extract.py`, `core/settings.py` (`MODEL_*`).

## What I would not do (and why)

- **Graph database / GraphRAG**: see `docs/research/graph_connect_the_dots.md`.
- **Self-hosted NemoGuard / Nemotron rerank / Nemotron embed NIMs** for the hackathon: second host, GPU, and breaks the "runtime via Token Factory" story. Revisit post-hackathon if the API is added to Token Factory (check catalog again; `GET /api/public/models_info`).
- **Splink now**: right tool at larger scale, not at ours (see #1).
- **Learning-to-rank now**: no labels yet (see #6).

## Facts table (quick reference)

| # | Fact | Source | Confidence |
|---|------|--------|-----------|
| 1 | Token Factory catalog: 25 models; one embedder (Qwen3-Embedding-8B); no reranker/guard/classifier | https://tokenfactory.nebius.com/model-catalog.md | confirmed (2026-10-09) |
| 2 | Nemotron ids/prices/context on Token Factory | same | confirmed |
| 3 | Nemotron embed 1B v2: 26 langs, 2048 dims, 8192 tok; BM25 wins on long docs | https://huggingface.co/nvidia/llama-nemotron-embed-1b-v2 | confirmed |
| 4 | Nemotron rerank 1B v2: cross-encoder, 26 langs, 8192 tok, NIM | https://huggingface.co/nvidia/llama-nemotron-rerank-1b-v2 | confirmed |
| 5 | NemoGuard NIMs: jailbreak-detect, safety-guard-8b-v3, topic-control; 1 GPU each | https://docs.nvidia.com/nemo/microservices/latest/guardrails/tutorials/deploy-nemoguard-nims.html | confirmed |
| 6 | Tavily Crawl params and credits | https://docs.tavily.com/documentation/api-reference/endpoint/crawl | confirmed |
| 7 | Tavily Research params; mini 4-110, pro 15-250 credits; $0.008/credit PAYG | research + api-credits pages | confirmed |
| 8 | Tavily Research result format | research page | unknown |
| 9 | OCDS party identifier scheme+id, ocid, relatedProcesses | https://standard.open-contracting.org/latest/en/schema/reference/ | confirmed |
| 10 | TED eForms BT-04 Procedure Identifier exists | https://docs.ted.europa.eu/eforms/1.13/reference/business-terms/BT-04.html | confirmed |
| 11 | TED BT-125 / BT-501 roles | docs.ted.europa.eu BT pages | unknown (read them) |
| 12 | GLEIF API supports fuzzy search and parent/child data | https://www.gleif.org/en/lei-data/gleif-api | confirmed |
| 13 | GLEIF rate limits, licence (CC0?), cost | https://api.gleif.org/docs | unknown |
| 14 | Splink: Fellegi-Sunter, unsupervised, DuckDB/Spark | https://moj-analytical-services.github.io/splink/ | confirmed; Postgres backend inferred |
| 15 | MiniCheck 770M ~GPT-4-level at ~400x lower cost; RoBERTa variant MIT | https://arxiv.org/abs/2404.10774 ; https://huggingface.co/lytang/MiniCheck-RoBERTa-Large | confirmed (authors' claims) |
| 16 | Injection design patterns paper | https://arxiv.org/abs/2506.08837 | confirmed |
| 17 | Anthropic multi-agent research: +90.2% vs single agent; token multiplier | https://www.anthropic.com/engineering/multi-agent-research-system | 90.2% confirmed; multiplier unknown |
| 18 | NeMo Agent Toolkit: agents, eval, profiling, MCP, A2A; Apache-2.0 | https://docs.nvidia.com/nemo/agent-toolkit/latest/index.html | features confirmed; licence inferred (secondary) |
| 19 | Nemotron reasoning toggle `enable_thinking`, `reasoning_budget` | https://docs.nvidia.com/rag/2.6.0/enable-nemotron-thinking.html | inferred (not Token Factory) |
| 21 | LLM reranker pointwise/listwise tradeoffs | https://www.zeroentropy.dev/articles/llm-as-reranker-guide/ (vendor blog) | inferred |

## Open questions and commands to run

1. Does Token Factory accept `chat_template_kwargs.enable_thinking` or `reasoning_budget` for Nemotron? Test with one cheap call each; compare `usage`.
2. Has the catalog added a Nemotron embedder, reranker or guard model? Run: `curl -s https://tokenfactory.nebius.com/api/public/models_info` and look for `embedding`/`rerank`/`guard` types.
3. TED BT-125 and BT-501 semantics: fetch the eForms 1.13 reference pages named above.
4. GLEIF: read https://api.gleif.org/docs for rate limits and licence before any bulk use.
5. Tavily: does Crawl honour robots.txt, and what is the Research result schema? Ask Tavily support or run one `mini` call with `output_schema` and record it.
6. Does NeMo Agent Toolkit accept an arbitrary OpenAI-compatible `base_url`? Read its LLM provider docs; only matters if #9 is built with it.
7. MiniCheck multilingual behaviour on our Spanish/Italian fixtures: test on `tests/fixtures/` before adopting.
