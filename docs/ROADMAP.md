# Northvaine roadmap (proposed by the CTO, 5 Oct 2026; the founder decides)

**Roles:**
- **Claude** (CTO, core engineer) builds.
- **ChatGPT** (CEO) handles strategy, go-to-market and reviews.
- **The founder** decides. Every phase ends at a decision gate.

**Product:** a B2B buying-signal radar. Wherever one business sells to another, it finds the
organisations that are about to buy, when, with every fact proven by its source. It is one
general engine with nothing hard-coded per industry.

**Business:**
- **Agency service** (now): done-for-you weekly buyer briefs for Indian B2B exporters, stone
  first.
- **SaaS** (from about Dec): a high-paying, early-adopter niche abroad. The first candidate is
  companies selling into the UK, EU and US public sector. The engine is built so that GTM teams
  can use it through an API.

---

## Phase 0: Hackathon version (now to about 15 Oct; submit by 29 Oct)

| # | Build (Claude) | Why |
|---|---|---|
| 0.1 | **M5.1 brief quality** (T5.8): stated vs inferred requirement, who really buys per stage, a short list, a one-screen summary, actions per stage, deadlines too close demoted | Briefs move from 4-5/10 to sendable |
| 0.2 | **UK tenders** (Find a Tender, free official API) | UK buyers for exporters; covers the EU + UK |
| 0.3 | **Private projects, step 1**: fetch full articles behind news leads; trade-press and newsroom watch as per-client data | Hotels, developers and brands, not only governments |
| 0.4 | **A minimal learning loop**: the owner's feedback ("not relevant", "already knew", "acted") changes the next run's queries and ranking | Real proof of "adapts to your business" |
| 0.5 | **A simple web app**: leads, case file, feedback buttons | A public demo URL is required |
| 0.6 | **Deploy on Nebius**, README, licence, history secrets scan, Nebius/NVIDIA feedback section | Required for submission |

**Founder and ChatGPT, in parallel:**
- reach 5-10 stone exporters with discovery conversations;
- hand-research leads with every link checked;
- log the anonymised feedback in `docs/COLLAB.md`;
- record the 3-minute video in the last week.

**Gate 0 (about 15 Oct):**
- the founder rates the new briefs: at least 3 entries "yes" on all four, per test client;
- the head-to-head (our brief vs manual ChatGPT research, same exporter, same week) shows ours
  at least equal on verified, new and actionable leads.

**Deferred from the original plan (founder to confirm):**
- the full four learners and the attention allocator;
- missed-opportunity post-mortems;
- the Gateway.

These are built after the hackathon, on real outcome data.

## Phase 1: Design partners (Nov)
- 3-5 exporters receive weekly briefs, delivered by hand through the agency.
- **Claude:**
  - sets up each radar;
  - records every lead's outcome (ignored, contacted, quoted, won);
  - fixes quality problems first.
- **Founder and ChatGPT:** run the relationships and test price points.
- **Gate 1:** at least 1 lead acted on per brief on average, and at least 2 partners willing to pay.

## Phase 2: Learning and coverage (Nov-Dec)
- **Learning:**
  - a "your business" learner, from corrections;
  - a buying-pattern learner once there are about 20-30 outcomes;
  - replay proof that the radar improves week over week.
- **Coverage:**
  - US SAM.gov (federal);
  - UK Companies House and US SEC filings;
  - job feeds;
  - US city building permits (open data);
  - Account Watch: watched target accounts with change alerts.
- **Gate 2:** paying partners retained after month 2, and cost per useful lead still in cents.

## Phase 3: SaaS beta for foreign early adopters (Dec-Jan)
- **Validate the niche first:** ChatGPT runs 5-10 conversations with UK and EU companies that bid
  on public tenders, covering how they find them, what they pay and what is missing.
- **Product:**
  - self-serve onboarding chat ("what creates demand for you?");
  - accounts and data isolation;
  - email, Slack and CRM delivery;
  - an API for GTM teams;
  - a connector for Claude and ChatGPT (MCP).
- **Business:** subscription pricing, set from Phase 1 evidence.
- **Gate 3:** 5-10 paying SaaS customers.

## Phase 4: Expand (2027)
- More industries and markets, each one opened by new data sources, never by code per industry.
- The Gateway: making clients findable by buyers and their AI agents.
- Paid data partnerships only where customers pull for them.

---

## What we measure from day one
- Leads acted on per brief.
- Cost per useful lead.
- Retention after 3 months.
- Our brief vs manual AI research, head to head.

## Standing rules
- No source, no claim.
- No scraping of sites that forbid it.
- Company-level signals only, never tracking of people.
- No automatic sending of outreach.
- Prospect identities stay out of the repo.
