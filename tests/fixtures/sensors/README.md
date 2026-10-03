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
