# Next build: account chain plus commercial evidence levels (ChatGPT CEO priorities, 9 Oct)

## 1. Contract nature (code-only, from official fields)

- **FTS:** OCDS `tender.mainProcurementCategory`, with values goods, works or services.
- **TED:** `contract-nature`, CONFIRMED by a live probe on 9 Oct 2026. It works as a query key and as a returned field, giving a list with one value per lot, for example ["supplies","supplies"].
- **World Bank:** "Procurement group" (GO = goods, CW = works, CS/NC = services). Already a line
  in its records (D91).
- **Rendering:** a structured line `Contract nature: supplies|works|services`. The record already
  carries the slot.

## 2. Account role per entry (code, from roles plus nature)

| Role | Meaning |
| --- | --- |
| `direct_purchaser` | the buyer of a supplies tender or award naming the offer |
| `demand_source` | the buyer of a works or services tender: not the material buyer |
| `awarded_contractor` | the winner of a works award: an account candidate |
| `supplier` | the winner of a supplies award: a competitor or channel; the gate already handles this |
| `unresolved` | anything else |

## 3. Commercial evidence level (replaces or extends stated/related/inferred)

1. `explicit_purchase`: a stated requirement AND role `direct_purchaser`, with an open or recent
   window.
2. `project_requirement`: a stated or related requirement where the buyer is not the material
   buyer (`demand_source`, or `awarded_contractor` without a catalogue fit yet).
3. `company_fit`: catalogue or website evidence that the company handles the category. Needs
   the website cross-check (step 5).
4. `generic_mention`: a word match without a supported commercial relationship.
5. `no_evidence`: inference only.

**Contact now** needs `explicit_purchase` (or `project_requirement` AND `company_fit`, for an
awarded contractor), no skeptic point against, and evidence that is not weak. Everything else is
qualify first or watch only.

## 4. Chain in the brief and the API

For an awarded contractor, show the chain from graph links: procedure (title, authority) →
award (date, value caveat) → this company → "likely buys: <offer> for <lot>". Each line has its
claim refs.

For a tender (watch only), show the likely bidders as the accounts to approach after the award.

## 5. Company-fit cross-check (website sensor)

- For shortlisted accounts (top N awarded contractors), fetch the official site's
  products/services/projects pages through the existing website sensor (robots respected, D59).
- Extract claims, then quote-check them.
- A fit claim is stored separately (`fit` events, no date) and shown in its own section,
  "Company fit (not a purchase)".

## 6. Outcome data contract

- `feedback` gains reason codes as a closed set.
- Scorecard fields (known account, new intelligence, accepted for contact, contacted, outcome)
  go into a table `case_outcome_reports` or into feedback columns.
- The API writes them; learning reads them without parsing Markdown.

## Gates (from CEO)

- No displayed claim without a quote.
- An authority is never shown as the material buyer.
- Contact now needs a supported requirement AND a supported account role.
- Fit is shown separately from demand.
- Machine-readable reasons are kept.
- Ranking is deterministic.
- No industry literals.
- Recordings stay replayable.
