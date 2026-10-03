# Signal availability probe — are buying moments actually visible?

**Date:** 3 Oct 2026. **Run by:** the orchestrator, at the founder's request, before M3.
**Cost:** $0 (public search and the free TED API; no model calls).

## Why this was run

The open question before building sensors was not "can we fetch pages" but **"do public,
dated buying moments actually exist for a given client, and in what volume?"** If a vertical has
no visible signals, no amount of learning fixes it, and M5's first radar would fail for reasons
that are not code. This probe answers that with live data rather than assumption.

## Headline finding

**Signals are abundant — but not where the naive design looks for them.**

The buyer of materials is almost never the organisation publishing the notice. A council
publishes a road scheme; the company that then needs stone is the **contractor who won it**.
Searching product CPVs finds the trickle; following the award chain finds the flood.

| What you search | Volume (EU-wide) | Verdict |
|---|---|---|
| Stone/paving products (CPV 44912000) | 36 / 3 months | too thin to build a business on |
| Refrigeration equipment (42513000) | 158 / 3 months | thin |
| Packaging machinery (42994000) | 26 / 3 months | thin |
| **Road construction works (45233000)** | **6,112 / 3 months** | the real pool |
| **…of which award notices naming a winner** | **1,190 / 2 months** | **≈600 named contractors a month** |

The last row is the product. Each award notice names a company that *has just won work* and
therefore *is about to buy materials*, with a publication date to measure lag from.

## Evidence (live, 3 Oct 2026)

`POST https://api.ted.europa.eu/v3/notices/search`, CPV 45233000, award notices, Apr–May 2026:

| Date | Country | Buyer | **Winner — the actual prospect** |
|---|---|---|---|
| 2026-04-01 | ESP | Ayuntamiento de El Puerto de Santa María | FIRMES Y CARRETERAS, S.A. |
| 2026-04-01 | DEU | Die Autobahn GmbH des Bundes – NL Nord | Saferoad Restraint Systems GmbH |
| 2026-04-01 | ROU | Directia Generala … Sector 4 | DOMARCONS |
| 2026-04-01 | FRA | Saint-Quentin-en-Yvelines | AXIMUM IDF SUD |

## The frontier/language thesis: confirmed

Every result above is in a language a UK owner does not monitor — Spanish, German, Romanian,
French, Polish. A separate CPV 42513000 query returned `Gmina Mszczonów` (a Polish
municipality) buying refrigeration equipment, published 2026-04-01 with a 2026-04-09 deadline.

This is the strongest part of the product thesis and it is now evidenced, not asserted: these
companies are **publicly identified and dated**, and the owner **cannot see them** — not because
they lack diligence, but because they do not read Polish procurement portals. ARCHITECTURE §0.1
("searches in the buyer's language") is load-bearing, not a nice-to-have.

## Fetchability — a concrete M3 finding

- **TED notice pages and PDFs do not fetch.** Both `…/notice/<id>` and `…/notice/<id>/pdf`
  returned empty content: the site is JavaScript-rendered. A page-fetching sensor would have
  silently produced nothing.
- **The TED Search API works, needs no key, and is free.** `POST
  https://api.ted.europa.eu/v3/notices/search` returned HTTP 200 with structured
  `publication-date`, `deadline-receipt-request`, `buyer-name`, `winner-name`, and per-language
  XML/PDF links. CPV and date-range filters work as documented.
- So the TED sensor must be an **API client, not a scraper**. CLAUDE.md already says "TED API";
  this confirms it was the right call and that the page route is a dead end.

## Where signals are genuinely weaker

A vertical with no public procurement — bespoke packaging sold to private cosmetics brands —
still has signals, but of a different kind: trade press and press releases announcing facility
moves and capacity investments, some with month-level phasing. They are real but
**unstructured, patchy and not enumerable**: you cannot ask "every such event this month" the
way you can of TED.

Honest conclusion: the radar is strongest where buyers are public bodies or where public works
create private buying moments, and weakest in private-to-private niches with no procurement
trail. That is a **client-selection criterion**, not a flaw to engineer away.

## What this changes

1. **The award chain is the product, so the project graph matters sooner than its milestone
   says.** Following funding → tender → award → contractor is currently M6. The probe suggests
   the award→winner hop specifically is what turns a thin trickle into ~600 prospects a month,
   and M5's first radar is weaker without it. Worth pulling that one hop forward.
2. **Search product CPVs *and* works CPVs.** A sensor that only searches what the client sells
   finds 36 notices a quarter. One that searches the works that consume it finds thousands.
3. **Onboarding must ask which works create demand for the offer** — a question for O
   (org-context), answerable in the founder's own words, not hardcoded. No industry words in
   code (CLAUDE.md #1).
4. **Lag is measurable from day one.** Award notices carry dates, so "how long after winning
   does a contractor buy?" is learnable from history rather than guessed — exactly what W's lag
   densities need.

## What this does *not* prove

Volume is not quality. This says the companies are findable, dated and numerous. It says
**nothing** about whether the founder would want to contact them, whether they already know
them, or whether they convert. That remains M5's job and only the founder's rating answers it.
