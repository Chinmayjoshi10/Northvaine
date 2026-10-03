# Tavily API (search + extract)

Date checked: 2026-10-03. Researcher: factory researcher.
Confidence tags: C = confirmed in official docs, I = inferred, U = unknown.

## Summary

Tavily is plain JSON over HTTPS with Bearer auth. Raw httpx is enough: the SDK adds convenience wrappers
(crawl, map, research, get_search_context, qna_search), none of which the plan needs. Cost is 1 credit
per basic search, 2 per advanced, and about 1 credit per 5 successful extractions. The free tier gives
1,000 credits a month. Three things need the founder's attention: `published_date` is opt-in
(`include_published_date`, beta) and its format is a free-form string; the `days` parameter is not in the
current search reference; and Tavily's terms say nothing explicit either way on storing results or
committing them as fixtures.

## Facts

| # | Fact | Source | Conf. |
|---|------|--------|-------|
| 1 | Base URL `https://api.tavily.com/`; endpoints `POST /search`, `POST /extract` | https://docs.tavily.com/documentation/api-reference/endpoint/search | C |
| 2 | Auth: header `Authorization: Bearer tvly-<key>` | same | C |
| 3 | Search `query` (required string) | same | C |
| 4 | `search_depth`: `basic` (default), `advanced`, `fast`, `ultra-fast` | same | C |
| 5 | `topic`: `general` (default), `news`, `finance` | same | C |
| 6 | `max_results`: int 0-20, default 10 | same | C |
| 7 | `time_range`: day/week/month/year (or d/w/m/y), default null | same | C |
| 8 | `start_date`, `end_date`: `YYYY-MM-DD` strings | same | C |
| 9 | `days` is NOT in the current search reference (older docs had it for `topic=news`). Use `time_range` or `start_date`/`end_date`. | same | C (absent); U (whether still accepted) |
| 10 | `include_raw_content`: false (default), true, `"markdown"`, `"text"` | same | C |
| 11 | `include_domains` (max 300), `exclude_domains` (max 150); `include_domains_mode`: `restrict` (default) or `prefer` | same | C |
| 12 | `country`: country name such as `"united states"`; only for `topic=general`; boosts, does not filter | same | C |
| 13 | Other useful params: `chunks_per_source` (1-3), `include_answer`, `include_usage`, `language`, `filter_by_language`, `exact_match`, `auto_parameters` (may silently choose advanced = 2 credits; leave off), `include_published_date`, `filter_by_published_date` | same | C |
| 14 | Search response: `query`, `answer`, `images`, `results[]`, `response_time`, `usage`, `request_id`. Each result has `title`, `url`, `content` (snippet), `score` (float), `raw_content` (only if requested), `published_date`, `favicon`, `id` | same | C |
| 15 | `published_date` is only returned when `include_published_date=true` (marked beta) or `filter_by_published_date=true`. It is a "publication/update date estimate or null". Docs example shows RFC 1123 text `"Tue, 11 Mar 2025 17:00:00 GMT"`. The format is not formally specified, so parse defensively and allow null. | same | C (opt-in, example); U (format guarantee, and whether `general` returns it for every result) |
| 16 | Extract params: `urls` (string or array, 1-20), `extract_depth` `basic` (default) or `advanced`, `format` `markdown` (default) or `text`, `query`, `chunks_per_source` (1-5), `include_images`, `include_favicon`, `timeout` (1.0-60.0 s; default 10 s basic, 30 s advanced), `include_usage` | https://docs.tavily.com/documentation/api-reference/endpoint/extract | C |
| 17 | Extract response: `results[]` (`url`, `raw_content`, `images`, `favicon`), `failed_results[]` (url + error), `response_time`, `usage`, `request_id`. HTTP 200 can include failures, so always check `failed_results`. | same | C |
| 18 | Credits: search basic/fast/ultra-fast 1, advanced 2. Extract basic 1 credit per 5 successful extractions, advanced 2 per 5. Map: 1 per 10 pages. | search reference page; https://docs.tavily.com/documentation/api-credits | C |
| 19 | Free tier: 1,000 credits/month, no card. Pay-as-you-go $0.008/credit. Paid plans $30-$500/month (4,000-100,000 credits). | https://docs.tavily.com/documentation/api-credits | C |
| 20 | Rate limits: dev key 100 RPM, production key 1,000 RPM. Production needs a paid plan or PAYGO. These are the default limits; per-endpoint limits for search and extract are not listed separately. | https://docs.tavily.com/documentation/rate-limits | C |
| 21 | Errors: 400 bad params; 401 bad/missing key; 422 validation; 429 rate limit (read `Retry-After`, do not match message text); 432 plan limit exceeded; 433 pay-as-you-go limit exceeded; 500 server | search and extract reference pages; rate-limits page | C |
| 22 | SDK `tavily-python` adds: crawl, map, get_search_context, qna_search, research, feedback, an async client, and tracking headers (`X-Project-ID`, `X-Session-Id`, `X-Human-Id`, `X-Client-Name`). Search and extract are the same HTTP calls. Nothing needed for search/extract is SDK-only. | https://github.com/tavily-ai/tavily-python | C (README summary); I (headers optional) |
| 23 | Terms (effective 4 May 2026): Tavily may retain inputs and outputs to train and improve its models (6.5) and gets a broad licence to Customer content (9.2); customers may not use outputs in a way that violates the agreement or third-party policies, or to build competing models (6.6). No clause found that forbids or allows storing results in your own database, and none about test fixtures. | https://www.tavily.com/terms | C (clauses as summarised); U (no explicit storage clause) |

## Request and response examples

From docs (search):

```
POST https://api.tavily.com/search
Authorization: Bearer <YOUR_TAVILY_API_KEY>
Content-Type: application/json
```

```json
{
  "query": "Who is Leo Messi?",
  "results": [
    {
      "title": "Lionel Messi Facts | Britannica",
      "url": "https://www.britannica.com/facts/Lionel-Messi",
      "content": "Argentine footballer, widely regarded as one of the greatest...",
      "score": 0.81025416,
      "published_date": "Tue, 11 Mar 2025 17:00:00 GMT",
      "favicon": "https://britannica.com/favicon.png",
      "id": "a3f9c2-04"
    }
  ],
  "response_time": 1.67,
  "usage": {"credits": 1},
  "request_id": "123e4567-e89b-12d3-a456-426614174111"
}
```

Request body shape the plan needs (assembled from the parameter tables; not a copied docs example):

```json
{"query": "...", "topic": "news", "search_depth": "basic", "max_results": 10,
 "start_date": "2026-09-01", "include_published_date": true,
 "include_domains": [], "exclude_domains": [], "include_usage": true}
```

Extract: `{"urls": ["https://example.com/page"], "extract_depth": "basic", "format": "markdown"}`.

## Limits

- 1,000 free credits per month. The daily budget guard should count `usage.credits` (request `include_usage`).
- 100 RPM on a dev key. Retry on 429 using `Retry-After`.
- 432 and 433 are budget stops, not transient: do not retry, and surface them as "provider budget exhausted".
- Extract: at most 20 URLs per call; a 200 response can contain `failed_results`.

## Terms of service on storage and fixtures

- Storing results in `documents` as snapshots: the terms contain no clause prohibiting it, and none granting an explicit right either. The only restrictions found concern violating other agreements or third-party policies, and building competing models. Fetched source pages also carry their own publishers' rights; our "no source, no claim" design stores snapshots for evidence, which is ordinary use. Confidence: inferred, not confirmed.
- Committing redacted responses as fixtures: not addressed. Low risk if fixtures are small, redacted, and contain no API key, `request_id` or personal data. This is a reading, not something the docs confirm. Ask the founder to accept the risk, or email Tavily support for a written answer.
- The terms page was read through a summarising fetch tool, not verbatim. Re-read https://www.tavily.com/terms sections 6 and 9 before the public repo goes live.

## Open questions

1. Does `topic=general` return `published_date` per result when `include_published_date=true`, and for what share of results? Confirm with the command below.
2. Is `days` still accepted for `topic=news`? Use `start_date`/`end_date` unless proven needed.
3. Per-endpoint rate limits for search and extract (docs list only default RPM).
4. Does an extract cost 0 credits when all URLs fail? Docs say "per successful extractions", so inferred yes.
5. Written answer on fixture and storage terms (see above).

Confirm 1 and 2 with a real key (take it from `.env`; never print it):

```
curl -s https://api.tavily.com/search -H "Authorization: Bearer $TAVILY_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"granite import tender","topic":"general","max_results":5,"include_published_date":true,"include_usage":true}'
```

Run the same with `"topic":"news","days":7` to see whether `days` is accepted or rejected with 400/422.
