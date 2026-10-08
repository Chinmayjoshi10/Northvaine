# Buying-signal sources beyond tenders

Date checked: 2026-10-09. Researcher notes for Northvaine. No code written. No secrets used.
Tags: **C** = confirmed in official docs fetched today, **I** = inferred, **U** = unknown (founder command given where possible).
"Third-party" marks blogs or vendor pages (last resort). Several official pages were fetched through a summarising tool, so quotes are paraphrase, not verbatim; re-check before building.

## 1. The buying-moment ladder and where each source sits

plan / pipeline -> funding or grant -> permit / planning application -> financing (charges) -> construction or expansion -> hiring -> procurement (tenders, covered elsewhere) -> delivery (trade flows).

Lead time before purchase is **I** (typical, not measured) throughout.

## 2. Ranking (top 10)

Score = (earliness x reliability x coverage) / effort. Each factor 1 to 5 (effort 1 = easiest). Scores are my judgement (**I**).

| # | Source | E | R | C | Effort | Score | Why |
|---|---|---|---|---|---|---|---|
| 1 | World Bank Projects API | 5 | 5 | 3 | 1 | 75 | Projects appear 1 to 3 years before tenders; keyless JSON; CC BY 4.0; fits Indian exporters selling into developing markets |
| 2 | USAspending assistance (grants) awards | 4 | 5 | 3 | 1 | 60 | Funded recipients (cities, universities, utilities) are about to spend; keyless; same host as our award sensor. Endpoint detail **I** (verify) |
| 3 | Tavily search `topic=news` + time filters | 3 | 2 | 5 | 1 | 30 | Already integrated; catches press releases, expansion news; needs quote check |
| 4 | SEC EDGAR (8-K, 10-K, 10-Q text) | 4 | 5 | 3 | 2 | 30 | Capex plans and new facilities in company's own words, quote-able |
| 5 | UK planning applications (PlanIt) | 5 | 4 | 3 | 2 | 30 | Application precedes construction by months to years; licence unclear |
| 6 | Grants.gov search2 | 3 | 4 | 2 | 1 | 24 | Keyless; reveals funding programmes (who may buy), not the buyer itself |
| 7 | Companies House (charges, filings, streaming) | 3 | 5 | 3 | 2 | 22.5 | New secured borrowing often funds sites or equipment; UK only |
| 8 | EU CORDIS / Funding & Tenders | 4 | 5 | 2 | 2 | 20 | Funded EU projects with partners and budgets; access route not confirmed |
| 9 | GDELT DOC 2.0 | 2 | 2 | 5 | 1 | 20 | Free global news index; noisy; no licence stated |
| 10 | UK National Infrastructure and Construction Pipeline | 5 | 3 | 2 | 2 | 15 | Years-ahead project list; annual spreadsheet; data caveats |

Next below the line: Adzuna hiring (13.5), Socrata city permits (10.7), 360Giving (UK grants), GLEIF (entity resolution, not a signal), UN Comtrade (macro, not org-level).
Do not build: bill-of-lading vendors (section 8), OpenCorporates free tier (share-alike).

Suggested build order: (1) World Bank, (2) USAspending assistance, (3) lean harder on Tavily news mode (no new code path), (4) EDGAR, (5) PlanIt after founder confirms terms, (6) Companies House.

## 3. Planning and permits

### 3.1 PlanIt (UK planning applications) - source: https://www.planit.org.uk/api/ (checked 2026-10-09)

| Fact | Value | Tag |
|---|---|---|
| Signal | A planning application for a new site, extension or change of use. Months to years before construction purchasing. | I |
| Search endpoint | `/api/applics/{fmt}?{query}`; formats csv, geojson, georss, json, tsv | C |
| Single application | `/planapplic/{applic_name}/{fmt}` | C |
| Areas | `/api/areas/{fmt}` | C |
| Auth | None described. 403 if IP blocked or User-Agent invalid. | C |
| Limits | Max 5,000 results and 1,000 kB per request; 45 s query timeout (400); 429 with Retry-After on rate limit; `pg_sz` default 300 | C |
| Fields | name, uid, altid, reference, description, start_date, decided_date, last_changed, status, decision, application_type, development_type, location, link, other_fields (applicant and agent details) | C |
| Coverage | UK planning areas by region; some areas inactive or stale. Total count not stated. | C |
| Licence / commercial reuse | Not stated on the API page; points to an acknowledgements page (the URL I tried returned 404). Underlying council data licences vary. | **U** |
| Evidence fit | `description` is free text from the council: quote-able. `link` goes to the council page. Applicant may be a private individual: store organisations only (rule: no private individuals). | C / I |

Founder action: email the PlanIt operators (contact on the site) asking whether commercial reuse of the API is allowed. Do not build before the answer.

### 3.2 US city permits via Socrata (SODA)

Sources: https://dev.socrata.com/docs/app-tokens.html (C). City dataset ids from third-party scraper listings only.

| Fact | Value | Tag |
|---|---|---|
| Signal | Issued building permit with work description and value. Weeks to months before fit-out purchasing. | I |
| Access | `https://<domain>/resource/<dataset-id>.json`, `$limit`, `$where` | I (docs not fetched; Socrata pattern) |
| Auth | App token optional; unauthenticated calls share a per-IP pool with lower limits; tokened calls are "not throttled" unless abusive; 429 on throttle; header `X-App-Token` | C |
| Example | Chicago building permits dataset id `ydr8-5enu` on `data.cityofchicago.org`; fields like permit_type, issue_date, work_description | third-party, I |
| Coverage | One schema per city. No national feed. | I |
| Licence | Per city, usually open data terms; check each. | U |
| Effort | High: per-city field mapping. Needs a "source config as data" approach (no city names in code). | I |

### 3.3 EU equivalents
No single EU planning API found. Not researched further. **U**.

## 4. Company filings and registries

### 4.1 UK Companies House
Sources: https://developer-specs.company-information.service.gov.uk/guides/rateLimiting (C); https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/charges/list (C); https://api.gov.uk/ch/companies-house-streaming/ (C, via search result).

| Fact | Value | Tag |
|---|---|---|
| Signal | New charge (secured loan) registered, new subsidiary or officer appointments, accounts. Hints at financing for expansion or equipment. | I |
| Charges endpoint | `GET https://api.company-information.service.gov.uk/company/{company_number}/charges`, returns `chargeList` | C |
| Field list | In the `chargelist` resource page (not read). Likely classification, persons entitled, created date. | U |
| Rate limit | 600 requests per 5 minutes; 429 beyond; higher limits on request; abusers may be banned | C |
| Auth | Free API key (separate Authorisation guide; not read) | I |
| Streaming API | Realtime streams: company information, filing history, insolvency cases, charges | C (api.gov.uk listing) |
| Streaming caveat | Forum reports `fields_changed` often empty and a missed event | third-party |
| Licence | Companies House staff say the register carries no usage restrictions; user must follow data protection and copyright law. A 2021 mailing-list post says bulk data is CC-BY, not OGL. | third-party, U |
| Evidence fit | Charge text is short, structured; quote-able only as filing metadata. No narrative of purpose. Officers are natural persons: use companies only. | I |

Founder command to confirm licence: read https://developer.company-information.service.gov.uk/ terms of use after login.

### 4.2 SEC EDGAR
Sources: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data (C); https://www.sec.gov/edgar/search/efts-faq.html (C).

| Fact | Value | Tag |
|---|---|---|
| Signal | 8-K (material events), 10-K/10-Q capex and facility plans, in the company's own words. 1 to 4 quarters ahead. | I |
| Official APIs | `data.sec.gov`: submissions by company and XBRL JSON | C |
| Full-text search | Web tool covers filings since 2001 (C). No documented API on the official pages (C). Third-party notes say `https://efts.sec.gov/LATEST/search-index` with `q`, `forms`, `startdt`, `enddt`, `from`, `ciks`, 10 hits per page. | third-party; undocumented, may break |
| Limits | 10 requests per second; must send a User-Agent naming the company and a contact email | C |
| Cost | Free | C |
| Licence | US federal public filings; reuse generally unrestricted | I |
| Evidence fit | Excellent: exact sentences, accession-number URL, filing date. | I |

Founder command: email textsearch@sec.gov (the contact the FAQ lists) to ask about supported programmatic full-text access.

## 5. Funding and grants

### 5.1 World Bank Projects API (projects before tenders)
Source: https://datacatalog.worldbank.org/search/dataset/0037800/world-bank-projects-and-operations (C)

| Fact | Value | Tag |
|---|---|---|
| Signal | Project in pipeline or approved, before procurement notices. Often 6 to 36 months ahead. | I |
| Endpoint | `https://search.worldbank.org/api/v3/projects`; full export `.../projects/all.xlsx` | C |
| Auth / cost | None stated; the sibling note (global_tender_sources.md) records keyless live probes of the procurement API | C (sibling) |
| Licence | Creative Commons Attribution 4.0 (commercial reuse with attribution) | C |
| Fields | title, task manager, country, project ID, sector, themes, commitment amount, product line, financing, links to public documents | C |
| Update cadence | Not stated | U |
| Evidence fit | Project documents (Project Appraisal Documents) are long PDFs with procurement plans: very quote-able, fetch via `documents` text. | I |
| Caveat | Borrower government is the buyer; the organisation is often a ministry. | I |

### 5.2 USAspending assistance awards
Source: sibling note lists https://api.usaspending.gov/docs/endpoints as keyless (C there). Assistance (grant) award search is a separate filter on the same API (not fetched today) so **I**.
Signal: federal grant to a city, utility or university means money to spend over 1 to 3 years. Fields: recipient, amount, CFDA programme, place, dates, description. Licence: US federal public data (**I**).

### 5.3 Grants.gov search2
Source: https://grants.gov/api/api-guide (C). Endpoint `POST https://api.grants.gov/v1/api/search2`; no authentication required; query keys include `keyword` (full list not in page); rate limits not stated (**U**). Signal: funding opportunity opened (a programme, not a buyer). Weak alone; pair with 5.2. A direct fetch of `https://api.grants.gov/` returned 403 (needs browser-like headers or a different path).

### 5.4 EU CORDIS and Funding & Tenders
Official landing pages fetched returned no usable detail. SEDIA search API documentation was not found in official sources (**U**). Per a third-party guide, funded-project data lives in CORDIS, a separate system. CORDIS publishes open data on data.europa.eu (**I**); licence typically CC BY 4.0 (**U**, confirm on the dataset page). Signal: funded consortia with budgets and named partners. Founder command: open https://cordis.europa.eu/about/open-data and https://data.europa.eu and note the licence and file format.

### 5.5 360Giving (UK)
Data-use licence page returned 404 (**U**). Standard is open grants data in a common schema (**I**). Narrow to UK charities and public funders; low priority.

## 6. Trade data

- **UN Comtrade**: needs subscription keys from the Comtrade portal (C: https://comtradedeveloper.un.org/). Free-tier limits not retrievable (page loads by script) (**U**). It gives country-by-product flows, not organisations, so it can rank markets but cannot name a buyer. Founder command: sign in at comtradeplus.un.org and read the API quota on the "My API portal" page.
- **Bill-of-lading data (ImportYeti, ImportGenius, Panjiva, Volza)**: USITC states bill-of-lading data is not official trade statistics and is not in DataWeb; one must ask CBP (C: https://www.usitc.gov/faq/question/can_i_get_bills_lading_data_dataweb.htm). Vendors say they obtain US data by FOIA (third-party). ImportYeti's own notice admits records can contain personal names and addresses and offers removal. **Recommendation: do not ingest.** Reasons: personal data risk, unclear redistribution terms, importers can request manifest confidentiality (third-party), and our rules forbid tracking private individuals. Revisit only with written terms. Tag: terms **U**.

## 7. Hiring signals

| Source | Facts | Tag |
|---|---|---|
| Adzuna | Base `https://api.adzuna.com/v1/api`; every call needs `app_id` and `app_key`; search ads, salary stats, categories; JSON; example country `gb`; rate limits and Terms of Service content not retrieved. Source: https://developer.adzuna.com/overview | C for auth; limits and terms U |
| USAJOBS | Federal jobs only (I). Search Jobs API: up to 10,000 rows, 500 per page. Terms page returned no commercial-use clause. Source: https://developer.usajobs.gov/guides/rate-limiting | C for limits; commercial terms U |

Signal: a hiring burst for site roles or specific functions suggests expansion 1 to 6 months ahead (**I**). Evidence fit: job text is quote-able, but an ad shows intent weakly. Treat as a corroborating signal, never alone. Adzuna terms must be read before storing snapshots (we must store a document snapshot per our no-source-no-claim rule, which API terms may forbid). **U**.

## 8. News and press releases

### 8.1 Tavily features
Sources: https://docs.tavily.com/documentation/api-reference/endpoint/search (C); https://docs.tavily.com/guides/api-credits (C, via search result).

| Fact | Value | Tag |
|---|---|---|
| `topic` | `general` (default), `news`, `finance` | C |
| Date filters | `time_range` (day, week, month, year or d/w/m/y), `start_date`, `end_date` (YYYY-MM-DD); undated results kept unless `filter_by_published_date` is true | C |
| `search_depth` | `basic` (default), `advanced`, `fast`, `ultra-fast`; 1 credit, advanced 2 credits | C |
| Domain control | `include_domains` up to 300; `include_domains_mode` `restrict` or `prefer` | C |
| Extract cost | 1 credit per 5 successful URLs basic, 2 advanced | C |
| Map cost | 1 credit per 10 pages; 2 with instructions | C |
| Crawl cost | Map plus extract (example 3 credits for 10 pages basic) | C |
| Dollar price | Not in official docs; third parties say about $0.008 per credit pay-as-you-go | third-party |

Use: scheduled `topic=news` queries with `time_range=week` and `include_domains` of official newsrooms and regulator sites; then `extract` to snapshot the page for quote verification.

### 8.2 GDELT DOC 2.0
Source: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ (C).
Endpoint `https://api.gdeltproject.org/api/v2/doc/doc`; params `query`, `mode`, `format` (json, csv, rss...), `timespan` (min 15 minutes), `startdatetime`/`enddatetime` (must be within last 3 months), `maxrecords` (default 75, max 250), `sort`. History search back to 2017 (as stated). Auth none stated. Licence and rate limits not stated (**U**). Output is article list (title, URL, source); you must fetch the article text yourself, so quote verification works on the fetched page. Noisy; use for broad discovery only.

### 8.3 Newswires / RSS
Not researched in depth (**U**). Company newsroom RSS feeds are public pages; check each site's terms. Newswire APIs (PR Newswire, Business Wire) are paid or licensed: not confirmed.

## 9. Trade shows, associations, certifications
Exhibitor lists are published as web pages with per-site terms; no official API found. Scraping is only acceptable where robots and terms allow; treat as fetch-by-Tavily-extract of a known public page. Reliability of "exhibitor" as a buying signal is low (it is a seller signal for most shows; visitor and buyer-delegation lists are rarely public). Status: **U**, not ranked. Industry registries and certifications (for example ISO certificate databases) mostly lack open APIs (**U**).

## 10. Infrastructure pipelines

| Fact | Value | Tag |
|---|---|---|
| UK National Infrastructure and Construction Pipeline | Annual GOV.UK publication with xls and csv; lists planned public and private investment. The 2025 edition page I tried returned 404; a 2018 edition page lists xls and csv. | C (2018), current edition U |
| Caveats | Earlier editions say data is unaudited administrative data, owned by providers, not official statistics, not a commitment | C (via search summary) |
| Licence | OGL likely on GOV.UK (**I**); not confirmed on the page | U |
| Signal | Project name, sector, owner, expected timing and value; 1 to 10 years ahead | I |
| US state STIPs, EU structural funds | Not researched; per-state PDF or portal formats (**U**) | U |

Founder command: open https://www.gov.uk/search/transparency-and-freedom-of-information-releases?keywords=national+infrastructure+and+construction+pipeline to find the current edition.

## 11. Entity resolution helpers (not signals)

- **GLEIF API**: public search, fuzzy name search, parent and child relationships; production since 2020 (C: https://www.gleif.org/en/lei-data/gleif-api). Docs at https://api.gleif.org/docs not read; licence (believed CC0), auth and limits **U**. Useful for linking a project owner to a parent company.
- **OpenCorporates**: API key required; free only for open-data projects that release under share-alike attribution; default 200 requests per month and 50 per day; paid plans remove share-alike (C: https://api.opencorporates.com/documentation/API-Reference). Share-alike makes the free tier unsuitable for a proprietary product. Skip unless paid.

## 12. How each fits the evidence model

Rule 2 requires a `documents` snapshot containing a `source_quote`. Fit:

- Strong (prose in an official page or filing): World Bank project documents, SEC filings, planning application descriptions, news pages fetched by Tavily extract, grant award descriptions.
- Medium (short structured fields only): Companies House charges, USAspending awards, Grants.gov listings. Quote the field text with its record URL; do not infer purpose.
- Weak: job ads, GDELT hits (only pointers), trade flows.

Also: all fetched text is untrusted (rule 7); personal data in permit or planning records (named applicants) must be dropped or kept to organisations only.

## 13. Open questions (need founder or a key)

1. PlanIt commercial reuse terms (email operators).
2. SEC programmatic full-text access (email textsearch@sec.gov).
3. Companies House API terms and key (register for a free key, read the terms).
4. Adzuna ToS: whether storing snapshots is allowed (register for keys, read terms).
5. World Bank update cadence and procurement-plan fields (live probe: `curl "https://search.worldbank.org/api/v3/projects?format=json&rows=3"`).
6. USAspending assistance search endpoint shape (check https://api.usaspending.gov/docs/endpoints).
7. CORDIS bulk licence and format.
8. Comtrade free-tier quotas.
9. UK NIP current edition and licence.
