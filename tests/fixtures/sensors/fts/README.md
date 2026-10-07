# FTS fixtures (UK Find a Tender, OCDS release packages)

Recorded once from the live API (free, no key) on 2026-10-08 by running `FtsSensor` through
`replay.RecordingTransport`; the files are `RecordedExchange` lists (see `../README.md`).

| file | exchanges | what |
|---|---|---|
| `both_kinds_1.json` | 1 | `limit=8`, window 2026-10-02 (00:00:00 to 23:59:59), first page, has `links.next` |
| `both_kinds_2.json` | 2 | pages 2 and 3 of the same query, read with the cursor from page 1 |

Request URLs are exactly what the sensor sends (`limit`, `updatedFrom`, `updatedTo`, `cursor`),
so replay matches by URL. The recorded releases hold tender, tender-update, award/contract,
award-update, planning and cancellation tags, and one framework award with many suppliers.

## Redaction (applied before commit; the recorder also refuses to write a surviving email)

- Every key containing `contactPoint` (including `additionalContactPoints`), and every
  `email`, `telephone`, `faxNumber`, `streetAddress`, `postalCode` key, is removed.
- Email addresses inside free text are replaced by `[email removed]`; phone-like numbers in
  free text by `[phone removed]` (none were found after the key removal).
- Two supplier names that read as individual sole traders were replaced by
  `[natural person redacted 1]` and `[natural person redacted 2]`. The sensor's own marker list
  (`ted_natural_person_markers`, German and French legal forms) does not recognise UK sole
  traders, so this is by-eye review, as for TED.
- Public bodies, companies and notice text are otherwise as published.

## Attribution

Contains public sector information published by the Find a Tender Service, licensed under the
Open Government Licence v3.0.
