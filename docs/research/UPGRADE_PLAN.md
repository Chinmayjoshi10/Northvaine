# Northvaine upgrade plan (from the research of 9 Oct 2026)

Written by Claude (CTO) for the founder and ChatGPT (CEO). Five research reports sit in this folder:

- [global_tender_sources.md](global_tender_sources.md): more countries
- [signal_sources_beyond_tenders.md](signal_sources_beyond_tenders.md): signals that come before a tender
- [lead_quality_techniques.md](lead_quality_techniques.md): techniques for better leads
- [competitor_methods.md](competitor_methods.md): how others do it, and our gaps
- [learning_loop_design.md](learning_loop_design.md): learning from feedback
- [graph_connect_the_dots.md](graph_connect_the_dots.md): the "connect the dots" web

Facts in those files are tagged confirmed, inferred or unknown. This plan is a recommendation.

## What the research says, in five lines

1. **We have a real gap to own.** No tool found gives proof per fact, rejects competitors, argues
   against its own leads, or follows the chain to "the winner of this contract will now buy from
   you". Tender tools serve the bidder, intent tools give unproven scores at $15k+ a year, and AI
   sales agents are reported to disappoint. (Inferred from absence. Confirm by trialling Stotles
   on one tender.)
2. **"Connect the dots" can be built on what we have.** Use one `links` table in Postgres, where
   each line is backed by verified claims. Official IDs (procedure IDs, OCDS ids, company numbers,
   LEI) join the dots, and a code check comes before any model. No graph database and no GraphRAG
   framework is needed now: they let the model invent links, which breaks our proof rule.
3. **The moat is learning, but feedback alone cannot prove it yet.** With 10–100 ratings per
   client we cannot measure a lift. The first proof is replay on public history: would we have
   flagged what was later tendered or awarded?
4. **The world is reachable with free official data.** USA (SAM.gov and USAspending), Australia
   (AusTender), Canada (CanadaBuys), one general OCDS sensor (15+ countries in Latin America,
   Africa and elsewhere), and World Bank projects, which appear *before* their tenders. India and
   the Gulf have no open API.
5. **The NVIDIA story is "Nemotron proposes, code verifies, the graph shows".** Token Factory has
   no reranker or guardrail model, and NVIDIA graph tools need our own GPUs. We use Nemotron well
   and say so honestly. The embedder is Qwen, which we disclose.

## Before the hackathon (deadline 30 Oct; about 10 build sessions)

The order matters. Items lower down are cut first if time runs short.

| # | Work | Sessions | Why now |
| --- | --- | --- | --- |
| 1 | **Finish saving runs.** The decision log records which search, source and query found each lead, and the run's events are saved. | 0.5 | Learning and the graph both need it. |
| 2 | **Graph v0: connect the dots.** See below. | 1.5 | The core thesis, and the hero of the demo and the ad. |
| 3 | **Frontend: a Mac-app feel with the live web as the hero.** `react-force-graph-2d`: dots appear, lines draw stage by stage, and clicking any line opens its quote and source. | 2 | What the judges see. Waits for the founder's references. |
| 4 | **Learning loop v0.** See below. | 2 | Our moat, and it is in the hackathon story. |
| 5 | **USA plus World Bank projects.** SAM.gov tenders and USAspending awards; World Bank projects before tenders. | 1.5 | The top market and the earliest signal. |
| 6 | **Better reach at low cost.** Queries written per client in local languages, and a cheap pre-filter before the gate. | 1 | More true buyers per dollar. |
| 7 | **Deploy on Nebius, public repo, README, video.** | 1.5 | Required for submission. |

### Graph v0 (detail)

- **Company identity first.** A `company_identifiers` table (scheme, value): TED org id, OCDS id,
  company number, VAT, LEI, domain. Companies are matched in this order:
  1. exact ID;
  2. domain;
  3. normalised name plus country (`pg_trgm`, `unaccent`).

  Embedding similarity only suggests a match. An uncertain merge goes to a person, never
  automatically.
- **A `links` table.** Each link holds from, to, a relation (vocabulary is data) and stated,
  related or inferred (as in D84). Its `claim_ids` must be verified claims. Each link carries the
  date it was true and the date we learned it. An inferred link always says so and carries a
  confidence.
- **First chains:**
  - buyer → tender → award → winners, from official procedure IDs;
  - winners → "likely to buy" suppliers, as an inferred link with its reason;
  - one company seen across EU, UK and news sources.
- **Queries:** "who buys after this award", "trace this chain with a quote per line", and
  "what is expected next".

### Learning loop v0 (detail)

- **Every rating teaches one specific thing.** "Wrong facts" lowers source trust. "Not relevant"
  lowers fit for that pattern. "Later" is about timing. No reply yet means unknown.
- **What is learned.** Simple counted beliefs per search, source, country and pattern, pulled
  toward a shared starting point. Searches are chosen partly by these beliefs (Thompson sampling)
  and always keep some exploration.
- **One exploration slot per brief.** One lead in five is chosen with known randomness. This
  gives fair, unbiased evidence about what works.
- **Proof.** Replay on public history: the new version against the last one and a fixed
  baseline. A version goes live only if it passes. Every change is a `strategy_versions` row that
  can be rolled back.
- **A simulated owner** for testing, always labelled `simulated`. It never touches a real
  client's data.

## After the hackathon (ranked)

1. Australia, Canada, then one general OCDS sensor covering many countries.
2. Earlier signals:
   - US company filings (SEC 8-K, 10-K);
   - UK planning applications (PlanIt, after licence check);
   - Companies House;
   - Tavily news mode.
3. A second fact check: does the quote truly support the statement? (a small entailment model)
4. A small research agent for the top 3–5 leads, chasing the skeptic's open questions.
5. Calibrated scores and timing ("likely to buy within N months") once outcomes exist.
6. Learning v1: pooling across clients, pairwise "A beats B" ratings, and an AI judge calibrated to
   each owner.
7. A graph server (e.g. Neo4j) only as a read copy, and only if Postgres becomes slow.

## Not doing, and why

- **Customs shipping records (ImportYeti, Panjiva):** not official, and they can contain private
  individuals' details.
- **OpenCorporates free tier:** a share-alike licence and 50 calls a day.
- **India's CPPP and GeM, UNGM, and the Gulf portals:** no open API, or terms that forbid reuse.
- **GraphRAG, LightRAG, Graphiti and Cognee as frameworks:** the model asserts links with no code
  check. We copy Graphiti's idea of two dates per link instead.
- **Self-hosted NVIDIA NIMs, cuGraph and NemoGuard:** they need our own GPUs. Not worth it for the
  hackathon.

## Decisions for the founder and CEO

1. **The exploration slot:** one of five brief slots is chosen with known randomness so the
   system can learn fairly. *Recommend yes.*
2. **Schema additions:**
   - `feedback.source` (owner, simulated or judge) and `feedback.weight`;
   - `company_identifiers`;
   - `links`;
   - optionally `pairwise_preferences`.

   *Recommend yes.*
3. **A SAM.gov API key** (free, needs a sign-up by the founder) for US tenders.
4. **Frontend references** (Mac-app style) before the frontend sessions.
5. **Rotate the Neon database password** before the repo goes public.
6. **Positioning sentence** (from the competitor research) for the CEO to test with prospects:
   "Northvaine tells exporters and B2B sellers who is about to buy what they sell, when, and
   shows the source quote for every fact, while rejecting competitors and arguing against its
   own leads."
7. **Later:** a licence check with the PlanIt operators, and free keys for Companies House and
   Adzuna.
