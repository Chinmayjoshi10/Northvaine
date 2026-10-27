# Later

Ideas parked until after 30 Oct.

- Harness (SOPs, RFQs, quotes)
- Team features (territories, assignment, permissions)
- Email/Slack/Telegram/WhatsApp channels
- Apollo/Clay/customs data connectors (founder: after the hackathon, once the product is finished; company-level first, then contacts with a UK GDPR legitimate-interest assessment)
- Agent-Readiness Score web tool
- Jev or other classifier behind the decision layer

Parked from milestone 1 planning (to pick up in the milestone that needs them):
- SQLAlchemy table metadata + repository layer; versioned Pydantic payload models for JSONB
- HNSW vector indexes + EMBED_DIM ALTER (M2); /health/db endpoint + engine disposal on shutdown
- mypy in the gate; pytest-socket "no network in tests" enforcement; CI (outward-facing)
- 180-day document retention job; enum CHECKs for hypotheses.kind, messages.channel, inbound_queries.channel
- Cross-org pooling of beliefs

After the hackathon, the first new lens (docs/ARCHITECTURE.md §0.2):
- **Company watch / market intelligence:** continuously learn the operational state of
  companies from public evidence (SEC EDGAR filings and XBRL, Companies House, procurement
  awards, patents, hiring, facilities) and alert on emerging transitions and expected next
  events, personalised per analyst. Never stock-price prediction or investment advice.

Models beyond Nemotron (3 Oct):
- Distil the high-volume yes/no checks (buyer-or-seller gate, quote support, event concept,
  relevance) into a small classifier. Train it on labels the system collects (verified claims,
  gate decisions, owner ratings); switch only when it matches Nemotron on the golden set.
- JEPA-style timeline encoder (predict the next company state in representation space) as the
  world learner's predictor for the company-watch lens, once large timeline data exists.

## Scrub the database password from test failure output (confirmed real, 3 Oct 2026)

**Promoted from "nice to have" to a real finding, with evidence.** While running `db-test` during
T2.1b, a failing assertion printed the full `TEST_DATABASE_URL` - including the Neon password -
into the pytest output:

```
E  where 0 = run('postgresql://neondb_owner:npg_...@ep-....neon.tech/neondb?...', <function ...>)
```

`northvaine/core/db.py` already has `redacted()` and a scrubbing helper for its own error
messages, so the application code is fine. The exposure is pytest echoing the `migrated_url`
fixture's value in an assertion representation, which no application-side scrub can reach.

**Why it matters:** the repository history is clean (verified), so this is not a submission-
checklist failure. The risk is a human one - pasting a failing test output into an issue, a chat
or a screen share leaks a live production-adjacent credential.

**Fix when M3 touches config:** a `pytest_runtest_makereport` hook in `tests/conftest.py` that
scrubs known secrets (the API key and both database URLs) from `report.longrepr` before it is
rendered. General, one place, and it covers every future test rather than the db ones only.

Parked here rather than done in M2 because no M2 ticket owns `tests/conftest.py`, and the M2
board has already lost three build runs to tickets reaching outside their write scope.

## Distributor / channel-partner lens (validated 3 Oct 2026, build after the hackathon)

**The engine already computes this and currently throws it away.** The buyer-or-seller gate
(CLAUDE.md #3) rejects competitors and sellers of the client's own offer. A company that already
sells the client's product in a target market is exactly either a competitor **or** a channel
partner - the same classification, opposite verdict depending on the lens.

**Evidenced live, TED CPV 44912000 (stone products), award notices since Jan 2025:** 99 notices,
naming real suppliers into those markets - ARABESQUE, EUROETANS INDUSTRI, AMP GRUP, M&M FRIMAR,
TEHCOM (RO), Benders Sverige AB (SE).

**Why low volume is acceptable here, unlike the buyer lens.** A business needs five good
distributors, not six hundred leads. One channel partner doing EUR 1M a year outweighs a year of
prospecting, so a lens producing ~99 candidates a year across the EU is a result rather than a
trickle. The ROI arithmetic is different in kind from the radar's.

**Two honest limits:**
- Competitor vs. partner is a commercial judgement, not a data fact. The system can surface and
  evidence the company; the owner decides which it is. (Consistent with CLAUDE.md #5.)
- The strongest distributor signal - company-level import/customs data - is not public in the EU
  the way it is for the US or India. The EU route is award winners, company registries, trade
  fair exhibitor lists and trade press: weaker, but demonstrably non-empty.

### The one cheap thing to do *before* then

**Make the gate persist what it rejects, labelled with why.** Rejected sellers are computed
today and discarded. Keeping them - a `rejected_as` reason on the record rather than a delete -
costs almost nothing now and preserves the entire lens for later. Discarding them is
unrecoverable, the same asymmetry as `llm_calls.provider` (D15): everything else about this lens
is reversible configuration, but data never written cannot be reconstructed.

Fold into whichever milestone first implements the gate (M4/M5), as a column and a non-delete,
**not** as a distributor feature. The lens itself stays out of hackathon scope (ARCHITECTURE
§0.2: B2B radar is the hackathon product).

## Parked from Milestone 3 planning (2026-10-04)

- Find a Tender / Contracts Finder (UK) sensor: only if Q1 picks a UK-market client (then a
  wave-2 ticket); otherwise M5+.
- TED notice types beyond cn-standard/can-standard (`cn-social`, `veat`, `can-modif`, `pin-only`)
  in `TED_KIND_TO_NOTICE_TYPES`; TED ITERATION pagination; place-of-performance country filter;
  TED text (`~`) queries.
- Hourly poll to measure the TED indexing lag (D36 provisional).
- Companies House, SEC EDGAR, SAM.gov registry sensors (M4/M5 or later).
- Award winners -> `companies` rows (entity resolution, the D20 award->winner hop): M4/M5.
- Planning portals / planning.data.gov.uk (D32).
- Fetching TED notice XML/HTML for free-text scope and per-lot winners (strip contacts first).
- Tavily `/extract`; Tavily credit ledger alongside `llm_calls`.
- Archived web snapshots (Wayback) to make web documents replay-safe.
- Wiring sensors into the nightly `discover` job and per-provider concurrency caps: M5.
- Gate persisting rejected sellers with `rejected_as`: M4/M5.
- DNS pinning in `safe_fetch` (rebinding protection).


## Parked from Milestone 4 planning (2026-10-04)

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


## Parked from Milestone 5 planning (2026-10-05)

- DB persistence of radar runs: `companies` upsert by match key, `cases` (stage gated/dismissed,
  `rejected_as` column), `case_evidence` stances, `case_open_questions` (M6 case file; D61).
- LLM-assisted entity resolution for uncertain pairs; domain-based company keys; aliases across
  languages; the project graph (M6).
- Bidder inference for tenders (likely bidders = repeat winners of similar works, D19/D23 join).
- Judge (deep model), calibrated confidence, thesis weights in the ranking (SPEC §5 steps 8-9).
- SPEC §5 filter/match stages (recency drop, blocked aggregators beyond the deny list, embeddings
  match to theses); skeptic with its own search budget (ARCHITECTURE §10).
- Clients as workspaces in the database (the radar reads specs from the fixtures dir in M5).
- Tavily `/extract` instead of page fetch; Wayback snapshots for replay-safe web pages.
- Per-provider concurrency caps; Tavily credit ledger; the nightly `discover` job wiring.

- Move `radar_non_name_pronouns`, `radar_non_name_words` and `radar_name_max_words` from
  `radar/entities.py` defaults into `core/settings.py` the next time settings is touched (T5.2
  reads them as optional settings attributes already).
- Client spec flag for "the business the owner knows", so the scorecard can name that client
  without an industry word in code (T5.5 uses a generic wording).

## From the 14 Oct buyer-intent field test (D101)
- Competitors' "where to buy" / stockist pages as proven-buyer lists.
- Trade-body and embassy published buyer enquiries (stated intent for exporters).
- Watching proven buyers' websites for a new range or out-of-stock pages.
- Trade-fair exhibitor lists and new exhibitors.
- Ordering calendars per market (e.g. spring stock shipping windows).
- US shipping manifests (importer + supplier + origin): paid, needs founder approval.

## Adoption: what makes clients keep using it (14 Oct)
- Weekly WhatsApp/email digest linking into the app (optional pre-hackathon if a day frees up).
- Draft next step per taken lead from verified facts only; company-level route.
- Simple tracker per lead (contacted, sample, quote) and a results line on Station.
- One login across many clients for the agency.
- "3 accounts to work today" from the proven-buyer list.

## More signal sources (15 Oct, founder asked "where else can opportunities come from")
Industry-neutral; official APIs and public pages only; company-level facts only.
- **Proof of buying:** Canada importers database; trade-fair visitor lists.
- **Just changed:** company registers abroad with change data (France SIRENE, Belgium KBO,
  Denmark CVR, Norway Brønnøysund, Czech ARES, Slovakia, Poland KRS); company filings (growth,
  funding); job ads for buyer, purchasing and sales roles via official job-board APIs or company
  sites; press releases and trade-press RSS.
- **Stated intent:** UK Contracts Finder (below the Find a Tender threshold); SAM.gov (free
  key, founder); US city and state building permits; planning applications that name the
  product; private-sector RFQ portals.
- **Market changes:** trade deals entering into force; anti-dumping duties; insolvency notices
  (UK Gazette) of large suppliers or merchants; import statistics by origin country (Eurostat,
  HMRC OTS); port and shipping disruption.
- **The client's own world:** reorder due from a customer's past pattern; quotes gone quiet;
  lost bids whose winner fails to deliver.
- **Priority after step 1b:** Contracts Finder, job ads, insolvency notices and trade deals,
  competitors' stockist lists.
- **Added 17 Oct** (founder: "add if we got time"):
  - UK insolvency notices (The Gazette) go into hackathon step C **only if time allows**: a
    failed competitor or merchant means its customers need a new supplier.
  - Grants received (UK 360Giving, EU funding portals); filed-accounts growth; import volume
    rising or a new origin country; "out of stock" or "discontinued" on a buyer's site; product
    recall databases; buying seasons per market and the public-sector year end (UK 31 March);
    new rules that require the client's kind of product; paid customs data for the US
    (shipping manifests) and India, once revenue covers it.
  - How they fit: each is one sensor mapped to an existing event type plus a strength rule;
    web-read signals share one Tavily sensor; derived signals need no new source. Two fresh
    signals on one company beat one; each client's decisions set its own signal weights.

## Full SaaS operation (founder, 16 Oct: after the hackathon)
- Pricing page (Free / Pro / Agency), card payments, invoices and plan limits enforced per account.
- Accounts and sign-in for clients and the agency; subscriptions replace `_subscribers.txt`.
- Contact requests and trial claims in the database with an admin view and email notification.

- **Replay of recent recordings (found 27 Oct).** `scripts/radar.py` replay compares the spec's
  sensor queries with `meta.queries`, but since D126 the recording stores the expanded set (intent,
  partner and target-account searches), so a recent recording is refused as "queries differ".
  Compare against the expanded set (or record both) so a live run can be replayed after a code fix.

- **Clean-up after the hackathon (scan of 28 Oct).** Built for the full architecture but unused in
  the shipped product: about 35 table models for features not built (Gateway enquiries, messages,
  quote requests, theses, cases, beliefs, playbooks), the Postgres job queue (`core/queue.py`), the
  empty `gateway/` package, and a growing set of legacy settings pinned for old recordings. Also:
  split `radar/run.py`; add the frontend to the format check; scan the frontend for dead code.
  Remove on a branch after the submission freeze, with the gate.
