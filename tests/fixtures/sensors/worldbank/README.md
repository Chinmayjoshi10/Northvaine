# World Bank fixtures (procurement notices, `search.worldbank.org/api/v2/procnotices`)

Recorded once from the live API (free, no key) on 2026-10-09 by running `WorldBankSensor`
through `replay.RecordingTransport` with `worldbank_page_size=6`; the files are
`RecordedExchange` lists (see `../README.md`). Request URLs are exactly what the sensor sends,
so replay matches by URL.

| file | exchanges | what |
|---|---|---|
| `tender_1.json` | 3 | a one-row probe for the newest date, then `Invitation for Bids` offsets 0 and 6 (12 notices dated 2026-10-07) |
| `award_1.json` | 3 | the probe, then `Contract Award` offsets 0 and 6 (8 notices used; `notice_text` HTML kept) |
| `seek_1.json` | 18 | bisection for 2026-03-02 (one-row probes of `id` and `noticedate`), then one award page |

## Redaction (applied before commit)

- The sensor never requests `contact_*` fields, so no contact name, email, phone or address was
  ever recorded. `notice_text` is requested for awards only.
- In award text: the free text between a bidder's name and its `Country:` line (postal
  addresses, sometimes emails and phone numbers) is removed; beneficial-owner table rows (names
  of people) are replaced by `[beneficial owner redacted]`; any remaining email becomes
  `[email removed]`. The redaction step refuses to write a file in which an email survives.
- Five winner or bidder names that read as individuals or sole traders were replaced by
  `[natural person redacted 1..5]`. The sensor's markers cannot recognise these (see D91), so
  this is by-eye review, as for TED and FTS. Public bodies, companies and the rest of the notice
  are as published.

## Attribution

Source: World Bank Procurement Notices, The World Bank Group, licensed under Creative Commons
Attribution 4.0 (CC BY 4.0).
