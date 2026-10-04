# Milestone 5 plan: First Reviewable Radar

status: **approved** (orchestrator, 5 Oct 2026; founder answered Q1 and Q2 on 5 Oct)
date: 2026-10-05
baseline: `main` at 3ac2e7a (M4 closed: gate green, 1083 unit + 50 golden, migration head 0005).
requirements: `docs/COLLAB.md` (ChatGPT's M5 brief + Claude's five corrections), `factory/reports/M4.md`
"Quality facts carried into M5", `docs/LATER.md` items tagged M5, DECISIONS D19-D56.

## Goal

One command per client turns public sources into a **readable Markdown brief the founder can
judge**, through one generic pipeline:

```
discover (sensors, queries shifted to the run date)
  -> lead upgrade (snippet URL -> robots + deny list + safe_fetch -> website document)
  -> extract + verify (M4 ledger; extractor v2 now names the company)
  -> identify the company (grounded subject mention -> match key -> one candidate per company)
  -> buyer-or-seller gate (code: unidentified; LLM mid: competitor / reseller / publisher /
     not_a_buyer / not_an_organisation) BEFORE any investigation; rejections kept with rejected_as
  -> skeptic (evidence against, cited, or 'unknown' + open questions)
  -> simple explained ranking (evidence strength, window urgency / recency, direct buyer)
  -> reports/radar/<client>/<date>/brief.md + scorecard.md + run.json
```

```
uv run python scripts/tasks.py radar -- --client stone_supplier          # offline replay (default)
uv run python scripts/tasks.py record-radar -- --client stone_supplier --yes   # orchestrator only
```

Each brief entry answers the nine questions (who, what happened, when, why it creates demand,
exact evidence, source, why a buyer and not a competitor/publisher, what is uncertain, suggested
action), states its **stream** (tender / award = enumerable, announcement = not enumerable) and
its **timing window**, and contains facts only from verified claims. Same code for all three
sample clients. No contact-person data. No sending.

## Waves

| Wave | Tickets | Gate to the next step |
|---|---|---|
| 0 | **T5.1** identify the company, part 1: extractor v2 (subject, role, date required; tight event types) · **T5.0** contracts (radar models, settings, skeletons, LLM output schemas, invariant rules, `.gitignore`) | T5.0: mechanical check. **T5.1: Checkpoint A** (below) on its branch before merge |
| - | **Checkpoint A (orchestrator, on the T5.1 branch):** `tasks.py record-llm -- --yes` re-records `tests/fixtures/llm/ledger/` with prompt v2 (~$0.01); read by eye; T5.1's proof test runs on the new recordings; then merge | **GO** if the proof thresholds hold; else one more prompt iteration (v3) before wave 1; second failure goes to the founder |
| 1 | **T5.2** identify the company, part 2: entity match key + candidates + windows · **T5.3** discover + lead upgrade · **T5.4** gate + skeptic · **T5.5** rank + brief + scorecard rendering | disjoint writes; each codes against T5.0 only; the wave starts after Checkpoint A says GO (T5.2 also lists T5.1 so its TED/extracted tests run on v2) |
| 2 | **T5.6** `run_radar`, the `radar` / `record-radar` CLI, radar recordings format | needs all wave-1 modules |
| - | **Recording R (orchestrator):** `record-radar --yes` for the three clients; by-eye review of fetched pages and briefs (contacts, natural persons); commit `tests/fixtures/radar/` | only the orchestrator has `.env` and network |
| 3 | **T5.7** radar replay evidence suite: real recordings, nine questions, zero unsupported facts, ordering, generality (test engineer) | gate green -> briefs go to the founder |
| - | **Founder scoring** (go/no-go, below) | |

Eight tickets (one over the 5-7 target: the evidence suite has to come after the live recording,
as T4.6 did). Wave-1 write scopes are disjoint (checked):
`radar/entities.py` | `radar/discover.py` | `radar/gate.py`, `radar/court.py`, two prompts |
`radar/brief.py`, plus each ticket's own test files.

## Frozen contracts (T5.0)

*(impl)* = implemented in T5.0. Everything else is a signature + docstring + `NotImplementedError`
body, implemented by the named ticket. Contract tests check shape only.

```
northvaine/radar/models.py  (new, T5.0 impl; radar-only shapes, so core/models.py is untouched)
  class RadarStream(StrEnum): TENDER="tender", AWARD="award", ANNOUNCEMENT="announcement"
  def stream_is_enumerable(stream) -> bool            # tender, award: True; announcement: False
  class RejectedAs(StrEnum): UNIDENTIFIED, INSUFFICIENT_EVIDENCE, COMPETITOR, RESELLER,
                             PUBLISHER, NOT_A_BUYER, NOT_AN_ORGANISATION   (snake_case values)
  class ClientSpec: id: str, offer: str, markets: list[Iso2],
                    sensors: dict[str, list[SensorQuery]]      # same JSON as tests/fixtures/clients
  def load_client_spec(client_id: str, clients_dir: Path | None = None) -> ClientSpec   (impl)
  class CandidateClaim: ref: str ("C1"...), fingerprint, document_id: UUID, statement,
                        source_quote, source_name, url, available_at: datetime | None,
                        evidence_kind: EvidenceKind, verified_by: str, upgraded_from: str | None
  class CandidateEvent: event_type, description, occurred_on: date | None,
                        available_at: datetime | None, claim_refs: list[str],
                        slots: dict[str, Any], fingerprint: str
  class Candidate: key: str, name: str, country: Iso2 | None, aliases: list[str],
                   roles: list[str], stream: RadarStream, streams: list[RadarStream],
                   events: list[CandidateEvent], claims: list[CandidateClaim],
                   window_start: date | None, window_end: date | None,
                   window_estimated: bool, window_note: str
  class GateDecision: passed: bool, rejected_as: RejectedAs | None, by: Literal["code","llm"],
                      reason: str, direct_buyer: bool | None, buyer_reason: str | None,
                      demand_reason: str | None, suggested_action: str | None,
                      cited_refs: list[str]
                      # validator: passed == (rejected_as is None)
  class AgainstPoint: claim_ref: str, why: str
  class SkepticFinding: stance: Literal["against","unknown"], against: list[AgainstPoint],
                        open_questions: list[str]
                      # validator: stance == "against" iff against non-empty
  class RankedEntry: rank: int, candidate: Candidate, gate: GateDecision,
                     skeptic: SkepticFinding, strength: Literal["strong","medium","weak"],
                     rank_reasons: list[str]
  class RejectedEntry: candidate: Candidate, gate: GateDecision
  class UpgradedPage: lead_url, final_url: str | None, status: int | None,
                      fetched_at: datetime | None, title: str | None, text: str | None,
                      refused: str | None          # robots | denied | http_<n> | content_type | error
  class DiscoverResult: documents: list[EvidenceDocument], leads: int,
                        upgraded: list[UpgradedPage], notes: list[str]
  class RadarRun: client_id, offer, as_of: datetime, queries: dict[str, list[SensorQuery]],
                  documents_by_kind: dict[str, int], leads: int, upgraded: list[UpgradedPage],
                  entries: list[RankedEntry], rejected: list[RejectedEntry],
                  llm_calls: int, cost_usd: Decimal, notes: list[str]

northvaine/radar/discover.py  (T5.3)
  def shift_queries(queries, as_of: date) -> dict[str, list[SensorQuery]]
  def strip_contacts(text: str) -> str
  class PageFetcher(Protocol): async def fetch(self, url: str) -> UpgradedPage
  class LivePageFetcher(PageFetcher)          # RobotsCache + safe_fetch + html_to_text + strip_contacts
  class RecordedPageFetcher(PageFetcher)      # from list[UpgradedPage]; unknown url -> ReplayMismatch
  def upgraded_document(page: UpgradedPage, lead: EvidenceDocument) -> EvidenceDocument | None
  async def discover(spec: ClientSpec, queries, *, http: httpx.AsyncClient | None,
                     fetcher: PageFetcher, settings=None) -> DiscoverResult

northvaine/radar/entities.py  (T5.2)
  def company_key(name: str, country: str | None, settings=None) -> str
  def stream_for(source_name: str, event_type: str, settings=None) -> RadarStream
  def window_for(stream, events: list[CandidateEvent], settings=None)
        -> tuple[date | None, date | None, bool, str]
  def build_candidates(results: list[tuple[EvidenceDocument, LedgerResult]], *, settings=None)
        -> tuple[list[Candidate], list[RejectedEntry]]          # rejected: UNIDENTIFIED only

northvaine/radar/gate.py  (T5.4)       GateOutput (strict-schema shape, T5.0 impl)
  def numbers_grounded(text: str, quotes: list[str]) -> bool
  async def gate_candidate(candidate, spec: ClientSpec, *, run, session=None, settings=None)
        -> GateDecision
northvaine/radar/court.py  (T5.4)      SkepticOutput (strict-schema shape, T5.0 impl)
  async def skeptic(candidate, gate: GateDecision, spec, *, run, session=None, settings=None)
        -> SkepticFinding

northvaine/radar/brief.py  (T5.5; code only, never imports brain.llm)
  def rank(passed: list[tuple[Candidate, GateDecision, SkepticFinding]], *, as_of: datetime,
           settings=None) -> list[RankedEntry]
  def render_brief(run: RadarRun) -> str
  def render_scorecard(run: RadarRun) -> str
  def write_reports(run: RadarRun, out_dir: Path) -> list[Path]   # brief.md, scorecard.md, run.json

northvaine/radar/run.py  (T5.6)
  def seeded_concepts() -> list[EventConceptRow]                  # level-0 seed of migration 0002
  async def run_radar(spec, *, as_of, http, fetcher, concepts, run, settings=None) -> RadarRun
scripts/radar.py (T5.6): --client, --replay (default) | --record --yes, --as-of, --out
```

GateOutput / SkepticOutput (strict-schema rules from PF1: no docstrings, no Field descriptions,
no pattern/minLength; enums allowed; nullable = `anyOf [X, null]`, every field **required**):

```
GateOutput:    verdict: Literal["buyer","competitor","reseller","publisher","not_a_buyer",
                                "not_an_organisation"], direct_buyer: bool | None,
               reason: str, buyer_reason: str | None, demand_reason: str | None,
               suggested_action: str | None, cited_refs: list[str] (maxItems 8)
SkepticOutput: against: list[{claim_ref: str, why: str}] (maxItems 4),
               open_questions: list[str] (maxItems 3)
```

Settings (T5.0 impl, `core/settings.py`, all data, no literals in radar code):
`radar_clients_dir="tests/fixtures/clients"`, `radar_reports_dir="reports/radar"`,
`radar_fixtures_dir="tests/fixtures/radar"`, `radar_max_lead_upgrades=15`,
`radar_max_gate_candidates=40`, `radar_brief_entries=10`, `radar_tender_window_days=30` (D27),
`radar_recent_days=90`, `radar_stream_by_event={"tender_published":"tender","contract_awarded":"award"}`,
`radar_enumerable_sources=("ted",)`, `radar_legal_forms` (company legal-form tokens: ltd, limited,
plc, llc, inc, gmbh, ag, kg, sa, sas, sarl, srl, spa, bv, nv, ab, as, oy, sp z o o, ...),
`gate_max_tokens=700`, `skeptic_max_tokens=600`, `radar_run_budget_usd=1.00`.

Invariant rules added to `scripts/check_invariants.py` (T5.0): `radar/brief.py` and
`radar/entities.py` never import `northvaine.brain.llm` (ranking, identity and rendering are code).

## Checkpoint A: identify the company (correction 1), go/no-go before wave 1

On the T5.1 branch, after the orchestrator re-records the ledger fixtures with prompt v2,
`tests/radar/test_subject_fill.py` must pass on the real recordings:
- at least 2/3 of events built from **extracted** (non-TED) documents carry a grounded subject
  (subject name inside a verified quote, D50), and
- every full-text recorded document whose verified quotes contain an organisation name the model
  named yields at least one grounded subject.

The orchestrator also reads the recordings by eye: the M4 example (a company investing in its own
hub typed `contract_awarded`) must no longer be typed as an award. Result goes in the M5 report.
**No-go** -> one prompt iteration (v3, same contract); if still below, stop and tell the founder
(the fix may need the mid tier for extraction, which changes cost).

## Go/no-go: what the founder rates (correction 3)

`scorecard.md` is written next to each brief, one row per entry, four yes/no columns, plus a
"which step failed" chip when a row is "no":

| Column | Stone client (founder knows the business) | Cold-chain and packaging clients |
|---|---|---|
| **Correct** | every fact matches its source | same |
| **Relevant** | a plausible buyer of this offer | same |
| **New or worth acting on** | *previously unknown* to the founder | *would a salesperson in that industry act on this?* |
| **Actionable** | a person knows who to approach and why now | same |

Failure chips: wrong company · not a buyer · competitor/publisher let through · stale/closed
window · wrong fact · not actionable. The founder also skims the **rejected** table and marks any
rejection that was actually a good buyer ("wrong rejection").

**GO (proceed to M6 learners) when all hold:**
1. Stone and cold-chain: **at least 2 entries each** rated yes in all four columns.
2. Packaging: either at least 2 such entries, **or** the brief says honestly that sources are thin
   (correction 4, D22) with no padded entry. A padded or invented entry is a no-go.
3. **Zero unsupported facts**: T5.7 proves every quoted fact is a verified claim present in its
   document, and the founder finds no fact they cannot trace from the brief.
4. Wrong rejections at most 1 in 3 of the rejected rows the founder checks.
5. `tasks.py gate` green; the three briefs regenerate offline from recordings with no `.env`.

**NO-GO** points at the step to fix from the chips: mostly "wrong company" -> identification
(T5.1/T5.2); "competitor/publisher let through" or "wrong rejection" -> gate prompt; "not
actionable"/"stale" -> sources and queries (data, not code); "wrong fact" -> stop and treat as a
ledger bug.

## Proposed decisions (D57+)

- **D57 — Extractor v2 names the company.** `subject_name`, `subject_role` and `date_text` (claims
  and events) become required-nullable fields of the strict schema, and the prompt requires the
  quote to contain the organisation's name (otherwise grounding drops it, D50). An event type is
  used only when its seeded description fits; otherwise no event. Re-record, never hand-edit (D53).
- **D58 — Entity resolution in M5 is one explicit code rule.** Match key = NFKC, casefold,
  punctuation stripped, legal-form tokens removed (a settings list, not industry words), plus the
  ISO2 country. A country-less mention joins the single countried key with the same name, else it
  stays separate. No LLM pair resolution, no domains, no merging across different countries.
- **D59 — A lead is upgraded once by fetching its publisher page.** Robots.txt, the deny list
  (rule #9) and `safe_fetch` apply; emails and phone numbers are stripped from the text before it
  becomes a `website` document (`available_at = fetched_at`, `meta.upgraded_from` = lead URL);
  at most `radar_max_lead_upgrades` per run; every refusal is kept with its reason.
- **D60 — Three streams on every brief entry.** `tender` (enumerable; window = publication to the
  earliest stated deadline, else +30 days marked *estimated*, D27), `award` (enumerable; account
  intelligence, D23; no window), `announcement` (not enumerable; specification window; date only
  as stated). Recall is reported only for enumerable streams (D30). A company seen in several
  streams is one entry with a primary stream (tender > announcement > award).
- **D61 — M5 persists the radar run as a JSON run record; database cases wait for their first
  reader.** `run.json` keeps every candidate, passed and rejected, with `rejected_as`, reason and
  `by`, never deleted. Writing `companies`/`cases`/`case_evidence` (and a `rejected_as` column)
  lands with the case file in M6, mapped from this record. Keeps M5 offline and DB-free.
- **D62 — Gate and skeptic.** Code rejects candidates with no named company (`unidentified`)
  before any model call. The gate is one mid-tier call per candidate over its verified claims and
  the client's offer, choosing buyer / competitor / reseller / publisher / not_a_buyer /
  not_an_organisation; a natural person is rejected and their name withheld from reports. The
  skeptic runs only on passed candidates (mid tier) and must cite claim refs, else `unknown` with
  open questions. No judge / deep model in M5.
- **D63 — Model-written brief sentences cite claims and never introduce a number.** Demand
  reason, buyer reason, suggested action, skeptic reasons and open questions must cite valid claim
  refs, and every number in them must appear in a cited verified quote; otherwise the sentence is
  shown as "not stated". Facts are rendered only as verified statements with verbatim quotes.
- **D64 — Ranking is lexicographic and explained.** Order by (evidence strength, window urgency or
  recency, direct buyer); each component is printed as a reason line. No numeric score.
- **D65 — Radar runs are fresh and replayable.** Query date ranges are shifted to end at the run
  date (same length); a radar recording (HTTP exchanges, fetched pages, LLM exchanges, meta with
  `as_of` and the shifted queries) lives in `tests/fixtures/radar/<client>/`. Replay is the
  default; only the orchestrator records. M3/M4 fixtures stay as they are (except T5.1's re-record).
- **D66 — Generated reports are not committed** (pending founder Q1): `reports/radar/` is in
  `.gitignore`.

## Parked (for `docs/LATER.md`)

- DB persistence of radar runs: `companies` upsert by match key, `cases` (stage gated/dismissed,
  `rejected_as` column), `case_evidence` stances, `case_open_questions` (M6 case file; D61).
- LLM-assisted entity resolution for uncertain pairs; domain-based company keys; aliases across
  languages; the project graph (M6).
- Bidder inference for tenders (likely bidders = repeat winners of similar works, D19/D23 join).
- Judge (deep model), calibrated confidence, thesis weights in the ranking (SPEC §5 steps 8-9).
- SPEC §5 filter/match stages (recency drop, blocked aggregators beyond the deny list, embeddings
  match to theses); skeptic with its own search budget (ARCHITECTURE §10).
- Clients as workspaces in the database (the radar reads specs from the fixtures dir in M5).
- Tavily `/extract` instead of page fetch; Wayback snapshots for replay-safe web pages.
- Per-provider concurrency caps; Tavily credit ledger; the nightly `discover` job wiring.

## Risks

1. **Subject fill stays low** (the top risk): Checkpoint A stops the milestone before any other
   spend; fallback is a v3 prompt, then a cost question to the founder.
2. **Fetched publisher pages are thin or blocked** (JS sites, robots, paywalls): packaging may stay
   below 10 entries. The brief states it (correction 4). Upgrade refusals are listed in the run.
3. **Fetched pages contain personal data** (bylines, staff names): contacts are stripped by code,
   persons rejected by the gate with names withheld, and the orchestrator reads every recording by
   eye before committing (as D42). Reports are gitignored.
4. **Tender windows already closed**: shifted queries cover the last N days, but a 120-day tender
   range still includes closed windows; ranking puts open windows first and labels closed ones.
5. **Gate errors** (authority of a works tender is not the direct buyer, D19): `direct_buyer`
   false is allowed to pass; the suggested action then names the stage (D31), not a fake buyer.
6. **Recorded replay is brittle**: any prompt or settings change invalidates recordings; one
   recorder command re-records a client in under a minute.
7. **Tavily recorder refusals** (an email in raw content) drop whole queries, as in M3. Accepted;
   the run notes say how many.

## Questions for the founder

**Answered 5 Oct 2026:** Q1 = briefs shared privately, never committed. Q2 = an honest thin packaging brief is a pass.

1. **Reports in the public repo?** The briefs name real companies from public records and may name
   a sole trader who won a tender. Recommended: keep `reports/radar/` out of git and share the
   briefs privately; commit nothing generated. Yes / no?
2. **Packaging threshold.** ChatGPT's brief asks for at least two good entries per business;
   correction 4 says packaging may stay thin. Proposed go rule: packaging passes with an honest
   "sources are thin" brief and no padding, even with fewer than two. Accept?

## Live recording cost (orchestrator only)

| Step | Calls | Estimate |
|---|---|---|
| Checkpoint A: ledger re-record with prompt v2 | ~4 extract + 4 support (fast) + ~30 embeds | about $0.01 |
| Recording R: discover | TED free; Tavily ~8 searches (+2 optional extra packaging queries) | ~8-10 Tavily credits |
| Recording R: lead upgrades | up to 15 page fetches per client | free |
| Recording R: extract + support (fast) | ~15 full-text docs per client: ~75k in, ~30k out | ~$0.01 per client |
| Recording R: gate (mid) | up to 40 candidates per client, ~2k in / 300 out each | ~$0.035 per client |
| Recording R: skeptic (mid) | ~25 passed per client, ~2k in / 300 out each | ~$0.025 per client |
| **Total, three clients, one pass** | | **about $0.25 LLM + ~10 Tavily credits**; a re-record doubles it. Cap `radar_run_budget_usd=1.00` per client run |

Prices from `northvaine/brain/pricing.json` (fast $0.06/$0.24, mid $0.30/$0.90 per million
tokens). No new credentials or paid services.
