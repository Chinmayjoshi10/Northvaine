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
