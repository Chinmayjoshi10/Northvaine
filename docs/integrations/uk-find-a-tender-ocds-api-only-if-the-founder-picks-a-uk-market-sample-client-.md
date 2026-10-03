# UK Find a Tender OCDS API (only if the founder picks a UK-market sample client)

Date checked: 2026-10-03 (live calls made 2026-10-03, about 18:30 UK time).
Confidence key: **C-docs** = confirmed in official docs; **C-live** = confirmed by a live call
to the real API during this check; **inferred**; **unknown**.

## Summary

- Find a Tender (FTS) has a free, no-auth REST API that returns notices as OCDS release packages.
  Licence is Open Government Licence v3.0. Safe to use under the project's rules (public API,
  no scraping).
- **It carries Procurement Act 2023 (PA23) notices and legacy (Procurement Regulations 2015)
  notices in one feed**, including below-threshold PA23 notices. One source is enough for
  new procurements started on or after 24 Feb 2025.
- **Trap found by live test: the `stages` filter returns only legacy notices.** PA23 notices
  (tag `planning`/`tender`/`award`, legal basis `2023/54`) come back only when `stages` is
  omitted. Filter by `tag` in our own code instead.
- Rate limiting is real: after about 15 requests in a few minutes we got `429` with
  `Retry-After: 120`. Design the sensor to back off and to ask for narrow time windows.
- Ordering is not by `date`. Do not assume sorted output; page through the cursor and
  de-duplicate on `id`.

## Facts table

| # | Fact | Source | Confidence |
|---|------|--------|-----------|
| 1 | Release-package endpoint: `GET https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages` (path is `/api/{version}/ocdsReleasePackages`, version `1.0`) | https://www.find-tender.service.gov.uk/apidocumentation/1.0/GET-ocdsReleasePackages | C-docs, C-live |
| 2 | Record-package endpoint: `GET /api/1.0/ocdsRecordPackages` (compiled/versioned view per ocid; optional ocid appended; no listing params) | https://www.find-tender.service.gov.uk/apidocumentation/1.0/GET-ocdsRecordPackages | C-docs |
| 3 | No authentication: a plain `curl` with no key/header returned 200. Docs pages do not mention any key; a third-party actor description says "requires no authentication" | live call; https://apify.com/civicrows/uk-find-a-tender-notices (third party, last resort) | C-live (docs silent) |
| 4 | Query params: `limit` (int, default 100, min 1, max 100), `cursor` (string, max 300 chars, `[A-Za-z0-9=]*`), `updatedFrom`, `updatedTo` (format `YYYY-MM-DDTHH:MM:SS`, no timezone suffix), `stages` (`planning,tender,award`) | release-package doc above | C-docs |
| 5 | `limit` above 100 returns HTTP 400 `'limit' must not exceed the maximum value` | live call | C-live |
| 6 | Unknown parameter returns 400 "Request parameters unknown" with allowed list | release-package doc | C-docs |
| 7 | Single notice or procurement filter: append notice id (`nnnnnn-yyyy`) or ocid (`ocds-h6vhtk-hhhhhh`) to the URI | release-package doc | C-docs (not tested live) |
| 8 | Pagination: response has `links.next`, a full URL including `cursor`. The cursor is base64 of `updatedFrom=...|updatedTo=...|nextCursor=<integer id>`. Last page has no `links.next` (or no `links` at all) | live call | C-live |
| 9 | If `updatedTo` is omitted the server fills it with "now" (echoed in `uri`) | live call | C-live |
| 10 | Rate limit: HTTP 429 "Too Many Requests" with `Retry-After` header; observed `Retry-After: 120` after about 15 requests in a few minutes. Numeric quota is not published. 503 also carries `Retry-After` | release-package doc (429/503); live call (120 s) | C-docs for behaviour, C-live for value; quota unknown |
| 11 | No rate-limit headers (`X-RateLimit-*`) were present on 200 responses | live call | C-live |
| 12 | Licence: Open Government Licence v3.0 (response field `license` = `http://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/`). Attribution to the publisher is required by OGL | https://www.find-tender.service.gov.uk/Developer/Documentation ; live response | C-docs, C-live |
| 13 | OCDS version: fields mapped to OCDS 1.1.5 with extensions (EU profile and others); response `version` is `"1.1"` | Developer/Documentation page; live response | C-docs, C-live |
| 14 | Package-level `publishedDate`, `publisher`, `publicationPolicy`, `license`, `extensions` are present | live response | C-live |
| 15 | Volume: about 503 releases for the single day 2026-10-02 (about 233 PA23 award/contract, 97 PA23 tender, 41 PA23 planning, 55 legacy award, plus updates/cancellations). Six pages at limit 100 | live paging | C-live |
| 16 | The same notice can appear more than once across time (updates appear as new releases with tags `tenderUpdate`, `awardUpdate`, `contractUpdate`, `planningUpdate`, `tenderCancellation`) | live call | C-live |

## PA23 versus legacy: which notices are where

| Question | Answer | Source | Confidence |
|---|---|---|---|
| Is FTS the publication point for new procurements? | Yes. From 24 Feb 2025 both above-threshold and below-threshold notices for new UK procurements are published on FTS (below-threshold in Scotland excepted) | https://www.gov.uk/government/publications/ppn-019-requirements-to-publish-on-contracts-finder/update-to-legal-requirements-to-publish-procurement-information-on-contracts-finder (via search summary and fetch) | C-docs |
| Does PA23 require Contracts Finder publication? | No. Procurements commenced from 24 Feb 2025 need notices only on FTS | same PPN 019 / transparency guidance https://assets.publishing.service.gov.uk/media/67ea9b74f0edd954a99fe96a/2025-03-06_Guidance_on_transparency_requirements_for_publishing_on_Contracts_Finder_-_legislative_requirements_-_Final_.pdf | C-docs (read through summaries, not full text) |
| What still goes to Contracts Finder? | Procurements advertised and not yet awarded before 24 Feb 2025 (PCR 2015 transitional) still follow the old Contracts Finder rules. Thresholds there: central government £12,000, sub-central and NHS £30,000 (inc VAT). The PPN does not apply to wholly or mainly devolved Scottish, Welsh or Northern Irish functions | PPN 019 page above | C-docs |
| PA23 notice types (names) | UK1 pipeline, UK2 preliminary market engagement, UK3 planned procurement, UK4 tender, UK5 transparency (direct award), UK6 contract award (starts standstill), UK7 contract details (after signing), UK9 contract performance, UK10 contract change, UK11 contract termination, UK12 procurement termination, UK13-UK16 dynamic market, UK17 payments compliance. Legacy: F01-F25, T01-T02 | https://www.find-tender.service.gov.uk/Home/NoticeTypes | C-docs |
| Are PA23 notices in the OCDS API? | Yes. Live releases have `tender.legalBasis.id = "2023/54"`, `scheme = "UKPGA"`, `uri = https://www.legislation.gov.uk/ukpga/2023/54/contents`, and `noticeType` values UK4, UK7, UK12, UK15 were observed in `documents[]`/`contracts[].documents[]`. Legacy notices show `32014L0024` (public contracts) or `32014L0025` (utilities), scheme `CELEX` | live calls | C-live |
| Are below-threshold PA23 notices in the API? | Yes. Example tender 093572-2026 has `tender.aboveThreshold = false` and `procurementMethodDetails = "Below threshold - open competition"` | live call | C-live |
| Does `stages=` work for PA23? | **No.** On 2026-10-02: no filter gave 503 releases (about 380 PA23); `stages=award` gave 56 (all legacy), `stages=tender` gave 7 (all legacy), `stages=planning` gave 3 (all legacy) | live calls | C-live |
| Is one source sufficient? | For a lead-finding product: yes, FTS only, for anything started on/after 24 Feb 2025, plus legacy notices still being awarded. Contracts Finder adds only pre-Feb-2025 leftovers and below-threshold legacy contracts that a client is unlikely to need. Caveats: Scottish below-threshold notices go elsewhere (Public Contracts Scotland, not checked here); some PA23 notice types may be edited via e-procurement vendors only | PPN 019; NoticeTypes page | Inferred from C-docs |

## Field paths (confirmed on live notices)

All paths are relative to one element of `releases[]`.

| Need | PA23 tender notice (UK4) | PA23 award/contract details (UK7) | Legacy tender / award |
|---|---|---|---|
| Notice id | `id` (e.g. `093572-2026`) | `id` | `id` |
| Procurement id | `ocid` (`ocds-h6vhtk-xxxxxx`) | `ocid` | `ocid` |
| Stage | `tag[]` (`tender`, `planning`, `award`, `contract`, plus `...Update`, `tenderCancellation`) | `tag[]` | `tag[]` |
| Published/updated timestamp | `date` | `date`; also `contracts[].documents[].datePublished` | `date` |
| Tender deadline (submission) | `tender.tenderPeriod.endDate` | n/a | `tender.tenderPeriod.endDate` |
| Enquiry deadline | `tender.enquiryPeriod.endDate` | n/a | not seen |
| Award decision date | n/a | `contracts[].dateSigned` (signing date; UK7). No separate award-decision date seen in our samples (inferred: UK6 contract award notice may carry one; not confirmed) | `contracts[].dateSigned` |
| Contract period | `tender.lots[].contractPeriod.startDate/endDate/maxExtentDate` | `contracts[].period.startDate/endDate` | `tender.lots[].contractPeriod.*` |
| Supplier name | n/a | `awards[].suppliers[].name`, `awards[].suppliers[].id` (e.g. `GB-COH-08151565`); also `parties[]` with `roles` containing `supplier` | `awards[].suppliers[].name`; `parties[]` roles `supplier` |
| Buyer | `buyer.name`, `buyer.id` (e.g. `GB-PPON-...`, `GB-UKPRN-...`, `GB-FTS-...`); `parties[]` with role `buyer` (address, `contactPoint` incl. email) | same | same |
| CPV | `tender.items[].additionalClassifications[]` with `scheme = "CPV"`, `.id`, `.description` (PA23 samples) | `awards[].items[].additionalClassifications[]` | `tender.classification` (`scheme` CPV, `id`) plus `tender.items[].additionalClassifications[]` |
| Value | `tender.value.amount` (ex VAT) and `amountGross`, `currency` | `contracts[].value.amount`, `amountGross` | `tender.value.amount`, `contracts[].value.amount` |
| Title / description | `tender.title`, `tender.description` | `tender.title` (may be absent) | same |
| Threshold flag | `tender.aboveThreshold` | `contracts[].aboveThreshold` | not seen |
| Notice link | `tender.documents[].url` (attachments) | `contracts[].documents[].url` (`https://www.find-tender.service.gov.uk/Notice/<id>`) | n/a |
| Legal basis | `tender.legalBasis.id` (`2023/54`) | same | `32014L0024` / `32014L0025` |
| Delivery region | `tender.items[].deliveryAddresses[].region` (NUTS, e.g. `UKC1`) | `awards[].items[].deliveryAddresses[]` | same |

Notes: `tender.amendments[]` appears on modification notices. Some PA23 award releases list a
supplier with role `removedSupplier` (dynamic market modification, UK15). `parties[].contactPoint`
holds personal data (names, emails, phones); the project rule on contacts applies: store only
what the claim needs and never commit samples.

## Examples (real calls, trimmed)

```
GET https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?limit=100&updatedFrom=2026-10-02T00:00:00&updatedTo=2026-10-03T00:00:00
-> 200, { "uri":..., "version":"1.1", "publishedDate":..., "license":"http://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
          "releases":[...up to 100...], "links":{"next":"https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?limit=100&updatedFrom=...&updatedTo=...&cursor=<base64>"} }

GET .../ocdsReleasePackages?limit=500      -> 400 "'limit' must not exceed the maximum value"
GET .../api/2.0/ocdsReleasePackages        -> 400 (no version 2.0 exists)
(15 or so rapid requests)                  -> 429, Retry-After: 120
```

## Limits and design notes

- Max page size 100. About 500 notices per day: a daily poll needs about 6 requests.
- Poll by `updatedFrom`/`updatedTo` windows; follow `links.next` until absent; de-duplicate on
  `id`; keep the highest `date` seen as the next `updatedFrom`. Overlap windows slightly.
- **Do not use `stages`.** Filter on `tag` and `tender.legalBasis.id` in code.
- Treat 429 and 503 as normal: sleep for `Retry-After` (observed 120 s), then retry the same URL.
  Keep a gap of at least a second or two between requests.
- Remember project rule 7: notice text (`description`, `title`) is untrusted data; fence it in prompts.
- Tests must use saved fixtures, not live calls.

## Open questions (not confirmed)

1. Numeric rate-limit quota (requests per minute). Not published; we only know 429 appears fast.
   Founder can measure: loop 30 requests with `curl -s -o /dev/null -w "%{http_code}\n" "<url>"` and note where 429 starts.
2. Exactly why `stages` excludes PA23 notices (possible API bug or intended legacy mapping). Check the
   how-to guide https://www.find-tender.service.gov.uk/apidocumentation/api-how-to-guide (fetch returned no usable content) or ask FTS support.
3. Whether a PA23 UK6 contract award notice exposes a distinct award-decision date field. Our samples
   were UK7 (signing date) only.
4. Whether `updatedFrom` filters on `date` of the release or on an internal modification time (the
   ordering is not by `date`).
5. Scotland below-threshold coverage (Public Contracts Scotland), Wales and Northern Ireland specifics.
6. The PPN 019 and transparency guidance were read through fetch summaries, not word for word.
   Confirm the legal wording if it matters for a public claim.
