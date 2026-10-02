# First radar, by hand: UK prospects for a natural stone shipper (3 Oct 2026)

A manual run of the milestone 5 go/no-go. Four research agents each scouted one type of
signal. The orchestrator then checked every quote in code against the raw text of the live
page.

- **Client (assumed):** an overseas supplier/shipper of natural stone (paving, setts, kerbs,
  walling) into the UK.
- **Buyers:** UK importers/distributors, merchants, landscape and civils contractors, and
  public-realm projects.
- **Gate:** competitors (other exporters and quarries) and directories are rejected.
- **Window:** roughly April to October 2026.
- **Result:** 14 prospects. **15/15 quotes verified verbatim** in raw page text.
- **No personal data:** roles only.

## Ranked brief

| # | Prospect (buyer) | Signal | Date | Why now | Against / unknowns | Strength |
|---|---|---|---|---|---|---|
| 1 | **Chichester City Centre scheme**: West Sussex CC (client); the contractor to be appointed is the buyer | Next phase approved with **York Stone** across main pedestrian areas, about £10.5m | 13 Mar 2026 (procurement now) | Contractor appointment targeted for autumn 2026, start spring 2027: get on the contractor's stone supply list now | Reclaimed stone is part of the plan; quantity unknown | **strong** |
| 2 | **Church St, Downpatrick**: John McQuillan Contracts (contractor), NMDDC / DfC | Started on site Aug 2026 with **granite paving and natural stone kerbs**, about £2.9m | 21 May / 21 Jul 2026 | Contractor named and on site, 12-month programme: orders happening now | Stone may already be ordered; Northern Ireland logistics | **strong–medium** |
| 3 | **Birmingham city-centre public realm**: CPC Civils (contractor), BCC / Central BID | Two-year, six-phase programme installing **granite** | 1 Apr 2026 | Later phases need further granite batches | Supplier probably locked in for the programme | medium |
| 4 | **London Stone** (UK importer/stockist) | Launched a **new limestone paving range** | 19 May 2026 | Actively adding collections, so sourcing now | Has established quarries/suppliers; trade-news source | medium |
| 5 | **Plymouth Civic Centre**: Morgan Sindall (contractor) | £6.49m phase 1 won; "extensive hard and soft landscaping" | 27 Aug 2026 | External packages procured in coming months; linked Armada Way schemes | Material not stated | medium–weak |
| 6 | **45 Moorfields, City of London**: John F Hunt (contractor) / Freshwater | New plaza with hard landscaping; works to Jan 2027 | 28 Aug 2026 | External works package likely late 2026 – Q1 2027 | Material unknown (granite or precast) | medium–weak |
| 7 | **Harrowden / George Davies Turf & Stone** (distributor) | Acquisition completed | 30 Jun 2026 | Post-deal range and supplier review | Mainly turf; stone volume unknown | weak–medium |
| 8 | **Former London City Hall retrofit**: Mace / St Martins | £150m; public realm upgrade of The Scoop and Queen's Walk | 15 Jul 2026 | Early specification window; external works later | Long timeline; local authority may fix the palette | weak–medium |
| 9 | **McMonagle Stone Group** | First southern England location (Rock Unique, Sevenoaks) | 22 Apr 2026 | New footprint may need wider ranges | **Owns quarries: may be a competitor (gate ambiguity)** | weak–medium |
| 10 | **Liscard town centre**: Wirral Council | Design team appointed (£225k) to prepare the construction tender | 30 Sep 2026 | Pipeline: construction tender after design | Design stage; no materials yet | watch |
| 11 | **Derby city-centre public realm**: Derby CC | Strategy published, £1.5m Pride in Place first phase | 30 Jul 2026 | First-phase tenders possible within about 6 months | Strategy only | watch |
| 12 | **York Central (£2bn)**: partnership | Phase 1 planning approved: squares, park, courtyards | 11 Sep 2026 | Building from 2027; hard landscaping about 2028 | Very long timeline; material unconfirmed | watch |
| 13 | **Folkestone town centre**: Jackson Civil Engineering | Granite paving going in on two streets (Levelling Up Fund) | 28 Apr 2026 | Remaining phases or top-ups only | Late stage; local news source | weak |
| 14 | **Travis Perkins** (national merchant) | First landscaping brochure since 2019 (natural stone + porcelain) | 5 Mar 2026 | Category push | Locked supplier panel; possibly an existing customer | weak |

## What this teaches the product

1. **The core promise holds for this client:** real, dated, verifiable buying signals exist on
   the open web, and the strongest ones name the material.
2. **The sequence matters more than any single event.** The scouts saw the same chain of
   stages again and again: strategy or funding → design team → tender → **contractor
   appointed** → on site → stone ordered. The contractor appointment is the key buying moment.
   This is exactly the world learner's "what usually happens next" (§5), and items 10–12 are
   *expectations* to watch, not leads yet.
3. **The buyer is usually the contractor, not the council.** The radar should follow the chain
   to whoever places the order.
4. **Code verification is necessary.** The web-fetch tool returns summaries, so agent "quotes"
   can't be trusted until code finds them in the raw page. This run confirmed all 15.
5. **Coverage gaps are a sensor problem.** Contracts Finder, Bidstats, Horticulture Week and
   one council site returned 403 to plain fetching. Use official APIs and feeds (Find a Tender /
   Contracts Finder: research their APIs in milestone 3) instead of scraping.
6. **Materials are often unstated.** The best next research action is planning documents
   (design and access statements and landscape specifications usually name the paving
   material). This is a good first action for the research-policy learner.
7. **The gate needs a "both" case.** Quarry owners that also distribute (#9) can be buyer and
   competitor at once. That's a judgement question, and a candidate for the owner's feedback.
8. **"Already knew?" matters.** #14 may already be the client's customer.
9. **Cost:** 4 agents, about 200k tokens, about 1 hour including a usage-limit pause, for 14
   verified prospects.

These 14 cases, plus the dropped ones, are good seeds for `tests/golden/` once the gate and
verifier exist. Do not record any personal data.
