# Milestone 4 plan: the evidence ledger (verified claims to events)

status: **approved** (orchestrator, 4 Oct 2026, per founder delegation; founder answered Q1 yes and Q2 yes on 4 Oct)
date: 2026-10-04
baseline: `main` at ad9aca3 (gate green: 729 passed, 25 deselected; migration head 0004).
`northvaine/radar/` holds only an empty `__init__.py`. Already on main: `ClaimRow`, `EventRow`,
`EventConceptRow` (no ledger code uses them), the 12 level-0 seed concepts (embeddings NULL),
`brain/llm.py` (`complete_json`, `embed` with one text, a random fence nonce per call), and the
recorded sensor fixtures: 72 TED documents and 13 Tavily documents. Only 4 Tavily documents are
full text (`text_kind='raw'`, each cut to about 1,500 characters at redaction); 9 are
snippet-only, including all 3 for the packaging client.
research:
- `docs/integrations/nebius-token-factory-strict-structured-output-which-json-schema-features-are-honoured-needed-by-the-extractor-and-support-check-schemas-.md` (PF1 note; **untracked, the orchestrator commits it before T4.0 starts**)
- `docs/integrations/nebius-token-factory-api-surface-and-client.md`

## Goal

Build the evidence ledger and turn verified claims into events, so M5 (first radar, several
clients) can rely on them.

- Every fact becomes a `claims` row linked to a `documents` snapshot. Code finds `source_quote`
  in `documents.text` **before** any LLM support check.
- Unverified claims are stored with a reason, are never read by consumers, and no event is ever
  built from them (CLAUDE.md #2). Every field an event carries (date, subject, country, slots) must
  itself be grounded in a verified quote.
- Verified claims are normalized into events with a generic level-0 type, a stated date, an
  `available_at`, a concept from the seeded tree, a dedup cluster and an idempotency fingerprint.
- One engine for any lens and any industry: concepts, event types and source rules are data
  (rule #1, D33). All LLM calls go through `brain/llm.py` with untrusted text fenced; tests replay
  recorded calls offline, independent of `.env`.

## Preconditions for approving this board

1. **Orchestrator commits the PF1 research note** (currently `??` in git) to `main` and appends a
   one-line pointer to it in `nebius-token-factory-api-surface-and-client.md`, before the T4.0
   worktree is created.
2. **Founder answers Q1 (D46) and Q2 (D45)** below. If Q1 is "no", T4.2 and T4.5 change only in
   that the structured path calls the support check (`support=True`); no contract changes.
3. **The orchestrator writes D45-D54** into `docs/DECISIONS.md` and the parked items into
   `docs/LATER.md` before wave 1. No ticket writes those files.
4. **Mechanical check (FACTORY §2 rule 9)** on the T4.0 branch: `uv run pytest -m "not live and
   not db"` and every failure is in a T4.0-owned file; `scripts/gate.py` green.
5. **PF1b (orchestrator, on the T4.0 branch, before merge)**: one strict json_schema call per
   frozen schema (`ExtractionOutput`, `SupportOutput`) on the fast tier, `reasoning_effort: none`,
   including one input where a nullable field should come back `null`. About $0.0002. Result
   appended to the PF1 note. If any keyword is rejected, T4.0 changes the model (not llm.py) until
   only accepted keywords remain.
6. **Production at 0005 before recording.** `claims` must be empty at 0004 (it is: no code writes
   it); the migration itself refuses to run if rows exist.

## Waves

| Wave | Tickets | Why here |
|---|---|---|
| - | commit PF1 note; DECISIONS/LATER entries | gates the build |
| 0 | **T4.0** contracts: migration 0005, models, settings, LLM output schemas, skeletons, `client_override`, invariant rules, DDL test ownership | everything else depends on these shapes |
| - | PF1b on the T4.0 branch; mechanical check | confirms the frozen schemas live |
| 1 | **T4.1** LLM record/replay + `record-llm` · **T4.2** quote check + verifier · **T4.3** extraction (LLM + structured) · **T4.4** ledger store (db) | disjoint writes; each needs only wave 0 |
| 2 | **T4.5** concepts, clustering, grounding, `build_evidence` / `process_document` | needs T4.2, T4.3, T4.4 |
| - | **orchestrator:** `migrate` production to 0005; `tasks.py record-llm -- --yes` (under $0.05); read the recordings by eye; commit `tests/fixtures/llm/ledger/` | only the orchestrator has `.env` and network |
| 3 | **T4.6** recorded-replay evidence suite, invariant/ordering checks, golden quote-check set (test engineer) | needs the recordings and every module |

Seven tickets. Write scopes inside each wave are disjoint (checked: wave 1 = `brain/replay.py`,
`scripts/record_llm_fixtures.py`, `scripts/tasks.py` | `radar/quote_check.py`, `radar/verify.py`,
`claim_support.v1.md` | `radar/extract.py`, `radar/structured.py`, `evidence_extract.v1.md` |
`core/ledger.py`, plus each ticket's own test files).

### Changes from the draft (critique and research)

- **Structured quote mode (blocking).** Many TED rendered lines are shorter than 20 characters
  (`CPV: 45233000`, `Buyer country: DEU`). `find_quote` now has two modes: `extracted` (normalized
  exact match, then fuzzy at >= 0.95, minimum 20 characters) for LLM drafts, and `structured`
  (the quote must equal one whole line of `documents.text` exactly; no normalization, no fuzzy, no
  minimum) for structured records. `verify_claims(mode=structured)` refuses any document whose
  eligibility is not `structured`. T4.3 tests every structured draft with a whole-line stand-in
  check; T4.6 runs the real `find_quote`. Recorded in D46/D48.
- **Event idempotency (blocking).** `events.fingerprint text NOT NULL UNIQUE` in 0005 =
  sha256 of (event_type, sorted claim fingerprints, occurred_on, subject key). `save_events` uses
  `ON CONFLICT (fingerprint) DO NOTHING`. db tests: save twice inserts 0; `process_document` twice
  leaves both row counts unchanged.
- **Grounded event fields (blocking).** `ground_event` (T4.5) keeps an extractor-given date,
  subject name, country and string slot value only if it appears (after `normalize_text`, case
  folded) inside the `source_quote` of one of that event's verified claims; otherwise the field is
  dropped (`occurred_on=None`, `subject=None`, slot removed). A country is kept only if its ISO2
  code or `iso2_to_name` appears. `events.description` is composed **by code** from event_type, the
  grounded subject and the verified claim statements; it is never LLM free text. Recorded in D50.
- **Env-independent replay (blocking).** Each recording file stores the model id per tier, the
  max_tokens settings that shape its requests, and `recorded_at`. `brain.replay.replay_environment(recording)`
  pins `MODEL_*` and test budget caps (env vars + `get_settings.cache_clear()`, restored on exit).
  A test proves replay passes with no `.env` and with a different `MODEL_FAST` in the environment.
- **Schema keywords (should-fix).** A T4.0 test walks both output schemas and allows only the
  confirmed keywords: `type, properties, required, items, $defs, $ref, enum, maxItems, anyOf
  (with null), additionalProperties, title, default`. So output models carry **no docstrings and
  no `Field(description=...)`** (Pydantic would emit `description`), and ISO2/snake_case checks
  stay in code, never `pattern`/`minLength`. PF1b re-runs the probe on the real schemas.
- **PF1 note location (should-fix).** T4.0 reads the PF1 note by its real name; the orchestrator
  commits it first.
- **Invariant rules narrowed (should-fix).** Rule (b) scans `northvaine/**/*.py` except
  `core/ledger.py` with the case-sensitive pattern `\b(FROM|JOIN|INTO|UPDATE)\s+claims\b`
  (migrations, schema.sql and tests are out of scope). Rule (c): `ClaimRow` may be imported only in
  `core/models.py` and `core/ledger.py`. Planted violations for both.
- **Clustering (should-fix).** Events without an embedding (structured records) share a cluster
  deterministically on (event_type, group_key), or (event_type, subject key, date window).
  `events_for_clustering` takes `as_of` (filters `available_at <= as_of`, excludes NULL when set).
- **Workspace scope (should-fix).** `verified_claims(..., workspace_id=None)` returns public claims
  (`workspace_id IS NULL`) plus, when given, that workspace's private ones.
- **Document-only event types (should-fix).** Setting `extract_excluded_event_types` (default
  `reorder_due, quote_stale, inbound_question`) removes internal-state types from the extractor
  prompt; a returned excluded type is dropped.
- **Eligibility by source, fail-closed (nit).** Setting `evidence_source_rules` (data):
  `ted -> structured`, `website -> full_text`, `tavily -> raw_only` (full text only when
  `meta.text_kind == 'raw'`). Any other source, or any other text_kind, is a lead.
- **Empty claims at 0005 (nit).** The migration docstring states it; the upgrade raises a clear
  error if `claims` has rows.

## Frozen contracts

Wave 0 lands these. *(impl)* = fully implemented in T4.0; everything else is a signature with a
docstring and a `NotImplementedError` body, implemented by the named ticket. Contract tests check
shape only and never assert that a stub raises.

```
migration 0005_evidence_ledger (T4.0), down_revision 0004, exact-reverse downgrade
  claims   + status text NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','verified','quote_not_found','quote_too_short',
                                 'unsupported','ineligible_document'))
           + meta jsonb NOT NULL DEFAULT '{}'
           + fingerprint text NOT NULL, CONSTRAINT claims_fingerprint_key UNIQUE (fingerprint)
           + CONSTRAINT claims_verified_status CHECK (verified = (status = 'verified'))
           + CONSTRAINT claims_verified_complete CHECK (NOT verified OR (quote_offset IS NOT NULL AND verified_by IS NOT NULL))
           + INDEX claims_document (document_id)
  events   + available_at timestamptz, + description text, + embedding vector(1024) (no index),
           + fingerprint text NOT NULL, CONSTRAINT events_fingerprint_key UNIQUE (fingerprint)
           + INDEX events_type_occurred (event_type, occurred_on)
  VIEW verified_claims AS SELECT c.*, d.available_at, d.workspace_id
           FROM claims c JOIN documents d ON d.id = c.document_id WHERE c.verified
  upgrade first: raise if claims or events has rows (both are empty at 0004)

core/settings.py (T4.0, impl)
  quote_min_chars=20, quote_match_min_ratio=0.95 (0<x<=1), extract_max_doc_chars=12000,
  extract_max_claims=8, extract_max_tokens=1500, support_max_tokens=600,
  concept_match_min_cosine=0.80, event_cluster_min_cosine=0.85, event_cluster_window_days=30,
  extract_excluded_event_types=("reorder_due","quote_stale","inbound_question"),
  evidence_source_rules={"ted":"structured","website":"full_text","tavily":"raw_only"}

core/models.py (T4.0, impl)
  ClaimStatus(StrEnum)  pending, verified, quote_not_found, quote_too_short, unsupported, ineligible_document
  ClaimRow  += status: ClaimStatus, meta: Json, fingerprint: str
  EventRow  += available_at: datetime | None, description: str | None, embedding: list[float] | None, fingerprint: str
  EvidenceKind(StrEnum)  structured, full_text, lead
  QuoteMode(StrEnum)     extracted, structured
  Eligibility        kind: EvidenceKind, reason: str | None
  EvidenceDocument   id: UUID, source_name: str, url, title: str | None, text: str,
                     available_at: datetime | None, workspace_id: UUID | None, group_key: str | None, meta: dict
  SubjectMention     name: str, country: ISO2 | None, role: str (snake_case)
  ClaimDraft         statement, source_quote, subject: SubjectMention | None, extracted_by: str, meta: dict
  QuoteMatch         found: bool, offset: int | None, length: int | None, ratio: float,
                     method: Literal['exact','line','fuzzy'] | None, reason: ClaimStatus | None
  ClaimCheck         document_id, draft: ClaimDraft, status: ClaimStatus, quote_offset: int | None,
                     verified_by: str | None, fingerprint: str ; property verified -> status == verified
  EventDraft         event_type: str, claim_indices: list[int], subject: SubjectMention | None,
                     date_text: str | None, occurred_on: date | None, group_key: str | None,
                     slots: dict, concept_label: str | None, concept_hint: str | None
  ConceptAssignment  concept_id: UUID | None, parent_id: UUID | None, level: int, label: str,
                     description: str, status: str, is_new: bool, embedding: list[float] | None
  ClusterCandidate   event_id: UUID | None, cluster_id: UUID, event_type: str, occurred_on: date | None,
                     subject_key: str | None, group_key: str | None, embedding: list[float] | None,
                     available_at: datetime | None
  PendingEvent       event_type, claim_fingerprints: list[str], occurred_on, available_at, subject,
                     description: str, embedding: list[float] | None, concept: ConceptAssignment,
                     cluster_id: UUID, slots: dict, details: dict, fingerprint: str
  NewEvent           as PendingEvent but claim_ids: list[UUID] and concept_id: UUID | None (what save_events takes)
  VerifiedClaim      id, document_id, statement, source_quote, quote_offset: int, verified_by: str,
                     available_at: datetime | None, workspace_id: UUID | None, meta: dict
  LedgerResult       document_id, eligibility: Eligibility, checks: list[ClaimCheck],
                     events: list[PendingEvent], llm_calls: int

brain/errors.py (T4.0, impl)   LlmReplayMismatch(AssertionError)
brain/llm.py   (T4.0, impl)    client_override(client) -> ContextManager   # ContextVar; get_client() checks it first

brain/replay.py (T4.1)
  LlmExchange        kind: Literal['chat','embed'], key: str, prompt_version: str | None,
                     request: dict (normalized), response: dict
  LlmRecording       recorded_at, models: dict[str, str] (tier -> id), settings: dict (max_tokens etc.),
                     exchanges: list[LlmExchange]
  normalize_body(body: dict) -> dict          # fence nonces -> fixed token
  exchange_key(kind: str, body: dict) -> str  # sha256 of canonical JSON of the normalized body
  load_recording(path) -> LlmRecording ; save_recording(path, recording) -> None
  class ReplayClient(recording)               # .chat.completions.create / .embeddings.create; miss -> LlmReplayMismatch
  class RecordingClient(inner)                # .recording(models, settings) -> LlmRecording
  replay_environment(recording) -> ContextManager   # pins MODEL_* and budget caps, restores on exit

radar/quote_check.py (T4.2)
  normalize_text(text: str) -> str            # NFKC, curly quotes, dashes, whitespace
  find_quote(text, quote, *, mode=QuoteMode.extracted, settings=None) -> QuoteMatch
  quote_contains(quote: str, fragment: str) -> bool   # normalized, casefolded substring (grounding)

radar/verify.py (T4.2)
  SupportVerdict(index: int, supported: bool) ; SupportOutput(verdicts: list[SupportVerdict])   (T4.0 impl, frozen)
  is_evidence_document(doc: EvidenceDocument, settings=None) -> Eligibility
  claim_fingerprint(document_id: UUID, statement: str, source_quote: str) -> str
  async verify_claims(doc, drafts, *, run, mode=QuoteMode.extracted, support=True,
                      session=None, settings=None) -> list[ClaimCheck]

radar/extract.py (T4.3)
  ExtractedClaim, ExtractedEvent, ExtractionOutput                                              (T4.0 impl, frozen)
  document_event_types(concepts: list[EventConceptRow], settings=None) -> list[EventConceptRow]
  async extract(doc, concepts, *, run, session=None, settings=None) -> tuple[list[ClaimDraft], list[EventDraft]]

radar/structured.py (T4.3)
  structured_evidence(doc: EvidenceDocument) -> tuple[list[ClaimDraft], list[EventDraft]] | None

radar/concepts.py (T4.5)
  cosine(a, b) -> float
  assign_concept(draft: EventDraft, embedding, concepts, *, settings=None) -> ConceptAssignment
  assign_cluster(new: ClusterCandidate, existing: list[ClusterCandidate], *, settings=None) -> UUID
  async seed_concept_embeddings(session, *, run) -> int

radar/ledger.py
  evidence_document_from_row(row: DocumentRow, source_name: str) -> EvidenceDocument          (T4.0 impl)
  evidence_document_from_sensor(doc: SensorDocument, *, document_id: UUID | None = None)
      -> EvidenceDocument   # id defaults to uuid5(NAMESPACE_URL, content_hash)              (T4.0 impl)
  event_fingerprint(event_type, claim_fingerprints, occurred_on, subject_key) -> str          (T4.0 impl)
  ground_event(draft: EventDraft, checks: list[ClaimCheck]) -> EventDraft | None              (T4.5)
  describe_event(event_type, subject, statements) -> str                                      (T4.5)
  async build_evidence(doc, concepts, recent_events, *, run, session=None, settings=None) -> LedgerResult   (T4.5)
  async process_document(session, doc, *, run, as_of=None, settings=None) -> LedgerResult                 (T4.5)

core/ledger.py (T4.4)
  UnverifiedClaimError(ValueError)
  async save_claims(session, checks: list[ClaimCheck]) -> dict[str, UUID]          # fingerprint -> id, idempotent
  async verified_claims(session, *, document_ids=None, as_of=None, workspace_id=None) -> list[VerifiedClaim]
  async load_concepts(session, *, statuses=("active","proposed")) -> list[EventConceptRow]
  async ensure_concept(session, assignment: ConceptAssignment) -> UUID              # idempotent on (parent_id, label)
  async set_concept_embedding(session, concept_id, embedding) -> None
  async save_events(session, events: list[NewEvent]) -> dict[str, UUID]             # fingerprint -> id; ON CONFLICT DO NOTHING
  async events_for_clustering(session, *, event_type, occurred_from, occurred_to, as_of=None, limit=200)
      -> list[ClusterCandidate]

scripts/check_invariants.py (T4.0, impl)
  (a) banned terms in northvaine/brain/prompts/*.md
  (b) `\b(FROM|JOIN|INTO|UPDATE)\s+claims\b` (case-sensitive) in northvaine/**/*.py except core/ledger.py
  (c) `ClaimRow` imported only in core/models.py and core/ledger.py
```

### Pipeline (T4.5), per document

```
eligibility = is_evidence_document(doc)
lead        -> LedgerResult(eligible kind=lead, reason), no claims, ZERO LLM calls
structured  -> structured_evidence(doc); verify_claims(mode=structured, support=False);
               no LLM, no embedding; concept = level-0 seed for event_type; cluster by (type, group_key)
full_text   -> extract (1 fast call) -> verify_claims (code quote check; 1 batched fast support
               call over passing quotes only) -> for each EventDraft: drop if no verified claim;
               ground_event; describe_event (code); embed description (1 call); assign_concept;
               assign_cluster; event_fingerprint; available_at = doc.available_at
process_document: load_concepts + events_for_clustering(as_of) -> build_evidence ->
               save_claims -> ensure_concept for new concepts -> save_events (refuses unverified)
```

## Decisions proposed (orchestrator writes them to DECISIONS.md before wave 1)

- **D45** A document is evidence only by an explicit, data-driven source rule
  (`evidence_source_rules`): `structured` (TED), `full_text` (website), `raw_only` (Tavily with
  `text_kind='raw'`). Everything else, including snippet-only results and unknown sources or
  text kinds, is a **lead**: no extraction, no claims, no LLM spend (fail-closed). M5's discover
  stage upgrades a lead by fetching the publisher URL through `safe_fetch` into a website document.
- **D46 (founder Q1)** Structured official records (TED, D39 rendering) yield claims and events
  by code. `source_quote` is one exact rendered line, the statement is a generic template over the
  same field, the quote check is a whole-line exact match, and `verified_by='code'`. No LLM
  extraction or support check.
- **D47** Extraction and normalization are one fast-tier call per full-text document. The support
  check is one fast-tier call per document, batching only claims whose quotes passed; it sees
  statements and quotes only (no document, no goal), all fenced. A missing verdict = unsupported.
- **D48** Quote check, extracted mode: NFKC + quote/dash/whitespace normalization, exact match
  first, then a stdlib `difflib` window fallback at ratio >= 0.95, minimum 20 characters.
  Structured mode: exact whole-line match, no minimum. `quote_offset` indexes the original
  `documents.text`. No new dependency.
- **D49** Every extracted claim is stored with a status (verified or a rejection reason) to measure
  extraction precision. Consumers read only the `verified_claims` view. CHECKs tie `verified` to its
  status and require `quote_offset` and `verified_by`. `check_invariants` forbids SQL on claims and
  `ClaimRow` imports outside `core/ledger.py`. `save_events` refuses unverified claim ids.
- **D50** The LLM never decides a fact on an event. Dates are written text parsed by code
  (`sensors.dates.parse_date`), and every event field (date text, subject, country, string slots)
  is kept only if it appears in a verified quote of that event; otherwise it is dropped. The event
  description is composed by code from verified statements. `available_at` = the latest
  `available_at` of its claims' documents (in M4: its document's).
- **D51** Concepts: the extractor picks the level-0 type from the seeded labels (data, minus
  `extract_excluded_event_types`). Level 1 = nearest child at cosine >= 0.80, else a `proposed`
  child named by the extractor (its first event's embedding seeds it). Dedup: events share a
  cluster when type matches, subject key or group_key matches, the date window holds, and cosine
  >= 0.85; events without embeddings cluster deterministically on (type, group_key) or (type,
  subject key, window). Candidates are filtered by `as_of`. Thresholds are settings in M4.
- **D52** Migration 0005 as in the frozen contracts (claims status/meta/fingerprint and two CHECKs;
  events available_at/description/embedding/fingerprint; the `verified_claims` view). Events are
  idempotent on `fingerprint`.
- **D53** LLM fixtures are recorded only by the orchestrator (`tasks.py record-llm`) through
  `llm.client_override` + `RecordingClient`, redacted with `smoke_llm.redact`, never hand-edited.
  Replay is keyed by sha256 of the nonce-normalized request body (a prompt change needs a
  re-record) and pinned to the recorded model ids by `replay_environment`. Vectors stored rounded
  to 6 decimals.
- **D54** Entity resolution is deferred to M5. Subjects are stored as mentions (name, ISO2 country,
  generic role) in `claims.meta` and `events.slots`; `company_id` stays NULL in M4.

## How the invariants are kept

- **#1 nothing hardcoded:** event types come from `event_concepts` rows; source rules and excluded
  types are settings data; prompts are scanned for banned terms (new rule a); T3.6's AST literal
  check stays green over `radar/`.
- **#2 no source, no claim:** the code quote check runs before any LLM; only `verified_claims` is
  read; CHECKs make an incomplete verified row impossible; `save_events` refuses unverified ids;
  `ground_event` drops any event field not in a verified quote; leads produce nothing.
- **#4 skeptic** is M5's (case level); M4 stores rejection reasons that the skeptic can use.
- **#7 untrusted content:** document text, title, url, statements and quotes are all fenced; the
  support check never sees the document; an injected-instruction page is a named test (T4.3, T4.6).
- **#8 all LLM via llm.py:** extract and verify call `complete_json`/`embed` only; tests swap the
  client through `client_override`, never the SDK.
- **Replay (ARCH §11):** `verified_claims(as_of)` and `events_for_clustering(as_of)` filter on
  `available_at`; NULL is excluded when `as_of` is set.
- **No secrets/PII:** recordings pass `smoke_llm.redact`, the recorder refuses on a surviving
  secret/email/phone, and the orchestrator reads them before committing.

## Risks

1. **Thin LLM evidence.** Only 4 Tavily documents are full text (about 1,500 characters each) plus
   the 3 synthetic web pages. The packaging client has none, so its M4 demo shows leads only.
   M5 must add full-text documents (lead upgrade, re-recording the 3 refused queries).
2. **Schema keywords.** Pydantic may emit a keyword nobody tested (`description`, `format`,
   `const`). Mitigation: the keyword allow-list test in T4.0 and PF1b on the real schemas.
3. **Cosine thresholds** (0.80 / 0.85) are guesses for Qwen3-Embedding-8B at 1024 dimensions.
   They are settings; T4.6 prints the distributions; the orchestrator tunes before M5.
4. **Fuzzy false positives** at 0.95 on short or boilerplate quotes. Mitigation: exact first,
   20-character minimum (extracted mode), offsets into the original text, golden near-misses.
5. **Brittle replay keys:** any prompt or max_tokens change invalidates its recordings. Intended
   (SPEC §12); each prompt edit after recording costs an orchestrator re-record (under $0.05).
6. **Grounding drops useful fields.** An LLM that paraphrases dates ("last March") loses
   `occurred_on`. Accepted: a missing date is honest; an invented one breaks rule #2.
7. **T4.0 size.** Migration, models, settings, two frozen output schemas, eight skeleton modules,
   the llm.py hook, three invariant rules and all DDL test ownership. The mechanical check and
   PF1b are preconditions of merge. Twice in M2 a missed test ownership blocked a whole wave.
8. **Recording depends on production at 0005** (llm_calls ledger for the budget caps). Wave 3
   waits for migrate, record, a by-eye review and a commit.
9. **No entity resolution:** `company_id` stays NULL; M5's gate and brief must add the
   award -> winner -> company hop (D20) and must not assume `company_id`.
10. **Private documents and events.** `events` has no `workspace_id`; M4 only processes public
   documents. Private-document events are parked (see below) and `process_document` refuses a
   document with `workspace_id` set.
11. **Schedule:** about one milestone behind. Cut order if late: proposed child concepts (keep
   level-0), then embedding-based clustering (keep deterministic), then golden set size. Never cut:
   the code quote check before the LLM, the verified-only read path, grounding, and the
   `save_events` refusal of unverified claim ids.

## Questions for the founder

**Answered 4 Oct 2026:** Q1 = yes (D46, code-only for structured records). Q2 = yes (D45, snippets are leads).

1. **Code-only verification for structured official records (D46).** SPEC §5 says the code quote
   check is followed by a fast-model yes/no support check. For TED notices the statement is a
   template over the same field the quoted line renders (D39), so there is nothing for an LLM to
   interpret. I recommend `verified_by='code'` with an exact whole-line quote match and no LLM.
   That keeps the TED pricing-window stream at zero LLM cost and deterministic; full-text documents
   still get both checks. OK to record this as a spec change? (Alternative: run the support check on
   them too, well under $0.01 for the fixtures, but slower and adds nothing.)
2. **Snippet-only results are leads, not evidence (D45).** Rule #2 cannot be met from a third
   party's excerpt, so 9 of 13 Tavily results, and all 3 for the packaging client, produce no claims
   in M4. In M5 the discover stage fetches the publisher page through `safe_fetch` (robots.txt, deny
   list) and verifies claims against that snapshot. Please confirm.

## Parked (orchestrator copies to docs/LATER.md)

- Entity resolution of subject mentions to `companies` rows; the award -> winner hop (D20): M5.
- Upgrading leads by safe-fetching the publisher page into a website document: M5 discover.
- Re-recording the 3 refused Tavily queries; more full-text announcement documents: M5.
- Events from private (workspace) documents: an `events.workspace_id` column and scoped reads.
- Chunked extraction for documents longer than `extract_max_doc_chars`; `document_chunks`
  embeddings and the SPEC §5 "match" stage.
- Ledger and concept thresholds in `policy_params` with update rules; concept split/merge by
  usefulness; promoting proposed concepts to active; an LLM concept-naming pass.
- Batch embeddings (a list input) in `llm.embed`; an HNSW index on `events.embedding`.
- Multi-document event `available_at` (latest of its claims' documents) once events merge across
  documents.
- Source-reliability updates from verification failures and "wrong fact" feedback (W learner, M7).
- Retention for claims and documents (180 days unless referenced, SPEC §11).
- Distillation dataset export of verified claims and support verdicts.
- Gate persistence of rejected sellers with `rejected_as`: M5.

## Tickets

| id | title | wave | role | depends_on |
|---|---|---|---|---|
| T4.0 | Ledger contracts: migration 0005, models, settings, LLM schemas, skeletons, client override, invariant rules | 0 | builder | - |
| T4.1 | LLM record/replay client, replay environment and the record-llm recorder | 1 | builder | T4.0 |
| T4.2 | Quote check and verifier: code check first, then a batched LLM support check | 1 | builder | T4.0 |
| T4.3 | Extraction: LLM extractor for full-text documents, code-only evidence from structured records | 1 | builder | T4.0 |
| T4.4 | Ledger store: idempotent claims and events, verified read path, concepts (db) | 1 | builder | T4.0 |
| T4.5 | Concepts, clustering, event grounding and the build_evidence / process_document pipeline | 2 | builder | T4.0, T4.2, T4.3, T4.4 |
| T4.6 | Recorded-replay evidence suite, invariant/ordering checks, golden quote-check set | 3 | test-engineer | T4.1, T4.5 |
