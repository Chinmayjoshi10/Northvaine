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
