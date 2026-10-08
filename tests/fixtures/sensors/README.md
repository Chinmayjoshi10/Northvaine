# Sensor fixtures

Recorded HTTP exchanges for the TED and Tavily sensors. They are recorded once from the live
APIs by the orchestrator (`tasks.py record-sensors`), never written by hand (D42). Synthetic
HTML is allowed only for fetch, SSRF, robots and website tests, which test our own code.

## Layout

```
tests/fixtures/sensors/<sensor>/<client>_<n>.json
```

`<sensor>` is `ted` or `tavily`; `<client>` is a sample client's file stem from
`tests/fixtures/clients/`; `<n>` is the page or call number, starting at 1.

Each file is a JSON list of `RecordedExchange` objects (`northvaine/sensors/replay.py`):

| field | meaning |
|---|---|
| `method`, `url` | the request line |
| `request_json` | the JSON body that was sent (from `ted.build_request` / `tavily.build_search_request`), or null |
| `status` | HTTP status |
| `headers` | an allow-listed subset of response headers (content type, retry-after) |
| `body_json` / `body_text` | the response, as JSON when it parses, else text |
| `recorded_at` | ISO 8601 time with offset |

## Redaction rules

- No API key or Authorization header, ever. Tavily `request_id` is removed.
- TED `links` is stripped. Only the fields in `ted.TED_SAFE_FIELDS` are requested, so no email,
  phone, fax, person, contact point, beneficial owner or internet address is present.
- The recorder refuses to write a file in which an email address or phone number survives.
- The orchestrator reviews every new fixture by eye before committing (sole traders, people in
  notice titles). Choose companies and public bodies.

## Attribution

Source: TED, Publications Office of the European Union, ted.europa.eu

## Natural-person redaction (orchestrator review, 2026-10-04)

The by-eye review of the TED recording replaced three `winner-name` values whose legal form makes
the name a natural person (a German sole trader `e.K.` naming its owner, a `GbR` of two named
individuals, a French `Ets` with a full personal name) with `[natural person redacted N]`.
Limited companies named after founders (GmbH, S.A., SARL...) are legal entities and are kept.
Placeholders are distinct, so de-duplication behaviour is unchanged.

## Tavily recording and redaction (orchestrator review, 2026-10-04)

Recorded with `tasks.py record-sensors`; 3 of 8 Tavily responses were refused by the recorder
(an email or phone survived), so `coldchain_maker_1`, `packaging_supplier_1` and
`stone_supplier_3` have no Tavily fixture. The TED folder was restored from git after the run
(old windows are never re-recorded, D36 note). By-eye review then:

- replaced `title`, `content` and `raw_content` of social-media results (Facebook, Instagram,
  LinkedIn) with `[social media post redacted]`, keeping `url` and `published_date` (often null)
  so the result shape is unchanged;
- truncated any `raw_content` over 1,500 characters, marked ` [truncated]` (third-party page text);
- replaced two journalist bylines with `[journalist redacted]`.

## USAspending (D90)

`usaspending/awards_1.json` is two live pages of a keyless `spending_by_award` search (NAICS
237310, awards signed 20-30 Sep 2026), recorded 2026-10-09 from the request that
`usaspending.build_request` builds. Only the fields in `USASPENDING_FIELDS` were requested, so
no address or contact is present. `internal_id`, `awarding_agency_id`, `agency_slug` and the API
`messages` were removed. Reviewed by eye: all twelve recipients are companies. US federal data
is public.
