# Competitor methods: how others find leads and buying intent, and where we win

Checked: 2026-10-09. Researcher: Claude (factory researcher role). No code, no other files changed.

Tags: **[C]** confirmed (vendor's own page or official doc seen), **[S]** secondary (third-party review, blog or
press; credible but not verified against the vendor), **[I]** inferred by us, **[U]** unknown. Prices from
blogs are estimates, never list prices. Many comparison blogs are written by competitors; flagged where known.
The search tool returns summaries, so most "source" links are the pages the summaries came from, not pages we read in full.
Only Clay's pricing page was fetched in full.

---

## 1. Summary

- **Intent data (Bombora, 6sense, Demandbase, G2, TechTarget)** sells "this company is researching topic X" from content
  consumption. It is company-level, topic-level, probabilistic, expensive ($15k to $250k+/yr), and has no per-fact proof.
  Users call it "directional, not a crystal ball". It is built for US/EU software marketers, not exporters.
- **Contact and signal databases (ZoomInfo, Apollo, Clay, Common Room, UserGems, Koala)** sell people and contact data plus
  triggers (job change, hiring, funding, product usage). Accuracy drops outside North America. Clay is a workflow tool
  that lets the user build their own research; it proves nothing by itself.
- **Procurement intelligence (GovSpend, GovWin, Stotles, Tussell, Tendium, Mercell, BidStats, TenderTiger)** serves
  *suppliers bidding for public contracts*. Their user is the bidder. None of them found by us says "who will
  buy the material downstream of a tender" (the main contractor, the project chain).
- **Trade intelligence (Panjiva, ImportGenius, Volza, TradeInt; Kompass and Europages are directories)** shows who
  has already shipped. It is backward-looking (past shipments), not "about to buy".
- **AI SDRs (11x, Artisan, Unify, Actively AI)** automate outreach. Evidence of weak results, churn and inflated claims for
  the autonomous ones. Our rule 6 (no real sending) sidesteps this category entirely.

---

## 2. Intent data vendors

### Bombora (Company Surge)
| Item | Finding | Tag | Source |
|---|---|---|---|
| Data source | Publisher co-op: B2B media sites carry a tag and share anonymised content-consumption data in exchange for aggregated intent | S (vendor-adjacent summaries) | https://bombora.com/intent/ , https://www.consentstack.io/vendors/bombora |
| Signal to lead | Per-company weekly "Company Surge" score 0-100 against the company's own baseline; 60+ treated as a surge. Topics are Bombora's own taxonomy (counts quoted range 6,800 to 17,000, so unclear) | S | https://syncgtm.com/blog/bombora-review |
| Company resolution | IP-to-company mapping plus identity resolution, fused with behavioural signals | S | same |
| Proof shown | A score and a topic list. No document or quote per signal | I | (absence in all sources) |
| Pricing | Not published; resold inside Demandbase etc. as a separate paid licence | S | https://support.demandbase.com (summary only) |
| Weakness | Company level only, topic level only, weekly refresh (daily on a higher tier), co-op skewed to tech/marketing content | S | syncgtm review |

### 6sense
- Source: not officially confirmed in our results. Reviews say it combines third-party intent with its own signals and anonymous visitor matching. [S] https://www.trustradius.com/products/6sense/reviews
- Price: not published. Estimate $60k to $250k+/yr (one 2026 blog). [S] https://tomba.io/blog/6sense-pricing-reviews-pros-and-cons
- Weaknesses (reviews): accuracy concerns especially international and contact data; false positives (intent from people unsubscribing); steep learning curve; "directional, not a crystal ball". [S] TrustRadius, Gartner Peer Insights, G2 as quoted in the search summary.
- Proof given: scores and segments. [I]
- Reverse IP mechanics: [U] (we could not confirm). Command to confirm: read 6sense's own docs/trust page, or ask a sales rep.

### Demandbase
- Own intent comes from the ad "bidstream" (sites where ads show), plus optional Bombora, G2 and TrustRadius feeds; Bombora needs a separate paid licence. Demandbase's own claim: 3M sites and 575,000+ topics vs Bombora's 5,000 sites (March 2024). [S: one search summary of Demandbase support docs; the support page returned HTTP 403 to us] https://support.demandbase.com/hc/en-us/articles/12043605367195-Understanding-Third-Party-Intent-in-Demandbase-One
- Price: not published. Estimates $25k to $200k+/yr; one AWS Marketplace listing reportedly $215,000 for 12 months. [S] https://blog.abmatic.ai/demandbase-pricing-2026-breakdown (Abmatic is a competitor)
- Account resolution method: [U].

### G2 Buyer Intent
- Source: first-party. Companies viewing a vendor's G2 profile, comparing, reading reviews. High quality for software buying, but only for products listed on G2. [S] https://www.capterra.com/p/206208/G2-Buyer-Intent/
- Price: not published. Estimates $10k to $60k/yr, median $55k from one aggregator (4 reports). Requires a G2 seller plan as base. [S] https://www.costbench.com/software/sales-intelligence/g2-buyer-intent/
- Weakness: only works for software categories on G2; irrelevant to manufacturers and exporters. [I]

### TechTarget Priority Engine
- Source: TechTarget's own publisher audience (content consumption on its sites and gated content). Delivers prioritised accounts and contacts. [S] https://www.gartner.com/reviews/market/revenue-data-solutions/vendor/informa-techtarget/product/priority-engine
- Weakness (reviewers): signals "too broad", no role or stage context, unclear company vs person engagement. [S] G2 reviews via search summary.
- Price: not published; one unverified claim of $75k/yr start. [U/S]

### What the intent group shares (the gap)
All five report *company X is interested in topic Y*. None attaches a dated, quoted public document as proof; none gives
the project, the buyer role, or the deadline. They are blind to buyers outside tracked publisher sites (e.g. a contractor
in Dubai ordering stone). [I, from the absence in vendor descriptions]

---

## 3. Contact and enrichment databases with signals

| Vendor | Data and method | Proof given | Price | Target | Weaknesses | Tags / source |
|---|---|---|---|---|---|---|
| ZoomInfo | Contact DB + "Streaming Intent" from its publisher network; credit-based reveals | Contact record, intent topic | Not published; est. $15k to $60k+/yr, median ~$33.5k (blogs) | US mid/large sales teams | Stale job data, accuracy falls outside North America, auto-renew complaints, credits | S. https://syncgtm.com/blog/zoominfo-review , https://bouncezero.io/zoominfo-review-2026 (BounceZero sells email verification) |
| Apollo | Contact DB, 15K+ topic intent; credits | Contact record | Per seat, about $49 to $119/user/month annual (blog); real cost often 2-3x via credits | SMB outbound | Vendor claims 98% email accuracy; independent blogs say 65-88%, about 60% outside North America; Trustpilot 2.9 vs G2 4.7 | S (Apollo claim from its own comparison page: https://www.apollo.io/insights/apollo-vs-6sense) |
| Clay | Workflow spreadsheet: waterfall across data providers, plus "Claygent" web research agent, then push to CRM/outreach | Whatever the user builds; the agent output is not source-verified by default [I] | Confirmed on pricing page: Free (500 actions, 100 data credits/mo), Launch from $167/mo annual (page headline; FAQ says $185 monthly), Growth from $446/mo annual (FAQ: $495), Enterprise custom. Data credits from $0.05. Claygent and waterfalls included on all plans | Growth/RevOps teams | Credit sprawl, user must design everything, no industry knowledge supplied | C. https://www.clay.com/pricing (fetched 2026-10-09; page and FAQ disagree on figures) |
| Common Room | Aggregates website, product, GitHub, community signals; AI research agents | Signal feed | From $2,500/mo annual, 5 seats (S). One source claims Zoom announced it would acquire Common Room in July 2026 (single source, unverified) | PLG / developer-led SaaS | Needs your own first-party signals | S. https://www.11x.ai/guides/common-room-pricing (11x is a competitor) |
| UserGems | Job-change tracking of past champions, then 30+ signals | Job-change event | About $2,750 to $3,000/mo (sources conflict) | B2B SaaS | Needs a customer/champion base | S. https://gappsy.com/compare/common-room-vs-usergems/ |
| Koala | Visitor deanonymisation + product usage | n/a | Reported shut down 30 Sep 2025 after Cursor acqui-hired the team | n/a | Gone (multiple sources agree; one outdated review still lists plans) | S |

Key facts about Clay worth copying: waterfalls run all providers in order until one returns a result, and since March 2026
failed lookups are no longer charged (S: https://tomba.io/blog/clay-pricing).

---

## 4. Procurement intelligence

| Vendor | Region | Data and method | Price | Notes | Tags / source |
|---|---|---|---|---|---|
| Stotles | UK (and EU) | Notices, awards, expiring-contract forecasts, buyer and competitor intelligence, decision-maker contacts, alerts by keyword/CPV/buyer | Free tier; Basic from about £75/mo; Growth from about £475/mo; Expert custom (review site) | Built for suppliers bidding; free tier is a real wedge | S. https://www.stotles.com/ppc/tender-alert , pricing via https://www.itqlick.com (third party) |
| Tussell | UK/IE | Over 600 portals, pre-market notices, early buying signals; CPV and keyword filters | Quote only ("Talk to Sales") | Compares itself as comprehensive on awards | C for portal count (own page). https://www.tussell.com/solutions-bid-tender-coordinators |
| Tendium | Nordics | AI tender discovery, summaries, bid-writing assistant | [U] | Only a third-party page found; no primary site seen | S/U. https://checkthat.ai/brands/tendium |
| Mercell | Europe (Nordics, NL) | Tender platform with AI summarisation and better matching | [U] | Own community post confirms AI rollout in NO/SE/FI/NL | C. https://community.mercell.com/product-updates/mercell-ai-is-now-available-in-norway-sweden-finland-and-the-netherlands-159 |
| BidStats | UK | Aggregator of UK tenders | Free (5 views/day, 90-day look-back); Standard £350/yr; Pro £800/yr (3 seats); Enterprise from £5k/yr with live spend and API | Cheap | C. https://alpha-app.bidstats.uk/pricing |
| GovWin IQ (Deltek) | US federal/state | Opportunity tracking and pre-RFP intelligence | Not published; est. $200/mo for 1 user to $1,500/mo for 10 (third party) | Pre-solicitation tracking is its edge | S/U. https://www.itqlick.com/govwin-iq/pricing |
| GovSpend | US state/local | Purchase orders, vendor payments, bids obtained mainly via public-records requests (tens of thousands monthly), back to 2015, quarterly refresh | Not published | Own support page says data comes from records requests | C for method. https://support.govspend.com/data-overview-spending-pos |
| TenderTiger | India (some global) | Email and SMS alerts by business category; global RFP/RFQ listings; free registration shows samples | [U] (only a pricing tracker found) | Alerts, not analysis | S. https://pricingsaas.com/companies/tendertiger |

**Common method**: tender notice, then keyword/CPV match, then alert to a *bidder*. The user must read the notice, decide
if they fit, and guess who to call. Proof is the notice itself. Weaknesses we can infer [I]: they match on what the
authority wrote (CPV, keywords) so generic tenders flood the list; they do not identify the downstream material buyer
(the contractor), do not argue against the lead, and do not reject sellers/competitors because the user is the
*bidder*, not a supplier to the winner. TED (EU) is free and official, so raw access is not a moat.

---

## 5. Trade intelligence for exporters

| Vendor | Data | Price | Weakness | Tags / source |
|---|---|---|---|---|
| Panjiva (S&P Global) | Bills of lading, 2B+ shipment records, 21 countries, 13M company relationships | Not published [U] | Shipments are history, not intent; US customs coverage limits not independently confirmed | C for counts (S&P listing): https://marketplace.spglobal.com/en/datasets/panjiva-supply-chain-intelligence-(22) |
| ImportGenius | US import data plus other countries (incl. India, Sri Lanka, Vietnam, Pakistan, Kazakhstan); plan limits: Starter 3 months US data, 15 searches/day; Plus 12 months | Not seen [U] | Limited history on cheap tier; backward-looking | C for tiers (support/comparison page): https://support.importgenius.com/portal/en/kb/articles/what-countries-trade-data-is-available-on-importgenius |
| Volza | Shipment data; free pages show counts, buyer and supplier names paywalled | Online access from $1,500 (own site); tiers by country and searches | Own claim "100% authentic", not verified | C for price and paywall. https://www.volza.com/p/bindi/ |
| TradeInt | India bill-of-lading data, updated monthly | Not seen [U] | Full history paywalled | C for monthly update. https://tradeint.com/product/countries-covered/asia-import-export-trade-data/india-trade-data |
| Kompass | Self-reported company directory (figures conflict: 2.3M to 50M+) | [U] | Self-reported, stale risk | S. https://libguides.cbs.dk/newsletter/5426/database-kompass-easy-business |
| Europages | Supplier directory (2.2M to 3M companies, claims vary) | [U] | Directory, no timing | S. https://globaledge.msu.edu/global-resources/resource/1275 |

Method: customs records give a list of who imported what, from whom. The user infers repeat buyers. Gaps [I]: no
forward-looking trigger, India export bills of lading are often partial, and small high-ticket project buying (stone for
a hotel) is rarely visible as a repeat shipment.

---

## 6. AI SDR and research agents

| Vendor | Claim | What users and press report | Tags / source |
|---|---|---|---|
| 11x ("Alice") | Autonomous outbound with research, citations, deliverability tooling | TechCrunch (24 Mar 2025, via secondary summaries): ZoomInfo and Airtable shown as customers but said they were trial users and did not authorise logos; reported ARR counted contracts exiting a roughly 90-day break clause; an employee cited 70-80% churn, 11x said 79% retention; CEO stepped back May 2025. 11x disputed parts. | S (we did not read TechCrunch itself). https://usagepricing.com/blueprint/activity/2025-03-24-11x-customer-claims-controversy |
| Artisan ("Ava") | Autonomous SDR; says hallucination about 1 in 10,000 emails (own claim, with Anthropic) | Reviewers: bland, formulaic copy needing heavy edits; deliverability swings; $25M Series A at about $5M ARR (April 2025) | S. https://tomba.io/blog/11x-vs-artisan |
| Unify | Signals plus outbound; $20 to $60+/seat; uses 25+ signals incl. 6sense, Clearbit, Demandbase | No hard criticism found | S. https://moderninbound.com/blog/unify-vs-koala |
| Actively AI | Per-account agent watching CRM, Gong, web and third-party intent; pushes next best action. $45M Series B; customers named: Attentive, Ironclad, Ramp, Samsara | Priced from about $20k/yr (directory listing); needs clean CRM and an existing outbound motion; no independent results found | S. https://pulse2.com/actively-45-million-raised-to-scale-intelligence-led-revenue-platform-powered-by-per-account-ai-agents/ |

Category summary: echai summary says autonomous AI SDRs "have mostly disappointed" (high churn, burned domains,
inflated claims) [S] https://echai.ventures/how-founders-use-ai/sales-prospecting/should-i-buy-an-ai-sdr-or-keep-prospecting-human.
Hallucination guardrails are claimed but no vendor shows per-fact quotes checked by code [I].

---

## 7. Synthesis

### 7.1 The five gaps we can own
1. **Proof per fact.** Intent vendors give scores, SDR agents give prose. We give a quote from a dated document, string-checked by
   code before any model sees it. Directly answers the hallucination and "directional only" complaints. (Our rule 2.)
2. **Buyer-or-seller gate plus evidence against.** No competitor found rejects competitors and sellers first, or stores the
   case against the lead. Intent data cannot tell a rival from a prospect; procurement tools serve bidders. (Rules 3, 4.)
3. **Project-chain timing.** Tender tools alert the bidder to the authority's notice. Nobody found maps notice, award,
   contractor, and the moment the contractor buys materials, with the window dated by when it became knowable. This is
   the exporter's real trigger. [I, from absence in vendor descriptions; tag as unconfirmed]
4. **Cross-border exporters (India outward to EU/UK/Gulf/US).** Intent data and contact DBs are US-centred and degrade
   abroad (ZoomInfo, Apollo, 6sense all reported weaker outside North America). TED and UK tender tools are EU/UK-only
   and for bidders. Trade databases are backward-looking. No one combines official tenders in the *buyer's* country with an
   *exporter's* offer.
5. **Honest coverage and price.** Competitors are $15k to $250k/yr, sales-led, annual lock-in. We state "official registers
   complete, news partial", and can sell to an agency or small exporter at a fraction (Stotles free tier and BidStats £350/yr
   show the low end is contestable, but they sell notices, not judged leads).

### 7.2 Features worth copying
- Clay: waterfall across providers, no charge for failed lookups, and a visible credit meter (cost transparency).
- Bombora: per-account baseline ("surge vs this company's normal") for any recurring signal we collect.
- Stotles / BidStats / Tendios: alerts by keyword, CPV and buyer; a real free tier or low-cost self-serve tier; expiring-contract forecasts (recompete timing).
- Mercell/Tendium/Tendios: AI tender summaries and a go/no-go recommendation on one screen.
- UserGems: a small set of high-value triggers (job change) shown with a dated event; Common Room: one unified signal feed.
- Actively: one "next best action" per account pushed where the user already works (we give drafts, never sends).
- GovSpend: using public-records requests as a legitimate data channel (later, not hackathon scope).

### 7.3 Positioning sentence (draft)
"Northvaine tells exporters and B2B sellers who is about to buy what they sell, when, and shows the source quote for every
fact, while rejecting competitors and arguing against its own leads."

Shorter variant: "Buying signals you can check: every lead, with its source and the case against it."

### 7.4 Defensibility analysis
| Layer | Copyable? | Why |
|---|---|---|
| Data (TED, Tavily, public pages) | Easy | Official and open. Not a moat. |
| Quote verification + gates + skeptic | Medium | Easy to describe, but needs architecture discipline; incumbents have contact-data business models that benefit from unverified volume. [I] |
| Industry-agnostic generation (nothing hard-coded) | Medium | Clay-like tools could add it, but they ship blank canvases, not judged leads. [I] |
| Outcome learning (which signals turned into deals, per business) | Hard, strongest | Compounds with usage; needs founder's own agency as workspace #1. [I] |
| Distribution to exporters in India and the agency-service wedge | Medium | Relationships and local trust, not technology. |
| Price floor | Weak against Stotles/BidStats at the low end for pure alerts | Differentiate on judged leads, not alerts. |

Main risks [I]: (a) Stotles or Tussell adding downstream-buyer inference and quote proof, (b) Clay plus a good agent giving
a DIY version, (c) hyperscaler "deep research" agents commoditising web research. Mitigation: outcome data, strict
verification as a brand, and focus on the exporter and project-chain case.

---

## 8. Open questions and commands to confirm
- 6sense / Demandbase account-matching mechanics: [U]. Check vendor docs or sales demo.
- Tendium and Mercell pricing: [U]. Check each vendor site (the search tool found no primary Tendium site).
- Panjiva, ImportGenius, TradeInt current pricing and India coverage: [U]. Request trial or quote.
- Exact Clay Growth allowance: page lists $446/mo with 6K credits/40K actions while FAQ says $495; confirm at https://www.clay.com/pricing.
- TechCrunch original on 11x: read at techcrunch.com (search "11x customers ZoomInfo Airtable", March 2025); we only saw secondary summaries.
- Zoom acquiring Common Room (July 2026): single source, verify before citing.
- Actively AI pricing, and Koala shutdown details: secondary only.
- Whether any tender vendor infers the downstream contractor: absence of evidence only. Test by trial of Stotles Growth tier on one sample tender.
