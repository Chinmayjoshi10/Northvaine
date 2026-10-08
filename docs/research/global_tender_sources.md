# Global tender and award sources (official, machine-readable)

Date checked: 2026-10-09. Researcher notes for Northvaine. No code was written.
Confidence tags: **C** = confirmed in official docs or by a live keyless request today (2026-10-08/09),
**I** = inferred, **U** = unknown / needs founder action.
"Live probe" means I sent a real HTTP request from this machine with no key. No secrets were used.

## 1. Summary and ranked recommendation

Build order by value (US + UK high-ticket buyers, Indian exporters selling abroad) against effort (our
existing OCDS reader in `northvaine/sensors/fts.py`):

| Rank | Source | Why | Effort | Key? |
|---|---|---|---|---|
| 1 | **US: SAM.gov Get Opportunities (open tenders) + USAspending (awards)** | Largest high-ticket buyer pool; open tenders AND awards with winner and value; NAICS and PSC filters. Not OCDS, so needs a new small mapper. | Medium (new JSON mapper x2) | SAM: free key. USAspending: none |
| 2 | **Australia AusTender OCDS API** | Real OCDS 1.1, keyless, live-confirmed. Awards with supplier and value (contract notices only, so it is awards not open tenders). Closest fit to our OCDS reader. | Low | None |
| 3 | **Canada CanadaBuys open data CSV (tenders + awards)** | Both open tenders and awards (supplier and value) in free CSV files under OGL-Canada. Not OCDS and CSV, so a small CSV reader. | Low to medium | None |

Then, for widest country coverage with the least code: **one generic "OCDS bulk/API" sensor** (section 6)
that reads OCDS release packages or the OCP Data Registry `.jsonl.gz` files. One reader, about 100 publishers
(Paraguay, Peru, Brazil, Ukraine, Nigeria, Kenya, Ghana, Ecuador, Uruguay, Dominican Republic, Rwanda,
Zambia, South Africa, Chile, Australia, UK nations, and so on).

Also worth doing for Indian exporters: the **World Bank procurement notices API** (keyless, JSON, live
confirmed) because it lists open tenders and awards for projects in 100+ developing countries, including
India-adjacent markets. It is easy (one JSON endpoint) and is a good fourth source.

India CPPP and GeM: no official API or open-data licence found. Do not build (section 5).

## 2. United States

### 2.1 SAM.gov Get Opportunities Public API (open tenders, plus award notices)

Source: https://open.gsa.gov/api/get-opportunities-public-api/ (checked 2026-10-09). Confidence C unless noted.

| Fact | Value |
|---|---|
| Endpoint | `GET https://api.sam.gov/opportunities/v2/search` (alpha: `https://api-alpha.sam.gov/opportunities/v2/search`) |
| Auth | Public `api_key` query param. Key comes from your SAM.gov account Details page (needs a free SAM.gov account; viewing the key needs password re-entry). |
| Required params | `api_key`, `postedFrom`, `postedTo` (both `MM/dd/yyyy`). Max span 1 year. |
| Pagination | `limit` max 1000, `offset` = page index from 0. Docs are inconsistent on whether both are required, so always send both. |
| Filters | `ptype` (u, p, a=Award Notice, r, s, o=Solicitation, g, k=Combined Synopsis/Solicitation, i), `ncode` (NAICS, up to 6 digits), `ccode` (classification/PSC), `state`, `zip`, `organizationCode`, `organizationName`, `typeOfSetAside`, `title`, `solnum`, `noticeid`, `rdlfrom`/`rdlto` (response deadline). No free-text keyword param besides `title`. |
| Format | JSON (not OCDS). |
| Open tenders AND awards | Open: yes (ptype o, k, p, r). Award notices: yes (`ptype=a`) with `data.award.number/amount/date` and `awardee.name`, `ueiSAM`, address, but only where the agency chose to post an award notice. |
| Freshness | Active notices updated daily; archived weekly. Only latest version of each notice. |
| Rate limits | Daily limits depend on role (federal / non-federal / general); the page gives no numbers. For the sister Contract Awards API the table is below; expect the same order of magnitude (about 10 per day with no role, 1,000 per day with a role) but **U** for Opportunities. Founder action: register a SAM.gov account, get a key, then read the quota from response headers. |
| Terms | Page states no explicit reuse terms. US federal data is generally public domain (**I**). |
| Gotchas | Description text needs the key appended to download. `postedFrom` and `postedTo` are required, so a nightly cycle must send a date window. Award notice coverage is partial (many awards are only in FPDS/USAspending). |

### 2.2 SAM.gov Contract Awards API (award data, FPDS-equivalent)

Source: https://open.gsa.gov/api/contract-awards/ (checked 2026-10-09; page is long, I read the first 100k of 182k chars). C.

| Fact | Value |
|---|---|
| Endpoint | `GET https://api.sam.gov/contract-awards/v1/search` (`deletedStatus=yes` for deleted) |
| Auth | `api_key` (personal key or System Account key). |
| Daily rate limits | Non-federal, no role: 10. Non-federal with role: 1,000. Federal personal: 1,000. Non-federal system account: 1,000. Federal system account: 10,000. |
| Filters | `dollarsObligated`, `naicsCode` (up to 100 values), `awardeeUniqueEntityId`, `awardeeCageCode`, `dateSigned` (single or `[MM/DD/YYYY,MM/DD/YYYY]`), `lastModifiedDate`, `fiscalYear`, `contractingDepartmentCode`, `q` free text. Operators `&`, `~`, `!`. |
| Pagination | `limit` max 100, default 10, `offset` zero-based. `limit` x `offset` must be at most 400,000. |
| Bulk extract | `format=csv` or `format=json` returns a tokenised download link; max 1,000,000 records per export. |
| Fields | `awardDetails.dollars.actionObligation`, `baseAndExercisedOptionsValue`, `baseAndAllOptionsValue`; `awardDetails.dates.dateSigned`; `awardeeData` (name, UEI, CAGE, parent info); principal NAICS. |
| Freshness | DoD awards are public only 90 days after signature (the "unrevealed" window is DoD-only). Civilian are current. |
| Gotchas | The 10 per day non-role quota makes this impractical for a nightly job unless the SAM.gov account has a role. |

### 2.3 USAspending.gov API (recommended for awards: keyless)

Sources: https://api.usaspending.gov/docs/endpoints (no authorization stated),
https://github.com/fedspendingtransparency/usaspending-api (api contract `search/spending_by_award`). C, plus live probe.

| Fact | Value |
|---|---|
| Endpoint | `POST https://api.usaspending.gov/api/v2/search/spending_by_award/` (live probe returned 200 with results) |
| Auth | None ("Endpoints do not currently require any authorization"). |
| Rate limits | Not documented. **U**; be polite (1 request per second). |
| Filters | `award_type_codes` (required; contracts A, B, C, D), `time_period` (`[{start_date, end_date}]` YYYY-MM-DD), `keywords`, `description`, `naics_codes`, `psc_codes`, `recipient_search_text`, `recipient_locations`, `award_amounts`, `agencies`, `set_aside_type_codes`, `place_of_performance_locations`. |
| Fields (request in `fields`) | `Award ID`, `Recipient Name`, `Award Amount`, `Awarding Agency`, `Description`, `Start Date`, `End Date`, `NAICS`, `PSC`, `Contract Award Type`, `Last Modified Date`. |
| Pagination | `limit` (default 10; max not stated, **U**; try 100), `page`; response has `page_metadata.hasNext`. |
| Bulk | `POST /api/v2/bulk_download/awards/` (zip of CSV) and monthly files via `/api/v2/bulk_download/list_monthly_files/`. |
| Freshness | Updated from FPDS roughly daily with lag; DoD detail lags by 90 days (**I**). |
| Terms | Licence not stated on the docs page; US federal data is public domain (**I**). Founder can confirm at https://www.usaspending.gov/about. |

Example request that returned results during the 2026-10-09 probe:

```json
{"filters":{"award_type_codes":["A","B","C","D"],"time_period":[{"start_date":"2026-09-01","end_date":"2026-09-30"}],"naics_codes":["541511"]},
 "fields":["Award ID","Recipient Name","Award Amount","Awarding Agency","Start Date"],"limit":2,"page":1}
```

Gotcha: `time_period` matched awards with an older Start Date (2016) because it filters on action dates, so de-duplicate by `generated_internal_id`.

Recommendation: SAM Opportunities for open tenders (needs key), USAspending for awards (no key, keep SAM Contract Awards only as a fallback).

## 3. Australia: AusTender OCDS API (full detail)

Sources: https://github.com/austender/austender-ocds-api (README), https://app.swaggerhub.com/apis/austender/ocds-api/1.1
(OpenAPI via https://api.swaggerhub.com/apis/austender/ocds-api/1.1), OCP registry https://data.open-contracting.org/en/publication/19,
plus live probe of `https://api.tenders.gov.au/ocds/` on 2026-10-09. C.

| Fact | Value |
|---|---|
| Base | `https://api.tenders.gov.au/ocds/` |
| Endpoints | `GET /findById/{CN ID}` (e.g. `CN4280221`); `GET /findByDates/{dateType}/{start}/{end}` with `dateType` in `contractPublished`, `contractLastModified`, `contractStart`, `contractEnd`; dates `yyyy-mm-ddThh:mi:ssZ` |
| Auth | None. Live probe succeeded keyless. |
| Rate limits | Not documented. **U**. |
| Format | OCDS 1.1 release package (`version: "1.1"`, one `releases[]` entry per Contract Notice); extension `http://cdn.tenders.gov.au/ocds/schema/extension.json` |
| Open tenders? | **No.** The API serves Contract Notices (CNs), i.e. awarded contracts. Open "Approaches to Market" are not in this API (not confirmed anywhere in the docs; **U**). |
| Awards | Yes. Live sample had `awards[].suppliers[].name`, `parties[]` with ABN (`AU-ABN`), `contracts[].value.amount` and `currency` (AUD, string), `contracts[].items[].classification` scheme **UNSPSC**, `contracts[].period`, `contracts[].dateSigned`, `procurementMethod`. |
| Filters | Dates only (published, last modified, start, end). No keyword, UNSPSC or buyer filter server-side; filter client-side. Earliest date 2013-01-01. |
| Pagination | The swagger lists optional `cursor`, `prevcursor`, `lastcursor` query params that the service injects; my one-day probe returned 92 releases in one response with no paging links in the body. For larger windows, page by narrow date windows. How large windows page is **U**. |
| Gotchas | `contractPublished` returns only parent CNs; use `contractLastModified` to also catch amendments. Contact emails appear in `parties[].contactPoint` (personal data): drop them, as `fts.py` does. |
| Licence | Data: CC BY 3.0 AU (the response itself carries `"license": "https://creativecommons.org/licenses/by/3.0/au/"`; the OCP registry says the same). Commercial use allowed with attribution. The MIT licence in the GitHub repo covers sample code, not data. |
| Freshness | Near real time (probe returned notices published within the previous day). |
| Bulk | OCP registry bulk files since 2007 (JSONL gz, 259 MB all-time), refreshed monthly. |

Example: `GET https://api.tenders.gov.au/ocds/findByDates/contractPublished/2026-10-01T00:00:00Z/2026-10-02T00:00:00Z`

## 4. Canada: CanadaBuys open data (full detail)

Sources: https://open.canada.ca/data/en/dataset/6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2 (tender notices),
https://open.canada.ca/data/en/dataset/a1acb126-9ce8-40a9-b889-5da2b1dd20cb (award notices),
data dictionary https://donnees-data.tpsgc-pwgsc.gc.ca/ba2/ac-cb/achatscanada-canadabuys-dd.xml; live HEAD and header read on 2026-10-09. C.
Note: OCP registry's Canada (Buyandsell, PWGSC) entry was last retrieved Sep 2022, so it is stale. Use CanadaBuys CSV directly, not OCDS.

| Fact | Value |
|---|---|
| Tender CSVs (keyless) | New: `https://canadabuys.canada.ca/opendata/pub/newTenderNotice-nouvelAvisAppelOffres.csv`; Open: `.../openTenderNotice-ouvertAvisAppelOffres.csv` (live: HTTP 200, 6.2 MB, Last-Modified 2026-10-08 10:20 GMT); Complete since 2022-08-08: `.../tenderNoticeComplete-avisAppelOffresComplet.csv`; per fiscal year: `.../2026-2027-TenderNotice-AvisAppelOffres.csv` |
| Award CSVs (keyless) | Complete since 2022-08-08: `https://canadabuys.canada.ca/opendata/pub/awardNoticeComplete-avisAttributionComplet.csv`; per fiscal year `.../2026-2027-awardNotice-avisAttribution.csv`; legacy 2012 to 2022-08 file |
| Auth / rate limits | None / not documented (**U**; plain static file downloads; use `If-Modified-Since` or ETag, files are updated at most daily). |
| Refresh | New tenders every 2 hours 06:15 to 22:15 (UTC-5); open tenders and complete files each morning 07:00 to 08:30 (UTC-5); past fiscal years monthly. |
| Format | CSV (UTF-8 with BOM), bilingual columns (`-eng`/`-fra`). Not OCDS. |
| Tender columns (live header) | `title`, `referenceNumber`, `amendmentNumber`, `solicitationNumber`, `publicationDate`, `tenderClosingDate`, `tenderStatus`, `gsin`, `unspsc` (+ descriptions), `procurementCategory` (CNST, GD, SRV, SRVTGD), `noticeType`, `procurementMethod`, `tradeAgreements`, `regionsOfDelivery`, `contractingEntityName` and address, `noticeURL`, `tenderDescription`. Contact name/email/phone present (personal data: do not store). |
| Award columns (live header) | `referenceNumber`, `contractNumber`, `contractAwardDate`, `contractStartDate`, `contractEndDate`, `contractAmount`, `totalContractValue`, `contractCurrency`, `awardStatus`, `instrumentType`, `gsin`, `unspsc`, `procurementCategory`, `supplierLegalName`, supplier address/city/province/country, `contractingEntityName`. |
| Winner and value | Yes (award file). |
| Filters | None server-side (static files). Filter client-side by UNSPSC/GSIN, region, dates, category, keyword. |
| Licence | Open Government Licence - Canada (https://open.canada.ca/en/open-government-licence-canada). Commercial use allowed with attribution. |
| Coverage | Federal only (Schedule I, II, III departments, Crown corporations); not provinces or municipalities. |
| Gotchas | Multi-line quoted fields (trade agreements, descriptions), so use a real CSV parser. `*CNST` style values with a leading asterisk. Amendments appear as new rows with `amendmentNumber`, so key by `referenceNumber` plus `amendmentNumber`. Quebec (SEAO) and Montreal are separate OCDS publishers in the OCP registry (Quebec last retrieved Oct 2026, Montreal Dec 2025). |

## 5. Open Contracting Data Registry (data.open-contracting.org)

Sources: registry listing https://data.open-contracting.org/en/search/ (135 datasets, checked 2026-10-09),
per-publication pages https://data.open-contracting.org/en/publication/NNN. C for what the registry says;
the live availability of each upstream API is **U** unless I probed it.

Bulk files: every dataset offers JSONL.gz (one contracting process per line), Excel and CSV, by year and
all-time, under `https://data.open-contracting.org/en/publication/NNN/download?name=<year>.<format>`
(pattern confirmed on page 135). The registry copy is refreshed monthly, so for freshness use the upstream API.
Only "compiled releases" are published there (the latest value per field).

Shortlist (current = registry retrieved within about 6 weeks of today; ranked by usefulness for us):

| # | Publisher | Registry id | Data span / registry last retrieved | Upstream API | Auth | Licence | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Australia, Dept of Finance (AusTender) | 19 | 2007 to Sep 2026 / Sep 2026 | `api.tenders.gov.au/ocds` (section 3) | none | CC BY 3.0 AU | Awards only |
| 2 | Ukraine, Prozorro | 154 | Feb 2015 to Sep 2025 (registry says "not yet retrieved") / real time | `https://public-api.prozorro.gov.ua/api/2.5/tenders?opt_schema=ocds`, feed paged by `next_page.uri` | none on the public feed (live probe returned 200 keyless, **but only fields of the feed, not OCDS probed**) | not specified in registry (**U**) | Huge (hundreds of GB). Tenders and awards. Wartime context; value for exporters is limited. Docs: https://prozorro-api-docs.readthedocs.io |
| 3 | Paraguay, DNCP | 63 | 2011 to Aug 2026 / Aug 2026; source updated hourly | `https://contrataciones.gov.py/datos/api/v3/doc/` | **Yes**: register app, OAuth token valid 15 minutes; 15 calls/min without key; lists capped at 10,000 records | CC BY 4.0 | Tenders and awards. Prefer the bulk file (1.7 GB all-time) |
| 4 | Peru, OECE | 135 | 2003 to Oct 2026 / Oct 2026; daily | none listed; bulk download only | none | CC BY 4.0 | Bulk only: `https://contratacionesabiertas.oece.gob.pe/descargas` |
| 5 | Brazil, SEGES (federal) | 157 | Aug 2021 to Sep 2026 / Sep 2026; daily | Swagger: `https://dadosabertos.compras.gov.br/swagger-ui/index.html#/11%20-%20OCDS/releases` | not stated (**U**) | CC BY 4.0 | Large buyer pool |
| 6 | Nigeria, BPP | 64 | May 2021 to Sep 2026 / Sep 2026 | none; bulk only (`http://nocopo.bpp.gov.ng/OpenData.aspx`) | none | BPP licence at `http://nocopo.bpp.gov.ng/license` (**U**, read it) | Awards and tenders; good for exporters to Africa. Plus 12 state publishers (Anambra Jun 2026, Ekiti, Osun Oct 2026 are current) |
| 7 | Chile, ChileCompra | 144 | 2022 to May 2026 / 6-monthly copy | Mercado Publico API: ticket from Clave Unica (personal registration), 10,000 requests per day per ticket, JSON/XML, by day/state/supplier/buyer; https://www.chilecompra.cl/api/ | **Yes** (ticket) | registry says CC0 | Chile needs a personal RUT and Clave Unica, so founder action. Terms: credit ChileCompra if republishing |
| 8 | Kenya PPRA / Ghana PPA / Rwanda RPPA / Zambia ZPPA / South Africa National Treasury | 147 / 85 / 145 / 3 / 143 | all retrieved Jul to Oct 2026 | not checked (**U**) | n/a | not checked | African exporter destinations; bulk files available from registry |

Other current publishers worth a later look (all retrieved Sep or Oct 2026): Ecuador SERCOP (110), Uruguay ARCE API (43),
Dominican Republic DGCP (22), Colombia (see below), Italy ANAC (117), Germany BMI (136), Netherlands MinEZ (133),
Taiwan AAC (160), Thailand BMA, Uganda PPDA, Croatia, Greece Diavgis, Guatemala, Honduras, Peru Compras, Indonesia ICW, Quebec (79).
Many European "OpenTender" entries (retrieved Jun 2026) just re-publish TED, which we already read.
UK nations: Contracts Finder (128), Find a Tender (41, already built), Scotland SPCD, Wales Sell2Wales. Not checked in detail.

Stale (do not build on): Canada PWGSC OCP copy (Sep 2022), Colombia Compra Eficiente OCP copy (Mar 2023), Mexico state entries (mostly 2022 to 2025),
India Assam (Oct 2024) and Himachal (Mar 2023), Portugal IMPIC (2022).

**Colombia alternative (not OCDS, current):** SECOP II "Procesos de Contratacion" on datos.gov.co (Socrata open-data API,
about 8.7 million rows, columns include `Nombre del Proveedor Adjudicado`, `Valor Total Adjudicacion`, `Precio Base`),
licence CC BY-SA 4.0 (https://www.datos.gov.co/api/views/p6dx-8zbt). Socrata endpoints are keyless with throttling (**I**); share-alike licence is a reuse constraint to check with the founder.

**Mexico federal (ComprasMX):** no federal OCDS publisher is current in the registry; I did not find an official API (**U**).

## 6. Multilateral

### 6.1 World Bank procurement notices API (recommended)

Sources: live probe of `https://search.worldbank.org/api/v2/procnotices` on 2026-10-09 (HTTP 200, keyless); an older doc path
`http://search.worldbank.org/api/procnotices` is cited on https://financesone.worldbank.org. I could not retrieve an official parameter reference page (**U**).
Confirm the full param list by running the commands below.

| Fact | Value |
|---|---|
| Endpoint | `GET https://search.worldbank.org/api/v2/procnotices?format=json&rows=N&os=OFFSET[&notice_type=...][&fl=...]` |
| Auth | None observed. |
| Rate limits | Not documented (**U**). |
| Data | 422,084 notices total at probe time. `notice_type` values observed: `Request for Expression of Interest`, `Contract Award`. Others (General/Specific Procurement Notice, Invitation for Bids) are expected, **U**. |
| Fields (live) | `id`, `notice_type`, `noticedate`, `submission_deadline_date`, `project_ctry_name`, `project_id`, `project_name`, `bid_reference_no`, `bid_description`, `procurement_group` (CS, etc.), `procurement_method_code/name`, `contact_organization`, `notice_text` (HTML). |
| Winners and values | Contract Award notices carry the supplier and value only inside the free-text HTML `notice_text` (I saw date, duration, scope; parse to confirm name and amount). Structured award data is in the separate Finances One datasets (below). |
| Filters | `notice_type` works (probed). Others (country, date, keyword `qterm`, `procurement_group`) are widely used but **not confirmed in official docs**: test them. |
| Licence | Not stated for this API (**U**). Finances One datasets: CC BY 4.0. |

Commands to confirm: `curl "https://search.worldbank.org/api/v2/procnotices?format=json&rows=1&qterm=pump&project_ctry_name=Kenya"`; `curl "https://search.worldbank.org/api/v2/procnotices?format=json&rows=1&notice_type=Invitation%20for%20Bids"`.

**World Bank structured awards (Finances One)**: e.g. https://financesone.worldbank.org/consultant-services-contract-awards-in-investment-project-financing/DS01064 :
CC BY 4.0, updated daily, API + bulk (API explorer `https://financesone.worldbank.org/api-explorer?id=DS01064`; a probe of its backing service returned HTTP 429 once, so it is rate limited).
Fields documented: WB contract number, contract signing date, "Supplier Country / Economy" (registration country). Supplier name and amount fields not named on the page (**U**). Excludes subcontractors; joint-venture values split equally.
Sources: https://financesone.worldbank.org .

### 6.2 UNGM
No official API or bulk feed found in official pages (help.ungm.org not read in detail). Public notices exist on the website;
third-party Apify scrapers exist but UNGM's terms govern automated access and I did not read them. **No API: do not build.**
Founder action: ask UNGM support, or read https://www.ungm.org terms, before any access.

### 6.3 Asian Development Bank
No notice API found. Closest: Operational Procurement Database (contracts awarded for projects approved in the past 10 years, XLSX files, as of 30 June 2024, https://data.adb.org/node/1081).
Bulk, stale, awards only. No API.

### 6.4 African Development Bank
No procurement-notice API found. Only a projects data portal (IATI-based) and statistics open data. No API for notices.

## 7. India (CPPP and GeM)

| Source | Finding |
|---|---|
| CPPP (eprocure.gov.in) | The site page lists a Downloads page (`https://eprocure.gov.in/cppp/downloaddisp`) but no API, open-data programme or RSS. Terms (https://eprocure.gov.in/cppp/disclaimer/): material may be reproduced "free of charge after taking proper permission" from the owning department, with acknowledgement; tenders are owned by the departments; no statement on automated access. Verdict: **no official API; reuse needs permission; do not scrape.** Contact `support-eproc@nic.in` to ask. |
| GeM (gem.gov.in) | No official API or open-data page found. I could not retrieve its Terms (the URL returned page-not-found). Bids are public on bidplus.gem.gov.in but terms of automated access are **U**. Verdict: no API, do not scrape without written permission. |
| data.gov.in | Has an API-key system and some datasets (e.g. Assam procurement) but the one I found says no API exists for that resource. No central tender dataset found. OCP lists only Assam (Oct 2024) and Himachal (Mar 2023), both not current. |
| Other | Policy: Open APIs policy of Government of India / API Setu (terms at https://docs.apisetu.gov.in). Nothing procurement-specific confirmed. |

For Indian exporters the useful data is foreign buyers (US, UK, EU, Australia, Canada, World Bank), not Indian tenders.

## 8. Middle East

- **Saudi Etimad:** the developer portal (https://apiportal.etimad.sa) requires an Etimad Business account and subscription per product; the products I saw were bank-contract inquiry and salary inquiry. No open tender feed is shown. A vendor blog claims an "Open Data" product, but I could not confirm it on the portal. Verdict: no usable open API. Needs account and subscription (could be paid); founder action only if a Saudi customer asks.
- **UAE:** no official open procurement API found; only commercial aggregators. 2015 Open Knowledge index rated UAE tender data 0% open (dated).
- **Other Gulf states:** not researched (no candidates surfaced). Qatar, Oman, Kuwait: **U**.

## 9. Coverage table: every country or region with an official source

Status key: **Usable now** = free, keyless or trivially free, official, machine-readable, probed or documented current.
**Needs key** = needs registration, key, ticket or account. **No API** = bulk files only, stale, or nothing official.

| Country / region | Source | Tenders | Awards | Winner + value | Format | Status |
|---|---|---|---|---|---|---|
| EU + EEA | TED Search API v3 | yes | yes | yes | JSON | Usable now (built) |
| United Kingdom | Find a Tender (OCDS) | yes | yes | yes | OCDS | Usable now (built) |
| United Kingdom | Contracts Finder (OCDS) | yes | yes | yes | OCDS | Likely usable now (not verified, **U**) |
| United States | SAM.gov Opportunities | yes | partial | partial | JSON | Needs key (free SAM.gov account) |
| United States | USAspending API | no | yes | yes | JSON | Usable now (keyless) |
| United States | SAM.gov Contract Awards | no | yes | yes | JSON/CSV | Needs key (10/day without a role) |
| Australia | AusTender OCDS | no (awards only) | yes | yes | OCDS 1.1 | Usable now (keyless) |
| Canada (federal) | CanadaBuys open CSV | yes | yes | yes | CSV | Usable now (keyless) |
| Canada (Quebec) | SEAO via OCP #79 | yes | yes | yes | OCDS | Bulk usable; upstream API not checked |
| Ukraine | Prozorro public API | yes | yes | yes | OCDS option | Usable now (keyless) |
| Paraguay | DNCP v3 API | yes | yes | yes | OCDS | Needs key (OAuth app) ; bulk usable now |
| Peru | OECE | yes | yes | yes | OCDS | Bulk only (daily); usable now as files |
| Brazil (federal) | SEGES OCDS | yes | yes | yes | OCDS | Likely usable now (swagger; key **U**) |
| Chile | Mercado Publico API | yes | yes | yes | JSON/XML | Needs key (personal ticket via Clave Unica) |
| Colombia | SECOP II on datos.gov.co | yes | yes | yes | Socrata JSON/CSV | Usable now (keyless; CC BY-SA) |
| Ecuador, Uruguay, Dominican Rep., Honduras, Guatemala | OCP publishers | yes | yes | yes | OCDS | Bulk usable; APIs not checked |
| Mexico | federal ComprasMX | - | - | - | - | No API found; state entries stale |
| Nigeria (federal + states) | BPP, Anambra, Ekiti, Osun | yes | yes | yes | OCDS | Bulk only |
| Kenya, Ghana, Rwanda, Zambia, Uganda, Tanzania, South Africa, Liberia | OCP publishers | yes | yes | yes | OCDS | Bulk usable; APIs not checked |
| Italy, Germany (BMI), Netherlands, Greece, Croatia, Taiwan, Thailand (BMA), Indonesia (ICW) | OCP publishers | yes | yes | mixed | OCDS | Bulk usable |
| Multilateral | World Bank procurement notices API | yes | yes | in text only | JSON | Usable now (keyless) |
| Multilateral | World Bank Finances One awards | no | yes | supplier country; name/value **U** | JSON/CSV | API; rate limited |
| Multilateral | ADB Operational Procurement DB | no | yes | yes (XLSX) | XLSX | No API, stale (Jun 2024) |
| Multilateral | UNGM, AfDB | - | - | - | - | No API |
| India | CPPP, GeM | - | - | - | - | No API; permission required |
| Saudi Arabia | Etimad developer portal | - | - | - | - | Needs account; no open tender product confirmed |
| UAE and other Gulf | none found | - | - | - | - | No API |

## 10. Build order for widest coverage

1. **USAspending (awards, keyless) then SAM.gov Opportunities (open tenders, free key).** Highest value for US buyers. New mapper: small.
2. **AusTender OCDS (keyless).** Fastest: reuse the OCDS reader. Awards only.
3. **CanadaBuys CSV (tenders + awards, keyless).** New small CSV reader, plus If-Modified-Since.
4. **Generic OCDS sensor** (one reader parameterised by publisher config: base URL, auth type, date param, field mapping), which also handles bulk `.jsonl.gz` from the OCP registry. First targets after AusTender: Prozorro (keyless API), Brazil SEGES, Peru OECE (bulk), Paraguay DNCP (OAuth), Nigeria BPP (bulk), then Kenya, Ghana, South Africa, Ecuador, Uruguay. This single sensor gives 20+ countries. Per-publisher differences to absorb: different date filters, token auth (Paraguay), classification schemes (UNSPSC, CPV, national) and currencies.
5. **World Bank procurement notices API.** Keyless JSON; open tenders and award notices in 100+ borrower countries.
6. Later only if asked: ChileCompra (needs personal ticket), Colombia SECOP (Socrata), Contracts Finder.
7. Do not build: India CPPP/GeM, UNGM, ADB, AfDB, Saudi Etimad, UAE (no official open access).

## 11. Rules and cross-cutting notes

- Rule 7 (untrusted data): all tender descriptions are untrusted text; fence them in prompts. This applies especially to `tenderDescription`, `notice_text` (HTML) and OCDS `description`.
- Personal data: AusTender `parties[].contactPoint` and CanadaBuys `contactInfo*` columns contain names, emails and phones. Do not store or render them (as `fts.py` does for UK).
- Attribution: AusTender (CC BY 3.0 AU), CanadaBuys (OGL-Canada), World Bank datasets and several OCDS publishers (CC BY 4.0) require attribution. Colombia SECOP is CC BY-SA 4.0 (share-alike). Add a `source_licence` string per sensor.
- Currency: awards come in AUD, CAD, USD, PYG, etc. Keep currency per claim; do not sum across currencies without conversion.

## 12. Open questions and commands for the founder

1. SAM.gov: create a free account and key, then call `curl "https://api.sam.gov/opportunities/v2/search?api_key=<KEY>&postedFrom=10/01/2026&postedTo=10/08/2026&limit=5&ptype=o&ncode=541511"` and read the quota in the response. Also check if the account has a role (the Contract Awards limit is 10/day without one).
2. AusTender pagination for large windows: `curl -s "https://api.tenders.gov.au/ocds/findByDates/contractPublished/2026-09-01T00:00:00Z/2026-09-08T00:00:00Z" -D -  | head -50` to check headers and size.
3. World Bank params: the two curl commands in section 6.1.
4. Prozorro OCDS shape and licence: read https://prozorro-api-docs.readthedocs.io (Authentication, Rate Control, Feed pages) before building.
5. CanadaBuys: verify no robots/terms restriction on `canadabuys.canada.ca/opendata/pub/` (OGL-Canada covers data; I did not read site terms).
6. Contracts Finder (UK) OCDS API docs URL returned 404 for me; confirm at https://www.contractsfinder.service.gov.uk.
7. India: write to `support-eproc@nic.in` for permission or an API; low priority.
8. Whether SAM.gov Opportunities daily quota allows a nightly poll is **U** until the key exists.
