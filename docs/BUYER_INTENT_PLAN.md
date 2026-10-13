# Buyer intent: what the 14 Oct field test taught us, and the build plan (D101)

**Objective: tell the client who to target.** For any B2B client, each edition names the
organisations to go after, why each one now (with its source), and the route to reach it. Every
source, check and score below exists to answer that one question.

On 14 Oct 2026 we searched by hand, under Northvaine's rules, for real buyers for one
design-partner prospect, a manufacturer-exporter (the test case happened to sell building
materials to the UK, Austria and the USA). **The industry is only a lens: Northvaine is for any
B2B business, and nothing below is specific to one product.** Examples in brackets come from the
test case. We compared the result with a list made by another assistant. Client and
prospect names are kept out of this repo; the working notes are in the git-ignored `.refs/`.

## What we learned

1. **The radar was blind to an exporter's real buyers.** Its run returned public-works
   contractors only. Importers, distributors and merchants (an exporter's customers) were missing,
   and the gate rejects them by design ("reseller").
2. **Who buys depends on the client's place in the chain.** For a manufacturer-exporter a
   distributor is a buyer; for a distributor it is a competitor. This must be data per client.
3. **Buying intent is "proof they buy" + "a reason now" + "a route in".** No public source gives
   all three; joining sources does.
4. **The best proof of buying for exporters is official import records.** HMRC publishes, every
   month, the name and address of each UK company importing each 8-digit product code, with an
   open, keyless API (`api.uktradeinfo.com`). It is right: the prospect's own customers appear in
   it. It shows who, not from where; the country split comes from the same API's trade
   statistics. US shipping manifests show importer + supplier + origin, but are a paid source.
5. **"Started importing this year" is a strong signal.** A new importer is building its supplier
   list.
6. **The gate matters more than ever.** Half the raw "new importers" were not buyers (a haulier
   clearing goods for others; a machinery dealer). A company register check catches these.
7. **Supply tenders are real stated intent**, and many UK ones are below the Find a Tender
   threshold (Contracts Finder, regional portals). The client's product codes must cover every
   official code buyers use (the test case was missing one broad "construction materials" code).
8. **Signals that worked for timing:** a company starting to import; public complaints about
   supply cost or lead time; job ads for a buyer or sales team (medium strength alone); new sites
   and acquisitions; planning documents that specify the exact product; market changes (a trade
   deal entering into force, a large merchant failing, anti-dumping duties).
9. **Signals that misled:** web search dates (three "2026" finds were from 2023); generic
   searches for projects (return suppliers, not buyers); events that sound big but do not fit
   (a buyer whose own product competes with the client's; a contract for a different product
   variant than the client makes; an acquisition whose announcement says suppliers stay the
   same).
10. **Opportunities mature over weeks.** Planning approval → architect → tender or contractor →
    specification → order. Searched once, a lead is either too early or too late. Northvaine must
    watch a case and act when the missing step appears ("potential" vs "now").
11. **Project leads need a route.** An exporter cannot supply a UK council or a hotel directly;
    its importer customers can. The chain is client → its customer → the project.
12. **The client's own customers are useful three ways:** a picture of a good buyer, a list never
    to show as new, and a route for project leads (and a conflict check: a new lead next door to a
    current customer).
13. **Every claim needed its source opened.** The other assistant's list had a real top lead and
    two overstated ones (a product range and a "supplier review" not supported by the page),
    plus personal contacts. Our rules (quote check, sceptic, product fit, company-level contacts)
    caught each one.

## The plan (in order; each step ends with the field-test comparison)

**Acceptance for every step:** rerun the prospect and compare with the hand-made list in
`.refs/`, **and** run at least one client from a different industry (the existing cold-chain and
packaging test clients) to show the step is not tuned to one product. A step is done when Northvaine finds the verified leads on that list (or explains in a
logged reason why not) and adds nothing the gate or sceptic would reject.

### Step 1: buyer model + import records + company register (about 1 session)
- `ClientSpec` gains a buyer model as data: `buyer_roles` (e.g. importer, distributor, merchant,
  contractor, developer, hotel), `not_buyers` (competitors, same-level sellers), `product_codes`
  (HS/CN and CPV), `markets`, and `existing_customers` (skip list and routes).
- The gate prompt receives the buyer model: a distributor is a buyer when the spec says so.
- New sensor `hmrc.py`: per product code and month, the UK importers; first-seen month; months
  active. New lead type **proven buyer**, with "started importing this year" as a signal. Market
  split by country from the trade statistics endpoint.
- New sensor `companies_house.py`: company status, age, and activity code, to reject hauliers and
  agents and to mark new businesses. (Official API, free key: ask the founder.)
- Tests from recorded API replies; no network in tests.

### Step 2: watching over time (about 1 session)
- One **case** per situation across editions (the `cases` table already exists): updated, not
  re-found.
- Each case names what it is **waiting for** (the missing chain step) and the source that will
  show it.
- **Wake-up:** when the missing step appears, the case moves to act now and leads the edition.
- Two scores: **potential** and **now**; states **hold until …**, **too late**, **back in
  motion**; a re-check schedule per source and a retirement age.

### Step 3: timing signals and the sceptic (about 1 session)
- Trade-press feeds read directly (RSS and newest-first pages), dates from the page.
- Job ads (buyer, purchasing, sales roles) with a strength rule: new and senior and specific is
  high; junior or a likely refill is low; two signals together beat one.
- Market-change leads: trade agreements, insolvencies, duties.
- Sceptic asks two new questions: "would buying from the client compete with their own
  product?" and "is this next to an existing customer?"
- Product-fit check before scoring: the lead must need the client's product, not a neighbouring
  variant the client does not make.

### Step 4: projects routed through customers (about 1 session)
- Planning documents that specify the product (aggregated by area: demand near each importer).
- UK supply tenders below the Find a Tender threshold (Contracts Finder), with every product code
  the client's buyers use; switch on the existing Find a Tender sensor for UK clients.
- A project lead shows its route: client → the client's customer near the project → the project.

### Later (in `docs/LATER.md`)
Competitors' stockist pages; trade-body and embassy buyer enquiries; buyers' website changes (new
range, out of stock); trade-fair exhibitor lists; ordering calendars per market; US shipping
manifests (paid: founder approval).

## Rules that do not change
No source, no claim; quotes checked in code; buyer-or-seller gate first; sceptic before judge;
fetched text is data, never instruction; company-level contacts only (no personal emails or
phones, no LinkedIn scraping); official APIs and permitted pages only; no sending.

---

# Findings from the same day (recorded 14 Oct)

## Gate 0 head-to-head (ROADMAP Phase 0), first result
Same prospect, same week:
- **Northvaine's automated run:** 38 leads, all public-works contractors and council tenders.
  None would be sent to an exporter.
- **Hand search under Northvaine's rules:** 4 verified UK buyers, 1 in a second market, and 1
  live supply tender.
- **Another assistant's list of 20:** 1 strong, 2 overstated, and the rest unverified.
- **Verdict:** the rules win, and the shipped engine loses for exporters. Steps 1-4 above exist to
  close that gap; the gate is re-run after each step.

## What Northvaine can and cannot promise
- **Can, reliably:**
  - stated public intent (supply tenders, specifications in planning documents), caught within
    a day;
  - who really buys a product (official import records), about 2-3 months behind: in mid
    October the latest published month was July.
- **Can, partly:**
  - timing signals raise the odds a buyer is open now, but do not prove it;
  - expect roughly 1-3 real conversations per 10 such leads (an estimate, to be measured).
- **Cannot:**
  - see a private company's decision to switch supplier before it acts. No public source shows
    it. Only being in front of the buyer early (watching) or being found when they search
    (Gateway) catches it.
- **Volume:** for a niche exporter in one market, about 3-5 strong leads a week, not a day.
  Broad offers in many markets can reach daily volume.
- **Honest promise:** "every week: who to target, why now, and the proof; live purchases as they
  appear; we keep watching". Never "guaranteed buying intent".
- **Daily habit without padding:** "3 accounts to work today" from the proven-buyer list, plus
  strong right-moment leads weekly, plus same-day alerts when a watched case moves.

## Data sources: facts confirmed on 14 Oct
**UK HMRC trade data** (`api.uktradeinfo.com`, open, keyless, OData, 60 requests a minute):
- `/Commodity?$filter=Hs6Code eq '...'&$expand=Imports($filter=MonthId ge ...;$expand=Trader)`
  returns each importing company (name, address, postcode) per 8-digit code and month.
- There is no country or supplier per company.
- `/OTS` gives the market split by country (value, mass) per code and month, with flow types 1
  and 3 for imports.
- Names are suppressed when there are few importers.
- Coverage: non-EU trade from 2016; GB-EU importers from 2022.
- **Validated:** the prospect's own known customers appear, importing monthly.
- In the test, 162 companies imported both of the client's product families in 2026, and 66 were
  new in 2026. Of 4 new ones checked, 2 were not buyers (a haulier, a machinery dealer).

**Other sources:**
- **Companies House:** official API (free key) for status, incorporation date and activity
  code. The search pages confirmed a 2024-incorporated distributor and a 1960 haulier.
- **The UK Trade Tariff site** blocks automated reading (HTTP 403). Use its API for duty rates.
- **UK tenders below the Find a Tender threshold** reach aggregators (Contracts Finder and
  similar) and were missed by our sources.
- **Planning documents:** hosted on council portals and aggregators. One landscape specification
  named an exact product, size and colour. A single scheme is too small for an exporter;
  summed by area it is demand for the importers serving that area.
- **US shipping manifests** show importer + supplier + origin, but are paid.
- **Most EU countries** publish no importer lists.

## Who our real clients are (from what the architecture is good at)
- **Best fit:** owner-led B2B companies (roughly 10-200 staff, 1-5 sellers, no research team)
  that win repeat, high-value business from organisations whose buying shows in public records.
  1. Manufacturers and exporters selling to importers and distributors, strongest into the UK
     and US.
  2. Suppliers into public and infrastructure projects (EU, UK, US).
  3. B2B services revealed by the same events: freight forwarders and customs brokers (a company
     that just started importing needs them), trade insurers, testing labs, consultancies.
  4. The founder's agency, running radars for many clients (done for you).
- **Not a fit:**
  - consumer businesses;
  - small one-off sales;
  - suppliers with a few well-known buyers;
  - large enterprises with full sales-intelligence stacks;
  - markets without public data;
  - software sold to tech companies (for now).
- **Focus for the next weeks:** exporters into the UK and US, with freight forwarders and
  customs brokers as a second test, since the same import data serves both.

## Product strength: honest scorecard (0-10)
| Area | Today | After the hackathon | Full vision |
|---|---:|---:|---:|
| Trust and accuracy | 9 | 9 | 9 |
| Who to target: exporters | 2 | 7 | 8-9 |
| Who to target: project suppliers | 6 | 7 | 8 |
| Right-moment timing | 3 | 5 | 7-8 |
| Catching private intent | 0 | 0 | 5-6 (Gateway) |
| Learning per client | 7 | 7 | 9 |
| Setup without the founder | 1 | 6 | 8 |
| Fits how clients work | 3 | 4 | 8 |
| Runs in production | 2 | 7 | 8 |
| Hard to copy | 5 | 7 | 8 |

- **Biggest unknown:** outcomes. No lead has produced a reply yet. Design partners decide whether
  this is a strong product or only a trustworthy research tool.

## How today maps onto the planned learners (ARCHITECTURE v2)
| Lesson | Learner it belongs to |
|---|---|
| Watch a case; know the next step | **W** (expectations) + **A** (when to re-check) |
| Who buys depends on the client; use their customers | **O** (the buyer model is its first form) |
| Which signals come before buying | **B** (needs about 20-30 outcomes) |
| Import records beat web search; search engines misdate | **R** (source and search yield) |
| Check every claim | Verifier and Skeptic (built) |

- **Gateway-lite** (a findable page, a fact-only receptionist, buyer requests becoming cases)
  should move from Phase 4 to Phase 2: it is the only way to catch private intent.

## What makes clients keep using it (adoption; mostly after the hackathon)
1. **Delivery where they work:** a short weekly WhatsApp or email digest linking into the app.
2. **A draft next step for each taken lead,** built only from verified facts, with a
   company-level route.
3. **A simple tracker per lead** (contacted, sample, quote).
4. **Results on Station** ("this month: 12 targets, 4 replies, 1 sample").
5. **One login across many clients,** for the agency.

- **Optional before the hackathon:** a weekly email digest, if a day frees up.

## Lessons from reviewing an external lead list
- **Adopt:** two scores, *potential* and *now*, and explicit states (act, hold until X, watch,
  too late, reject).
- **Adopt:** supply tenders routed through the client's customers when the client cannot bid
  directly.
- **Reject:** facts not on the cited page, a supplier review the page itself contradicts, product
  variants the client does not make, and personal contact details.

## Validation with design partners
- **Send:** each week, the best verified leads to design partners. Track sent → replied → meeting
  → sample or quote → won.
- **Ask directly:** "would you pay for this weekly, and how much?"
- **Test breadth:** 2-3 more exporters in different industries, so the result is not tied to one
  product.
- **Value case:** for an exporter, one new account brings repeat orders for years. One new
  account a year can cover the subscription many times over (to be confirmed with partners'
  real numbers).


---

# Step 1: technical design (14 Oct)

**Goal:** a client with a buyer model gets **proven buyers** from official import records,
checked by the gate against that model. Clients without a buyer model behave exactly as today,
so recordings and tests stay stable.

**1. `ClientSpec`** (`radar/models.py`). New optional fields; all empty by default:
- `buyer_roles: list[str]`: trade roles that buy from the client (for example importer,
  distributor, wholesaler, merchant, contractor).
- `not_buyers: list[str]`: who is competition (for example "other manufacturers or exporters of
  the same products").
- `product_codes: list[str]`: scheme-prefixed codes buyers use (`hs:690721`, `cpv:44113120`).
- `existing_customers: list[str]`: company names. They are never shown as new and are used as
  routes. Real lists live only in git-ignored specs.

**2. Gate** (`radar/gate.py`):
- New prompt `radar_gate.v4.md` with `{buyer_roles}` and `{not_buyers}`. Rule: an organisation
  whose trade role is listed is a buyer, never a reseller. Competitor means it sells the same
  offer at the client's own level.
- v4 is used only when `buyer_roles` is non-empty, so v3 recordings replay unchanged.

**3. New stream `trade`** (`RadarStream.TRADE`, D102):
- An entry backed by official trade records.
- Enumerable (`stream_is_enumerable`), because the register lists every importer that is not
  suppressed.
- Touches the files that switch on stream:
  - `account.py` (role: `importer_of_record`, evidence level `proven_buyer`);
  - `brief.py` (status, caution, ranking);
  - `entities.py`, `fit.py`, `bidders.py` (skip);
  - `discover.py`;
  - `api/views.py`;
  - frontend `lead.ts` / `CaseSheet.tsx` / `StationPage.tsx` (type "Importer", question
    "Approach X?", window "imports monthly since …").

**4. New event type `imports_recorded`** (`EventType`, generic; SPEC §1 amended in D102):
- Meaning: "official trade records show the company imported goods under the client's product
  codes in a period".
- Slots: codes, first month, months active, and `new_this_year`.

**5. Sensor `sensors/hmrc.py`:**
- **Query:** `SensorQuery(codes=["hs:690721", ...], countries=["GB"], published_from=…)`.
- **Calls:** `api.uktradeinfo.com/Commodity` with `$expand=Imports($filter=MonthId ge …;
  $expand=Trader)`, paged with `@odata.nextLink`, held to 60 requests a minute.
- **Also:** the previous calendar year with `$select=TraderId,MonthId` only, to mark new
  importers.
- **Documents:** one per trader per run. Rendered lines are what claims quote:
  - `Importer: <name>`
  - `Postcode: <postcode>`
  - `Commodity 69072100 (<description>): imported in 2026-01, 2026-02, ...`
  - `Not recorded as importing these codes in 2025`
- **Meta** (schema_ver 1): trader id, name, postcode, codes, months, and new_this_year.
- `source_name = "hmrc"`, evidence rule `structured`, `available_at` = the publication month.
- **Licence:** Open Government Licence v3.0 (attribute HMRC). Check the terms page during the
  build.
- **Fixtures:** recorded API replies under `tests/fixtures/sensors/hmrc/`. No network in tests.

**6. `structured.py`:**
- A branch for `doc.source_name == "hmrc"`.
- Claims are the rendered lines above, with the subject the importer (role `importer`).
- One `imports_recorded` event, its date the latest month.

**7. Sizing and noise:**
- Cap documents per run (setting).
- Rank traders by: imports both code families > months active > new this year.
- Drop traders at the HMRC overseas-trader address (postcode AB10 1ZP marks non-UK sellers) and
  existing customers (marked, not shown as new).

**8. Company register** (step 1b; needs the founder's free Companies House key):
- Status, incorporation date and activity code (SIC) per importer.
- The gate sees a claim "Companies House lists activity: …". Hauliers, agents and dissolved
  companies are rejected.

**9. Acceptance:**
- A run for the field-test client (spec in `.refs/`) lists the verified importers from the hand
  list (the 2024-incorporated new importer, and the importer with public supply complaints).
- A run for a non-stone test client works unchanged.
- `tasks.py gate` passes.
- Time: about 1.5 sessions; 1b when the key arrives.

---

# Daily edition: 3-5 checked targets a day (founder, 14 Oct)

**Promise:** 3-5 checked targets every day, each with a reason to contact them today, each
labelled:
- **act now:** a live purchase, award or tender;
- **just changed:** something happened to this company;
- **account to work:** a proven buyer with a fresh, researched angle.

Never padded: a thin day says so.

**Daily mix:** 1 act now (if any) + 1-2 just changed + 1-2 accounts to work.

**Sources per label:**
- **Act now:** tenders and awards in every market of the client, across all its product codes.
- **Just changed:**
  - the Companies House streaming API (same free key as the lookup): new owners (PSC
    changes), renames, new companies registered under the client's buyers' trade codes (SIC),
    officer changes;
  - import records (started or stopped importing);
  - news, trade press and job ads.
- **Account to work:** the proven-buyer list from import records, ranked by fit, each with a
  researched brief (what they sell, ownership, recent changes, import pattern, why now).

**Evidence:** the field test's best lead (a tile group taking control of a new company, renaming
it for stone and porcelain distribution, and starting to import) came from register changes plus
import records.

**Build order:**
1. Step 1 (buyer model, import records).
2. Companies House lookup and stream (step 1b, moved earlier).
3. A per-client daily quota with labels in the edition.
