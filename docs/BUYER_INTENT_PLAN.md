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
