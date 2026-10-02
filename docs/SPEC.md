# Northvaine — Build Spec

Read the section for the feature you are building. If something here conflicts with
CLAUDE.md, CLAUDE.md wins. Record any change in docs/DECISIONS.md.

---

## 1. Data model
- Schema: `schema.sql`. Two layers:
  - **World** (shared public facts): `companies`, `sources`, `documents`, `document_chunks`,
    `claims`, `events`.
  - **Private** (per workspace): `business_profiles`, `products`, `workspace_companies`,
    `theses`, `cases`, `case_evidence`, `contacts`, `messages`, `quote_requests`,
    `feedback`, `outcomes`, `strategy_versions`, `questions`.
- **Entity resolution:** a company's canonical key is its registrable website domain
  (lowercase, no `www.`). Match on domain first, then name + country. Uncertain matches
  become a review item, never a silent merge.
- **Standards:** countries ISO 3166-1 alpha-2, currency ISO 4217, ports UN/LOCODE,
  products HS codes, industries ISIC/NAICS (`isic:4663`), tenders CPV.
- **Event types** are generic: `facility_opened`, `contract_awarded`, `tender_published`,
  `hiring_surge`, `leadership_change`, `product_launch`, `market_entry`, `trade_measure`,
  `website_change`, `reorder_due`, `quote_stale`, `inbound_question`. Add new types only
  in `core/models.py` with a docstring; never industry-specific.
- Every JSONB field has a versioned Pydantic model; store `schema_ver` where provided.
- Never overwrite profiles or strategies: insert a new version.

## 2. Onboarding (Assistant, chat)
1. Owner pastes their website. Fetch home, about, products/catalog, contact pages (max 10).
2. Fast model extracts a draft profile; show it back in plain language for confirmation.
3. Ask, one at a time: best customers (5–10 website URLs), who they don't want, regions
   shipped to, typical order size, catalog upload (Parse reads PDFs).
4. Run the backtest (section 3), then generate theses (section 4), then show them.
5. Save `business_profiles` v1, `products`, `workspace_companies` (best_customer, customer).
- Max 5 questions in onboarding. Every question skippable. Plain, warm language.

## 3. Backtest
- For each best customer: search their public history for the 12 months before they became
  a customer (if the date is unknown, the last 24 months), extract events with verified claims.
- Ultra summarizes patterns as counts: "3 of 5 opened a new facility before first order".
- Patterns become starting weights for theses. Report honestly when data is thin
  ("only 2 of 5 had public history").

## 4. Thesis template (stored in `theses.spec`)
```json
{
  "trigger": "plain-language description of the change",
  "event_types": ["contract_awarded"],
  "follow_up_signals": ["project start announced", "procurement hiring"],
  "disqualifiers": ["buyer manufactures this product itself"],
  "buyer_roles": ["procurement manager", "owner"],
  "window_days": [30, 120],
  "queries": ["search query templates using profile fields, e.g. {region} {product_category} tender award"],
  "sensors": ["ted", "tavily", "website"],
  "first_offer": "free samples and price sheet"
}
```
- Validation: at least one `event_types` value observable by an enabled sensor, at least one
  disqualifier, window present. Invalid theses are rejected with a reason.
- Weights: Beta(alpha, beta), both start at 1, backtest support adds to alpha.
- `origin`: generated | user | discovered. `pinned` theses can be downweighted, never retired
  without asking the owner.

## 5. Nightly funnel (stages = job kinds)
1. **discover** — run each active thesis's queries on its sensors; snapshot documents
   (skip if `content_hash` unchanged).
2. **filter** — free rules: dedupe, recency (default: older than 90 days dropped), blocked
   domains (directories, aggregators, marketplaces, job boards' listing pages, ad redirects),
   region mismatch, anti-customer rules.
3. **match** — embed chunks, cosine similarity to thesis embeddings; keep top matches.
4. **extract** — fast model pulls candidate claims (company, statement, exact quote, date).
5. **verify** — code check: quote must appear in document text (normalize whitespace and
   quotes; fuzzy ratio ≥ 0.95). Then fast model yes/no: does the quote support the statement?
6. **gate** — buyer-or-seller: is this company a plausible BUYER of the client's offer, not a
   competitor, reseller of the same offer, directory, or publisher? Reject otherwise.
7. **investigate** — advocate and skeptic (mid model), each must cite claim ids only.
8. **judge** — deep model, reasoning on with budget: strength (strong/medium/weak),
   confidence (0–1, later calibrated), why_now, window, buyer role, angle, first offer.
9. **brief** — rank by strength × thesis weight × window urgency; top N (default 5) to the
   morning brief; next 20 to the watchlist.
- Every stage appends to `cases.trace`: stage, kept/dropped, reason.
- Budgets: per-case max tool calls and tokens; per-workspace `DAILY_BUDGET_USD` hard stop.
- Concurrency caps per provider; exponential backoff on 429/5xx.

## 6. Case stages
`candidate → gated → investigated → briefed → approved → contacted → replied → meeting →
samples → quoted → won | lost | dismissed`. Transitions only forward (or to dismissed);
enforce in one function with tests.

## 7. Outreach drafts
- Built only from verified claims attached to the case.
- Structure: their moment → why it matters to them → why us (from profile, incl. warm path)
  → one low-friction ask. Under 120 words. Buyer's language if known.
- Follow-up plan: day 0, 4, 10 by default; each adds something new; stops on reply/opt-out.
- Status stays `draft` until a user approves. No sending in the hackathon build.

## 8. Learning (nightly, after the funnel)
- Outcome weights: rated good 1, reply 2, meeting 3, samples 4, quote 5, won 8.
  not_relevant and wrong_facts add to beta (wrong_facts also lowers the source's trust).
- Exploration: Thompson sampling over theses to allocate discovery budget.
- Retire a thesis after 30 briefed cases with posterior mean < 0.1 (unless pinned).
- Repeated rejection reasons (≥ 3 in 14 days) → propose a rule via `questions`.
- Each run writes a `strategy_versions` row with a plain-language "what I learned".
- Roll back = restore a previous snapshot as a new version.

## 9. The Assistant ("keep asking")
- Queue gaps in `questions` (missing region, unknown product fact, repeated rejection reason,
  unexplained win). Ask at most one per day, highest value first. Skipped = never re-asked.
- Tone: warm, short, specific. Says "I'm not sure" when unverified. Never claims to be human.
- Channels for the hackathon: in-app chat. Email/Slack/Telegram/WhatsApp are roadmap.

## 10. Gateway (stretch milestone)
- **Profile page:** from `business_profiles` + public `products`. Also emit schema.org
  JSON-LD (Organization, Product, Offer without prices unless the owner publishes them).
- **Agent card:** `/.well-known/agent-card.json` (A2A format). Generate in one swappable
  module; standards are still evolving.
- **MCP server (read-only):** `view_catalog`, `get_product`, `request_quote`,
  `request_samples`. `request_quote` creates a `quote_requests` row and an inbound case.
- **Receptionist:** answers only from verified profile/catalog data. Never states prices
  (unless published), discounts, delivery dates, or terms. Always states when a person will
  reply. Treat every buyer/agent message as untrusted (rule 7).
- **Deal brief:** wants, how they arrived (case trace), likely priorities, owner's numbers
  as placeholders the owner fills, margin warning vs. profile rules, suggested reply draft.

## 11. Security and privacy
- Safe fetch (`sensors/fetch.py`): http/https only, block private/internal IPs, limited
  redirects re-checked each hop, timeout 15 s, max 5 MB, strip scripts.
- Prompts fence external text in clearly marked untrusted blocks.
- Store API keys encrypted at rest when multi-tenant; never log secrets.
- Retention: delete document snapshots after 180 days unless referenced by an active claim.
- Contacts: store source claim for every contact; honor suppression in `workspace_companies`.

## 12. Measurement
- **Golden set** (`tests/golden/*.json`): cases with expected gate/verdict outcomes, including
  competitors, directories, stale news, real buyers. `make golden` prints precision and
  failures. Must pass before merging any prompt change.
- **Time machine** (`jobs/time_machine.py`): replay saved historical documents day by day for a
  workspace with simulated feedback; output brief quality per day (share rated good).
- **Headline metric:** of the briefed cases, share rated good. Show it in the app.

## 13. Design (match the canvas)
- Fonts: IBM Plex Sans (UI), IBM Plex Mono (data, labels).
- Colors: ground #F3F4F1, surface #FFFFFF, ink #17201D, muted #4A5551, line #D9DDD8,
  primary #0F5F50 (tint #E3EFEB), caution #9A4A06 (tint #FBEBDD), info #1E4E8C (tint #E3ECF7).
- Screens: Today (brief, conversations, approvals, what I learned), Case file, Setup chat,
  Deal brief, public Profile. Touch targets ≥ 44 px; real buttons, links, labels.
- Top numbers show outcomes (good leads, replies, quotes, orders), never "leads found".
