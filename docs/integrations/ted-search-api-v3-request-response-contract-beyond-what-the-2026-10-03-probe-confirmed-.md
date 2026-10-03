# TED Search API v3: request/response contract

**Checked:** 2026-10-03 by the researcher, with live calls to the production API (no key, free)
plus official TED pages. Extends `signal-availability-probe-2026-10-03.md`.
**Confidence labels:** `[live]` observed in a real response today; `[docs]` stated on an
official page (URL given); `[inferred]`; `[unknown]`. No secrets or personal data in this note
(the example notice is a public Spanish municipal award; contact details deliberately omitted).

## Summary

- `POST https://api.ted.europa.eu/v3/notices/search`, JSON body, **no API key, no auth header**.
  Only `Content-Type: application/json` is needed. [live] [docs: https://docs.ted.europa.eu/api/latest/search.html says it is "openly accessible"]
- Body that works: `{"query": "<expert query>", "fields": [...], "limit": 1..250, "page": n}` or
  `"paginationMode": "ITERATION"` plus `iterationNextToken`. `fields` is **mandatory and non-empty**. [live]
- Hard limits [live]: `limit` max **250**, min 1, default **10** if omitted; page mode window
  `page x limit` max **15000**; ITERATION mode has no window cap.
- Two traps found: (1) ITERATION does not signal the end with a null token (see Pagination);
  (2) bursts of ~14 back-to-back calls produced an nginx HTML **429** with no `Retry-After`.
- Search record is enough for structured facts (winner, buyer, dates, CPV, value, title). The static
  XML is fetchable without JS but contains contact emails/phones: never persist raw XML.
- Licence: notices freely reusable (commercial too); attribution advised; personal data present
  in notices, so redact on commit.
- OJ S publication time of day is **not published anywhere I could find**. The rule
  `available_at = 00:00 UTC of the day after publication-date` is conservative (reasoning below).

## Request contract

### Example (copied from a successful live call)

```json
{
  "query": "classification-cpv=45233000 AND notice-type=can-standard AND publication-date>=20260401 AND publication-date<=20260402",
  "fields": ["publication-number","notice-type","procedure-identifier","publication-date",
             "winner-decision-date","buyer-name","buyer-country","winner-name","winner-country",
             "classification-cpv","notice-title","estimated-value-lot"],
  "limit": 250,
  "page": 1
}
```

Response top level [live]: `{"notices": [...], "totalNoticeCount": 217, "iterationNextToken": null, "timedOut": false}`.
Every notice also carries a `links` object even if not requested (about 3 KB each: XML, PDF, HTML per language), so
**always strip `links` before storing** unless you need a URL.

### Body parameters

| Parameter | Observed behaviour | Conf. |
|---|---|---|
| `query` | Expert-search string, required. Syntax errors give 400 `QUERY_SYNTAX_ERROR` with line/col. | live |
| `fields` | Required, non-empty (`must not be empty` otherwise). Unknown name gives 400 listing all 1830 supported names. Only requested fields come back (plus `links`). A notice simply omits a field it has no value for. | live |
| `limit` | 1 to 250; 0 gives `SEARCH_BELOW_MIN_LIMIT`; 251+ gives `SEARCH_EXCEEDS_MAX_LIMIT` (`maxLimits: 250`). Omitted = 10. | live |
| `page` | 1-based. `page x limit` must be <= 15000 else `SEARCH_WINDOW_TOO_WIDE` (`maxResultWindow: 15000`). Page 41 x 250 (=10250) worked. | live |
| `paginationMode` | Enum `PAGE_NUMBER` (default) or `ITERATION` (error message lists exactly these). | live |
| `iterationNextToken` | Opaque base64 string from previous response, only with ITERATION. | live |
| `scope`, `onlyLatestVersions`, `checkQuerySyntax` | Not tested; Swagger UI at `https://ted.europa.eu/api/documentation/index.html` is JS-rendered and could not be read. | unknown |

Command to confirm the remaining parameters (founder, browser): open
`https://ted.europa.eu/api/documentation/index.html`, expand `POST /v3/notices/search`, read the schema.

### Expert query syntax (all tried live, 2026-04-01 and 2026-10 data)

| Need | Query fragment | Result |
|---|---|---|
| Exact CPV | `classification-cpv=45233000` | works (217 on 1-2 Apr) |
| CPV list | `classification-cpv IN (45233000 45233100)` (space separated) | works, same 217 |
| CPV prefix | `classification-cpv=4523*` | works (237 on 1 Apr) |
| Notice type | `notice-type=can-standard`, or `notice-type IN (cn-standard can-standard)` | works |
| One day | `publication-date=20260401` | works; date format `yyyyMMdd` |
| Range | `publication-date>=20260401 AND publication-date<=20260402` | works |
| Relative | `publication-date>=today(-3)` | works |
| Buyer country | `buyer-country=POL` (ISO 3166-1 alpha-3) | works |
| Place of performance | `place-of-performance-country-lot=ROU` | works |
| Winner country | `winner-country=DEU` | works |
| Deadline | `deadline-receipt-request>=20260601` | works |
| Text contains | `winner-name~Aximum` | works (3 hits); `~` is a text match |
| Combine | `AND`, `OR`, `NOT`, parentheses | `NOT` and parentheses appear in the grammar error; AND/IN used above |

CPV is hierarchical in TED (docs say "business sectors and place of performance are structured
hierarchically"), so `=45233000` may also match descendants; the 217 vs `4523*` 237 difference shows
the exact match is narrower. Verify against your own recall needs [inferred].

## Pagination: use ITERATION, with a defensive stop rule

- PAGE_NUMBER: simple, capped at 15000 results per query. Split a wide query by publication-date
  (one day per query) to stay under it; a single day was 3,400-3,700 notices in all types.
- ITERATION [live]: returns up to 250 per call plus `iterationNextToken`.
  **Trap:** with `totalNoticeCount` 217 and `limit` 250, call 1 returned all 217 and a non-null
  token; call 2 returned **0** notices and a non-null token; call 3 returned the same 217 **again**
  (duplicates). The token is never null at the end.
  Stop rule for the client: stop when a page returns 0 notices, or when the count of unique
  `publication-number` seen >= `totalNoticeCount`. De-duplicate on `publication-number` + `notice-version`.
- Secondary source [docs, via search summary, not the page itself]: iteration/scroll is
  "unlimited", max 250 per page.
- Combining `page` with ITERATION did not error (page was ignored or honoured; page 2 limit 5
  returned the first 5 records). Do not mix them [live].

## Fields: names and value shapes

Mixed shapes are the main parsing risk. Treat **every field as possibly absent**, and every
"list" as possibly repeated/duplicated (CPV lists repeat codes per lot; one deadline list repeated the same
timestamp 30+ times). Normalise with a set.

| Field | Shape [live] | Example |
|---|---|---|
| `publication-number` | scalar string `NNNNNN-YYYY` | `"222468-2026"` |
| `notice-type` | scalar string | `"can-standard"` |
| `notice-subtype` | scalar string (eForms subtype number) | `"29"` (CAN), `"16"` (CN), `"38"` (can-modif) |
| `notice-version` | scalar integer | `1` |
| `notice-identifier` | scalar UUID | `"69ab8fa2-..."` |
| `procedure-identifier` | scalar UUID (links CN, CAN and changes of one procedure) | `"de547b8c-3ee0-49ab-9f3d-05fbd1aef150"` |
| `publication-date` | scalar string date with offset | `"2026-04-01+02:00"` |
| `deadline-receipt-request` | **list** of datetime-with-offset, may repeat | `["2026-06-17T15:00:00+03:00"]` |
| `deadline-receipt-tender-date-lot` / `-time-lot` | list of date / list of time | `["2026-04-16+02:00"]`, `["10:00:00+02:00"]` |
| `winner-decision-date` | **list** of dates with offset | `["2026-02-26+01:00"]` |
| `buyer-name` | **multilingual map**: lang code (lowercase ISO 639-2/B, 3 letters) to list of strings | `{"spa": ["Junta de Gobierno del Ayuntamiento de El Puerto de Santa María"]}` |
| `winner-name` | multilingual map, same shape | `{"spa": ["FIRMES Y CARRETERAS, S.A."]}` |
| `notice-title` | multilingual map, but value is a **string, not a list** (all 24 languages, machine-translated prefix "Country - CPV text -" plus original title) | `{"spa": "España – Servicios de reparación ... – Servicios de mantenimiento urbano ..."}` |
| `buyer-country`, `winner-country`, `place-of-performance-country-lot` | list of ISO alpha-3 | `["ESP"]` |
| `classification-cpv` | list of 8-digit strings, with repeats | `["50230000","45233222","50230000","45233222"]` |
| `estimated-value-lot` | list of numeric **strings** | `["7438016.5"]` |
| `total-value` | scalar **number** (CAN: sum of result values; CN: sum of estimates) | `1082772582.06` |
| `links` | object: `xml` {`MUL`: url}, `pdf`/`pdfs`/`html`/`htmlDirect` each {LANG3 upper: url} | see below |

Notes:
- Currency lives in separate fields (`estimated-value-cur-lot`, `total-value-cur`); request them with the value. Not tested [inferred from the field list].
- The language key for the notice's own language holds the original text; the other keys are
  translations of only the generic part. For buyer/winner names, expect one language key (the original).
- Winners in multi-lot awards: `winner-name` is one map, so lot-to-winner pairing is **not** recoverable from the search
  record. [inferred, one DEU sample showed single winners]. If pairing matters, use the XML.
- Legacy (pre-eForms TED schema, e.g. March 2023) notices returned `notice-title`, `buyer-name`, `classification-cpv`
  but **no `winner-name` or `winner-decision-date`** in the one sample checked. Do not plan history backfill on winners
  before eForms without a larger check [live, n=1].
- Fields present but untried: `change-reason-code`, `change-notice-version-identifier`, `legal-basis`,
  `procedure-type`, `contract-nature`, `winner-size`, `winner-selection-status`, `buyer-legal-type`. Full list:
  trigger the 400 for unknown field name (command below).

### Notice types

Values accepted by `notice-type=` and their April 2026 counts [live, one-month counts, 1-30 Apr]:

| Value | Count | Meaning [inferred from eForms names] |
|---|---|---|
| `cn-standard` | 38,473 | contract notice (the tender; has deadline) |
| `can-standard` | 30,491 | contract award notice (names winner) |
| `can-modif` | 4,005 | contract modification notice (a **change to an awarded contract**) |
| `pin-only` | 973 | prior information notice |
| `cn-social` | 904 | social-services contract notice |
| `veat` | 681 | voluntary ex-ante transparency |
| `pin-rtl` | 471 | PIN used as call for competition |
| `can-desg` / `cn-desg` | 168 / 104 | design contest result / notice |
| `pin-cfc-standard` | 93 | PIN call for competition |
| `qu-sy` | 91 | qualification system |
| `can-social` | (429 hit, not counted) | social-services award; value accepted by the earlier call chain, count unknown |

`notice-type=cn-standard-tender-notice` returns 400 `QUERY_UNSUPPORTED_FIELD_VALUE`, so the API validates values.
The full enum is not in the error. Not exhaustive: other eForms types exist.

**Corrigenda/changes** [docs: https://docs.ted.europa.eu/eforms-common/FAQ/index.html]: "eForms do not use separate
correction/corrigenda forms"; corrections are **Change notices**, a reproduction of the parent notice with a Change
section (BG-9; parent via BT-758, reason BT-140). Original and change are separate published documents. Practical
reading: a changed notice shows up as the same `notice-identifier`/`procedure-identifier` with a higher
`notice-version`; I did not verify a live example of a version-2 CN. [inferred].
`can-modif` (above) is something else: a modification of an awarded contract.

## Dates and times

- Dates: `YYYY-MM-DD` followed by the **publisher's local UTC offset**, not `Z`: `2026-04-01+02:00`,
  `2026-02-26+01:00` (winter offset). Parse with offset-aware parser; take the calendar date as written
  (the offset reflects the Central European zone, DST included). [live]
- Datetimes: `2026-06-17T15:00:00+03:00` (deadlines carry the **buyer's** local offset, e.g. +03:00 for Romania). [live]
- Times: `10:00:00+02:00`. [live]
- Several dates: list fields (deadline, decision date) can hold many entries, duplicates included. Take min/max deliberately.
- Query side uses `yyyyMMdd` with no separators and no offset. [live]
- Non-publication days [live]: `publication-date` counts were 0 for Sat 2026-04-04, Sun 04-05, Mon 04-06
  (Easter Monday), and Sat 2026-10-03; Fri 2026-04-03 had 3,463; Wed 2026-09-30 3,512; Fri 2026-10-02 3,625.
  Consistent with Mon-Fri issues, minus holidays [docs FAQ: "published from Monday to Friday, excluding certain public holidays"].

### Is `available_at = start of next UTC day` conservative?

- Time of day of the OJ S issue: **not stated** on the FAQ, legal notice or API docs I fetched [docs, absent].
  A 2016 TED-XML document (via search summary only, old regime) says 9 a.m.; treat as hint [inferred, weak].
- Evidence in a notice's XML [live]: dispatch `IssueDate` 2026-03-31 + `IssueTime` 07:33:26+02:00 and
  `PublicationDate` 2026-04-01+02:00. So `publication-date` is the OJ S issue date, later than
  dispatch; no publication time is in the XML.
- Argument: `publication-date` D is a calendar date in CET/CEST. Any publication at any time on D falls before
  `D+1 00:00 UTC` unless it occurred after 02:00 CEST on D+1 local, which would contradict the date label. Thus
  `00:00Z on D+1` is an upper bound on public availability, **assuming** TED's date equals the day the notice became visible. [inferred]
- Residual risk: notices might appear in the API later than the issue date (indexing lag). Not measured.
  To measure (founder or recorder, for several days): poll `publication-date=<today>` hourly over UTC and log the first time
  `totalNoticeCount` becomes > 0 and when it stops growing; run on a Tue-Fri. Until measured, state as inferred, not proven.

## Rate limits and errors

- Official fair-usage numbers [docs: https://ted.europa.eu/en/news/fair-usage-policy-on-ted]: **700 HTTP requests per
  minute** and **600 visualisations/downloads in under 6 minutes** per IP; 3 concurrent package downloads. The page
  does not say what happens on breach. TED itself tells technical users to use the public API.
  (The `developers-corner-for-reusers-fair-usage-policy-TED` URL cited in Q&A returned 404 to the fetcher.)
- Observed [live]: after about 14 sequential single-result searches at roughly 0.5 s each, call 14 returned
  **HTTP 429** with `Content-Type: text/html`, an nginx "429 Too Many Requests" body, **no `Retry-After`, no
  `X-RateLimit-*` headers**. A retry about 1 s later succeeded. 30 calls paced at 1.5 s all succeeded. So the
  effective limit is far below 700/min in a burst; one request per 1.5 s is safe. The 429 is **not JSON**: do not
  `resp.json()` before checking the status. [live]
- Anonymous daily cap: none observed or documented [unknown].
- Other errors, all JSON [live]: 400 with `{"message": "...", "error": {"type": "SEARCH_EXCEEDS_MAX_LIMIT" | "SEARCH_BELOW_MIN_LIMIT" |
  "SEARCH_WINDOW_TOO_WIDE" | "QUERY_SYNTAX_ERROR" | "QUERY_UNSUPPORTED_FIELD_VALUE", ...}}`;
  Bean validation errors: `error` is a list of `{objectName, field, message}`; bad JSON enum: `error: null`. 404 JSON for unknown paths.
- Recorder advice: sleep >= 1.5 s between calls, on 429 back off exponentially from 2 s, cap retries, never hammer. Request only
  the fields you need; 250 records x few fields is ~100-400 KB.
- Request time: single small call ~0.7 s.

## Per-notice links: do we need the XML?

- `links.xml.MUL` (`https://ted.europa.eu/en/notice/<pn>/xml`) returned HTTP 200 `application/xml`, 22 KB, with
  `Content-Disposition: attachment`, no JS needed. [live]
- `links.htmlDirect.<LANG>` (`.../notice/<pn>/html`) returned HTTP 200 static `text/html` (40 KB), no JS. [live]
  `links.html.<LANG>` (`.../notice/-/detail/<pn>`) is the JS app page. The 2026-10-03 probe's finding that "notice pages
  and PDFs do not fetch" applies to those; the `/xml` and `/html` forms **do** work. PDF not retested.
- The XML is UBL/eForms. Contains Name, address, and also **ElectronicMail, Telephone, Telefax** of buyer, review body, and
  the winner (`mnb@...` style business addresses) [live].
- Is it needed? For the radar facts (buyer, winner, dates, CPV, value, title) **the search record is enough**. A claim row can
  quote a verbatim value, e.g. `winner-name.spa[0]`. The `documents.text` snapshot for quote-checking can be a canonical JSON
  render of the (links-stripped, PII-free) record, with the source URL `https://ted.europa.eu/en/notice/<pn>/html`.
  Fetch XML/HTML only for what the record lacks: free-text scope descriptions, per-lot winner pairing, award criteria.
  If fetched, extract the wanted text and drop contact elements before storing.

## Licence and personal data

- Reuse [docs: https://ted.europa.eu/en/legal-notice]: "the procurement notices published in the Supplement to the Official
  Journal of the European Union can be freely reused, for commercial or non-commercial purposes" (Commission Decision
  2011/833/EU). TED editorial content is CC BY 4.0 (credit, indicate changes); system metadata is CC0.
  => Committing redacted extracts to the public repo is allowed. Add attribution "Source: TED, Publications Office of the
  European Union, ted.europa.eu" in the fixture README and the repo README. Not legal advice [inferred].
- Personal data [docs, same page]: notices include contact details, names and addresses, processed under Regulation (EU) 2018/1725 and kept
  public on TED ten years. Reuse of those fields is not waived by the licence; CLAUDE.md forbids real contact emails in the repo.
- **Never request these fields** (searchable names confirmed via the 400 field list [live]); patterns, each with many
  `-lot`/`-part` variants: `*-email-*`, `*-tel-*`, `*-fax-*`, `*-person-*`, `*-contact-point-*`, `business-email/fax/tel/contact-point`,
  `buyer-email`, `buyer-person`, `buyer-contact-point`, `winner-email`, `winner-person`, `winner-contact-point`, `ubo-email`, `ubo-fax`,
  `*-internet-address` (URLs are business-level but optional), plus `touchpoint-*` variants.
  Grep helper: `grep -E 'email|tel|fax|person|contact-point|ubo'` over the field list.
- Safe fields for the recorder: `publication-number`, `notice-type`, `notice-subtype`, `notice-version`, `notice-identifier`,
  `procedure-identifier`, `publication-date`, `deadline-receipt-request`, `winner-decision-date`, `buyer-name`, `buyer-country`,
  `winner-name`, `winner-country`, `classification-cpv`, `notice-title`, `estimated-value-lot`, `total-value`, currencies.
- Residual: `winner-name` can be a natural person (sole trader) and `notice-title` can contain a person's name. Fixtures should be
  chosen from companies/public bodies and reviewed.

## Commands for the founder

```bash
# list every supported field name (the 400 message carries all 1830)
curl -s -X POST https://api.ted.europa.eu/v3/notices/search -H 'Content-Type: application/json' \
  -d '{"query":"publication-date=20260401","fields":["x"],"limit":1}'

# smoke test
curl -s -X POST https://api.ted.europa.eu/v3/notices/search -H 'Content-Type: application/json' \
  -d '{"query":"classification-cpv=45233000 AND notice-type=can-standard AND publication-date=20260401","fields":["publication-number","winner-name"],"limit":2}'
```

## Open questions

1. OJ S issue time and API indexing lag (measure with the hourly poll above). `available_at` rule stays "inferred conservative".
2. Rate limit exact threshold and reset window: observed 429 at a ~14-call burst, undocumented; the official 700/min is not what was seen.
3. Remaining body parameters (`scope`, `onlyLatestVersions`, `checkQuerySyntax`) and the full `notice-type` enum: need Swagger UI (browser).
4. Change notices: confirm a live example (same `notice-identifier`, `notice-version` > 1) and whether the search returns all versions or only the latest.
5. Winner-per-lot pairing in multi-lot awards (search record cannot express it).
6. Coverage of winners in legacy-schema notices (n=1 sample had none).
7. Ten-year retention means history before late 2016 is not on TED; not tested.
