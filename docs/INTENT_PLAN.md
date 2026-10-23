# Intent engine - plan for the hackathon demo (24-29 Oct)

Goal (the founder's, from D101): find the **best intent-based leads for any B2B business**.
Fit says WHO, a change says WHEN, connected signals say CERTAIN. Nothing here is written for one
industry: every search phrase and rule comes from the client's own data (offer, buyer roles,
not-buyers, product codes, markets, channel). Demo client: the anonymised stone exporter, markets
UK, US, Germany, France, Italy, UAE, Saudi Arabia, Qatar.

## 1. Opportunities, three plays, three factors (Sat 25)
The unit is an **opportunity**: a company + the reason to talk to it now (its dots) + a play + a
window + the next action. A company can carry several over time; an expired one stops counting.

**Plays** (each needs a different action):
- **Project** - a tender, new establishment or renovation that needs what the client sells, with a
  named contractor, developer or buyer. Act fast: the window closes.
- **Partner** - a channel partner (distributor, dealer) that fits and shows a change (expansion,
  new range, import growth, new owner, hiring buyers). Build a relationship.
- **Account** - proof it already buys the product (imports, a contract for it) and a fresh sign.
  Win share.

**Factors**, each shown in words on the card ("Strong intent - Good fit - 3 sources agree"):
- **Intent** - how strong and how fresh the about-to-buy signal is (contract won this month >
  showroom opened last year; nothing new = none).
- **Fit** - how well it matches what the client sells and who it sells to (own site shows the
  product, matches a priority line, right role).
- **Confidence** - how many independent kinds of source agree (the connected dots).

**Labels the user sees** (the founder's four levels), top to bottom: Connected (strong intent and
2+ kinds of source agree) - Approach now (project) - Build a relationship (partner) - Looking for it
(account) - Watch list (fit, no intent yet). Inside a label: intent, then fit, then confidence, then
the most recent dot. A possible competitor is always last.

**Junk filters, by code, before any model call:** a contract or news lead must name the client's
product words; leads outside the client's markets are dropped; the register's company name is used
everywhere.

**Onboarding gets three questions** (prefilled from the website): which projects or events make a
customer need you; which product lines matter most, in order; 2-3 best customers (private).

## 2. The intent search (Sun 26)
Generated from the client's data, per market (one country per search):
- **Projects:** "new <building types the buyer roles serve> opening / renovation / fit-out
  contract awarded" + the client's product words -> the named contractor or developer is the lead.
- **Distributor changes:** "<channel role> + <product words> + expansion / new showroom / new
  range / acquires" -> the distributor is the lead.
Each result goes through what exists: read the company's own site (fit and role, quoted), the
gate, the skeptic. About 3-4 searches per country per night (about 28 in all; Tavily cap raised
from 20 to 50). Europe also gets TED tenders and awards; the UK keeps Find a Tender, import records
and the register; the US keeps USAspending.

## 3. Connected chains (Sun 26)
Link dots across sources: same registration number or name (exists, D115), plus **project ->
contractor -> supplier** (a contractor named in a project, found again as an importer or in a
contract). The case page's existing chain and history show every dot; Connections draws the chain.

## Showing it (existing screens, no redesign)
Station "to decide" = the top opportunities; each card says the label, the three factors in words,
why now, and one line of what to say. Case page: the full dot chain with sources, evidence against, the window. Map: leads
placed by town (UK postcode) or country. Leads filters become the four levels.

## How we test (Mon 27) - the bar
For 3 industries (stone exporter, refrigeration maker, one untuned): the top 5 of each, judged by
the founder's question "would this business call them today?" - at least 3 of 5 yes. No competitor,
out-of-market lead or broken name in any top 10. WOS hand list re-scored across all markets.

## Fallback
If the intent search is weak on Monday morning, the demo runs on the four-level ranking with the
sources we already have (contracts UK/EU/US, news, register changes, imports). The story holds.

## Not before 29 Oct
Logins and accounts, more clients, data into the database, billing, more countries, job-ad and
trade-show searches. After submission the judges' version is frozen; product work continues
separately.
