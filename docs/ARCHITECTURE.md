# Northvaine — Learning Architecture (v2)

Status: candidate architecture, 2 Oct 2026. Not built. Supersedes v1 of this file.
Where it conflicts with SPEC.md, it is a proposed change to record in DECISIONS.md once agreed.

**What changed from v1**
1. **Intelligence is defined as choosing where to spend attention, not as producing a score.**
   The Bayesian ledger is demoted to one swappable implementation of one learner (§7.6).
2. **Four separate learners:** world state, organizational context, buying patterns, research
   policy. Each has its own state, signals, update rule, evaluation, and interface.
3. **An attention allocator** turns everything the learners know into *what to search, what to
   watch, what to investigate, what to ask, and what to show* (§9). Learning changes behaviour
   through it, not only through rankings.
4. **v1's hard-coded limits** (clause caps, lag bins, prior strengths, question caps, thresholds,
   windows) are now adaptive mechanisms. Only a short list of **invariants** stays fixed, for
   safety, cost and honesty (§3).
5. **Public-world proxies.** Buying-pattern learning is split into a part learned from public
   data, with no labels needed (world dynamics), and a sparse part learned from the
   organization's own outcomes (§7.3). This is the main answer to sparse outcomes.

---

## 0. Summary

```
                   ┌──────────────── INVARIANTS (fixed: evidence, safety, cost caps, honesty) ───────────────┐
                   │                                                                                       │
  WORLD-STATE      │   ORG-CONTEXT        BUYING-PATTERN          RESEARCH-POLICY                           │
  LEARNER          │   LEARNER            LEARNER                 LEARNER                                   │
  what is true     │   who we are,        what precedes a         how to find out,                          │
  and how the      │   what we want,      valuable opportunity    cheaply and reliably                      │
  world changes    │   what we can do     for THIS org                                                      │
       │           │        │                  │                       │                                   │
       └───────────┴────────┴────────┬─────────┴───────────────────────┘                                   │
                                     ▼                                                                     │
                     ATTENTION ALLOCATOR  —  value of each possible action, per unit cost                  │
                     search programs · watches · investigations · questions · brief slots                  │
                                     ▼                                                                     │
                     ACT  →  EVIDENCE (verified)  →  DECISIONS (logged with propensities)                  │
                                     ▼                                                                     │
                     OUTCOMES + FEEDBACK + MISSED OPPORTUNITIES  →  routed back to the right learner ───────┘
```

**The thesis in one sentence.** The system becomes more intelligent for an organization as it
spends its limited attention better (compute, API calls, and above all the owner's time). It
does that because four learners keep revising what is true in the world, what this organization
is, what precedes its buying moments, and how to find those moments. Their combined beliefs
decide what the system looks for next.

---

## 0.1 North star: reach, not rank

Northvaine is a **radar**: it finds buying activity the business would otherwise have missed,
and it widens where the business can sell. Scoring exists only to protect the owner's time.
Discovery is the product.

What this changes in the design:
- **The headline metric is net-new reach:** briefed opportunities the owner rates good *and*
  did not already know about (§18.1). Each case gets a one-tap "**did you already know about
  this?**" that's the label for reach. A good lead the owner already knew is worth little; a
  good lead they would have missed is the whole value.
- **Discovery dominates the budget.** Event-first search finds companies that appear in no CRM,
  directory or list. The allocator values *novel* companies, regions and segments above
  re-finding known ones (novelty term in §9.2).
- **Reach grows deliberately.** The frontier search (§6.4) is a main product feature, shown to
  the owner as "new markets I'm testing for you", not a minor exploration budget.
- **Breadth of sensing is a learned asset.** R discovers regional sources (procurement portals,
  planning registers, trade press, local news) and searches **in the buyer's language**. This
  matters most for exporters, whose buyers publish in languages the owner doesn't read.
- **Recall is measured**, not assumed. Missed-opportunity post-mortems (§8.4) drive
  where the radar looks next.

---

## 1. What "intelligence" means here

A score is an output. Ranking a fixed candidate list better is the smallest kind of
improvement. The system is intelligent to the degree that it:
1. **Looks in the right places.** It finds opportunities a static system would never see,
   because its searches come from its current beliefs.
2. **Checks the right things.** It spends investigation on the questions whose answers would
   change a decision.
3. **Asks the right questions** of the organization, only when the answer is worth the owner's
   time.
4. **Revises its own representations.** It changes not only weights but concepts, patterns,
   search programs, and its picture of the organization, when evidence requires.
5. **Knows what it doesn't know.** It reports uncertainty honestly and spends some effort
   reducing it where that pays.

So the measure of intelligence (§18) is **outcomes per unit of attention, over time**:
- useful opportunities per owner-minute and per dollar,
- lead time,
- recall of opportunities that existed (including ones we missed),
- how fast representation changes improve those numbers on held-out time.

---

## 2. The learning problem, restated

### 2.1 Four learners, one allocator

| Learner | Learns | Main signals | Needs org labels? | Shared across orgs? |
|---|---|---|---|---|
| **World state** (W) | entities, events, the concept vocabulary, source reliability, **world dynamics** (what tends to follow what, with lags) | public documents, their timestamps, repeated observation | **no** (self-supervised on public data) | yes (world layer) |
| **Org context** (O) | what the org sells, to whom, where, constraints, capacity, sales motion, preferences, how these change | website, owner answers, owner choices on examples, outcome contradictions, inbound demand | partly | no (private) |
| **Buying patterns** (B) | which world states/sequences precede *this org's* valuable opportunities, with timing, fit and disqualifiers | org history, ratings + reasons, outcomes, inbound requests, plus W's proxy predictions | **yes** (sparse) | priors only, pooled statistics |
| **Research policy** (R) | which search programs and investigation actions produce decisive, verified evidence cheaply, in which context | logs of every search and action, with cost and what it resolved | no (uses outcomes of actions, not of deals) | yes (pooled priors) |
| **Attention allocator** (A) | not a learner of the world. It **combines** the four into decisions about effort; its own parameters (owner attention cost, budget split) are learned | owner engagement, realized value of past allocations | — | — |

**Why separate them?**
- They learn from **different data** at **different speeds**. W learns from millions of public
  events, B from tens of outcomes.
- Their errors need **different fixes**. A wrong fact is W's problem; "too small" is O's or
  B's fit; "never found it" is R's.
- They have **different sharing rules**. W and R improve for every customer; O never leaves the
  workspace.
- Mixing them is how v1-style systems fool themselves. For example, a source being unreliable
  (W) gets learned as "this pattern doesn't work" (B).

### 2.2 The atomic learning units, per learner

| Learner | Atomic unit | Higher structure |
|---|---|---|
| W | a verified **event** on a company timeline, and an **expectation** ("given A at t, B is likely by t+Δ") | concept hierarchy; world-dynamics graph of concept → concept lag relations; source reliability |
| O | a **belief slot** with a distribution and provenance | the org model: offer, segments, constraints, motion; its change history |
| B | a **pattern**: a predicate over a timeline, with a belief about its effect on this org's opportunity rate as a function of lag and context | the buying model: patterns, fit, disqualifiers, proxy links, calibration |
| R | an **action outcome**: (action, context, open question) → resolved? at what cost? | search programs and investigation playbooks with yield models |

### 2.3 Definitions

| Term | Definition |
|---|---|
| **Observation** | A document snapshot from a sensor, with `available_at` (when it could have been known). Untrusted. |
| **Evidence** | A verified claim: an exact quote found by code in a saved document, then checked by an LLM to support the statement. The only thing reasoning may cite. |
| **Event** | A dated change, built from ≥ 1 claims; an open-vocabulary concept; slots; a cluster id (one story = one event). |
| **Expectation** | A prediction made by W or B: "for company c, an event of concept K is likely between t₁ and t₂". It is scheduled for checking. Its fulfilment or absence is evidence. |
| **Hypothesis** | Any proposed, not-yet-validated statement in any learner: a pattern (B), a concept split (W), an org belief change (O), a new search program (R). Each has a status and an origin. |
| **Belief** | A distribution over a quantity, with a prior, evidence count, the source of the prior, and a version. |
| **Search program** | A versioned, executable recipe (query templates, sources, filters, schedule) compiled from a hypothesis. It carries yield statistics. |
| **Experiment** | Effort spent mainly to reduce uncertainty in a learner, not to find an opportunity today. It is logged as such. |
| **Opportunity (case)** | A company at a time with matched patterns, for/against evidence, open questions, P(good) with uncertainty, a window, a role, and an angle. |
| **Outcome** | The furthest rung reached (rated good → reply → meeting → samples → quote → won), timestamped, possibly censored. |
| **Feedback** | Owner judgement: rating + structured reasons + edits. Routed to the learner(s) it is evidence about. |
| **Missed opportunity** | A real opportunity (inbound, won outside the system, public award in category) the system did not brief in time. It is the signal for recall. |
| **Mistake** | A gap between predicted and observed, attributed to a learner and a component. |
| **Confidence / uncertainty** | Calibrated probability vs. the width of the belief. Kept separate. |
| **Business / temporal context** | The org model at time t / the time of reasoning, lags, availability, cycle position. |

---

## 3. Invariants vs. adaptive mechanisms

### 3.1 Fixed invariants (never learned, and why)

| Invariant | Reason it is not adaptive |
|---|---|
| No source, no claim; quote check in code before any LLM check | Learning must never trade truth for a better score |
| AI never negotiates; no prices, discounts, dates, terms from AI | Trust and liability, not statistics |
| No real sending in the hackathon build | Scope |
| External content is untrusted data | Security |
| Hard cost caps (per day, per case, per call) | The allocator optimizes *within* caps; caps protect the customer from the optimizer |
| No scraping where forbidden | Legal |
| Point-in-time availability in replay and in validation | Without it, every adaptive mechanism can fool itself |
| A promotion gate exists before any learned change goes live | Adaptivity needs an adaptive check *and* a fixed referee |
| Max change per update (trust region) + an exploration floor > 0 | Prevents runaway feedback loops and permanent blind spots |
| Owner-pinned items and owner-stated hard rules are never silently overridden | The owner's authority. The system may *challenge* them with evidence (§6.5) |

### 3.2 Every v1 constant, replaced

| v1 constant | v2 adaptive mechanism | Learner |
|---|---|---|
| ≤ 3 clauses, ≤ 2 absences per pattern | **Complexity earned by evidence.** A refinement (added clause / absence / filter) is accepted only if out-of-time model evidence beats its parent by more than the complexity penalty. Allowed complexity therefore grows with effective sample size. Search over refinements is a beam whose width is set by the allocator's explore budget. | B |
| 4 fixed log-spaced lag bins | **Lag density per pattern.** Start from a parametric prior (log-normal, from W's world-dynamics lags or the LLM). Add mixture components / change points only when model evidence supports them. Windows are read off the posterior. | B (prior from W) |
| Ordering gap d ∈ {7, 30, 90, 365} | Gaps come from the same lag densities (W's concept → concept relations). | W → B |
| Prior σ fixed per source (LLM ≈ 1.0, discovered 0.5) | **Meta-calibration of belief sources.** Each prior source (LLM-strong/medium/weak, owner statement, history, cross-org pool) has a learned bias and spread. These come from comparing its past priors with later posteriors, pooled across patterns and orgs. New priors get σ from that. | B, O (meta) |
| n₀ ≈ 5–10 pseudo-cases | Follows from the meta-calibrated σ. | meta |
| LLM words → fixed numbers (weak/medium/strong = 0.4/0.8/1.4) | That mapping is itself calibrated by the same meta-calibration. | meta |
| ≤ 5 onboarding questions; ≤ 1 per day | **Owner attention model.** P(answer), answer quality, and annoyance cost (skip rate, latency, drop-off) per question type, learned per owner. Ask while VOI > learned cost. | A, O |
| Brief size K = 5, watchlist 20 | **Owner capacity model.** Marginal expected value of the k-th case vs. the owner's per-case review cost, learned from what they actually act on and position effects. | A |
| ≤ 5 patterns in exploration | **Value of information per pattern** (knowledge-gradient style). Exploration effort follows expected improvement in future decisions, with the invariant floor. | A, B |
| Validate at P(w>0) ≥ 0.9; retire < 0.1; n_min | **Decision-theoretic promotion.** A pattern drives briefs (exploit) when expected value of using it, net of the owner's learned cost of false positives, exceeds alternatives. Retire when it no longer earns allocation *and* its information value is low. | B, A |
| Miner support m, top-N candidates | False-discovery-rate control on out-of-time tests; candidate volume set by the allocator's explore budget. | B |
| Recency filter (> 90 days dropped) | Removed. Lag densities make old events weak naturally. A cheap pre-filter drops events beyond the far tail of every active pattern's posterior lag. | B |
| Calibration switch at 50 labels | Hierarchical calibration that shrinks continuously toward identity × shrink factor; no switch point. | B |
| Investigation stop at fixed τ | VOI vs. learned costs; per-case hard cap remains an invariant. | R, A |
| 3–5 controls per positive | **Sequential control sampling:** draw controls while the pattern's odds-ratio interval is wide and controls are cheap. | B |
| Concept split by distance threshold | **Split/merge by usefulness:** a concept split is kept if it improves predictive likelihood in W's dynamics model or in any org's B model on held-out time. | W |
| Fixed watchlist re-check schedule | **Change-rate scheduling:** re-check company/source when P(change since last check) × value of a change is high. Change rates are learned per source and company type. | W, R |
| Fixed model tier per task | **Tier routing by disagreement sampling:** occasionally run the higher tier on the same input. Where tiers agree, route down; where they disagree, route up or keep the higher tier. | R (meta) |
| Retention 180 days | Stays an invariant (privacy), except documents referenced by active claims. | — |

**Defaults still exist.** Every adaptive knob starts at the v1 value. It sits in `policy_params`
with its update rule and its own evaluation. It changes only through the promotion gate (§18.4).

---

## 4. Shared substrate (used by all learners, owned by none)

- **Evidence ledger:** `documents` (with `available_at`), `claims` (verified only usable).
  Unchanged from SPEC.
- **Company timelines:** point-in-time builder. Only data with `available_at ≤ t`; asserted in
  code.
- **Decision log:** every scored candidate, every search run, every investigation action and
  every question, with context, cost, and **propensity** (how likely that choice was). This is
  what makes unbiased learning and offline evaluation possible for *search and investigation*,
  not just for briefs.
- **Belief store:** all distributions, versioned per learner.
- **Hypothesis registry:** every proposal from every learner, with status, origin, tests run,
  and result.
- **Strategy versions:** a snapshot of all learner states + policy params + prompt versions;
  the unit of rollback.

---

## 5. World-state learner (W)

**Question it answers:** what is true, what is changing, and what usually happens next, for
any company, independent of any customer.

### 5.1 State

- Entities (domain-keyed).
- Events with open-vocabulary concepts and slots.
- The concept hierarchy.
- **Source reliability** (P(claim correct), P(event meaningful), publication lag) per source and
  source type.
- **Change rates** per source and company type.
- **World dynamics:** for concept pairs (K₁ → K₂), the conditional rate of K₂ after K₁ relative
  to base rate, with a lag density, stratified by company attributes.

### 5.2 How it learns (no org labels)

- **Concepts:**
  - The LLM normalizes events to canonical generic descriptions.
  - Embeddings cluster them into a hierarchy, seeded with SPEC's 12 generic types at the top.
  - Splits and merges are kept by usefulness (§3.2).
  - The LLM names clusters.
- **Dynamics:**
  - Self-supervised. The world produces its own labels: whether K₂ followed K₁ for the same
    company within Δ.
  - Estimated as hierarchical rate ratios with shrinkage toward parent concepts.
  - Validated **out of time** (fit up to T, test after T).
- **Source reliability:** updated from contradictions between sources, owner "wrong fact"
  reports (as evidence, not only W's own checks), retractions, and whether expectations built
  on a source's events come true.
- **Expectations:** when K₁ is observed and dynamics predict K₂ with meaningful lift, W emits an
  expectation with a time window. The allocator decides whether to watch for it.

### 5.3 How W changes search and investigation

- **New concept** → R generates search programs for it, and B can propose patterns over it.
- **Expectation** → a targeted, timed **watch** ("check company c's news/tenders for K₂ between
  day 20 and day 60"). If it is fulfilled, the case strengthens; if it is absent, that absence is
  evidence too.
- **Source reliability** → sources lose or gain search budget and evidence weight.
- **Change rates** → re-check scheduling.

### 5.4 Evaluation

- Extraction precision (audited).
- Dedup accuracy (one story = one event).
- Concept coherence (LLM + human spot checks).
- **Next-event prediction on held-out time** (log-likelihood, Brier).
- Source-reliability calibration.
- Expectation hit rate vs. a base-rate baseline.

---

## 6. Org-context learner (O)

**Question it answers:** what this organization is, wants, and can do, as beliefs that are
allowed to be wrong and to change.

### 6.1 State

Belief slots, each a distribution with provenance and history:
- offer categories (HS/CPV),
- segments and buyer types,
- buyer roles,
- regions served and excluded,
- order size range,
- capacity,
- lead-time ranges they will publish,
- sales motion (tender / distributor / direct / project),
- competitors,
- anti-customers,
- differentiators,
- certifications,
- **preferences revealed by choices** (which cases they pursue, edit, dismiss).

### 6.2 How it learns

- **Website inference** (LLM) → initial distributions with evidence.
- **Questions chosen by value of information** (§6.3).
- **Choices on examples** ("which of these 8?"): active learning that picks *boundary* examples,
  where O's uncertainty changes B's ranking most.
- **Revealed preference:** consistent dismissals/pursuits update slots (e.g. order size lower
  bound) as evidence, with the owner told what changed.
- **Contradiction detection:** outcomes or inbound demand that contradict a stated belief
  (§6.5).
- **Drift:**
  - new products on the website (W watches the org's own site),
  - new kinds of inbound demand,
  - shifts in what the owner pursues.

  Each raises the uncertainty of the affected slots, which can trigger new questions and new
  hypotheses.

### 6.3 Which question to ask (no fixed list, no fixed count)

```
VOI(q) = E_answer[ improvement in the allocator's planned decisions ] − learned_cost(q, owner)
```

Computed cheaply:
1. For the top answers to q, re-run the allocator's *plan* in simulation, using code scoring and
   no LLM.
2. Measure how much the plan changes:
   - search programs funded,
   - candidates briefed,
   - investigations queued.

   This captures that a question can matter because it changes **what we search**, not only
   what we show.

Ask the highest-VOI question if it beats its learned cost. Onboarding ends when no question
does. The system then starts work, saying what is still uncertain.

### 6.4 How O changes search and investigation

The search space is defined by O's distributions, not by a fixed profile:
- Regions, segments and categories get **search budget in proportion to their probability ×
  value**.
- A small **frontier** budget goes to plausible-but-unconfirmed segments (adjacent
  industries, neighbouring regions). Results there are experiments that update O.
- A new offer category detected (drift) → B generates hypotheses and R generates programs for
  it.
- A constraint learned (e.g. min order size) → becomes a disqualifier clause that investigation
  checks early, *because* its VOI is high.

### 6.5 Owner statements are strong beliefs, not untouchable facts

If evidence accumulates against an owner-stated rule, O raises a **challenge question with the
evidence**. Example: "you excluded homeowners, but 9 of the last 20 inbound requests came from
homeowner-led projects and 3 became quotes." The owner decides. Nothing changes silently
(invariant).

### 6.6 Evaluation

- Prediction of owner choices on new examples (log-loss).
- Realized VOI: did answers change plans, and did changed plans improve outcomes in replay or
  live?
- Owner correction rate of displayed beliefs.
- Time to detect drift.

---

## 7. Buying-pattern learner (B)

**Question it answers:** for this organization, which world states and sequences precede a
valuable opportunity, how long before, for which kinds of companies, and what rules them out.

### 7.1 Representation (open, complexity earned)

A pattern is a predicate over a point-in-time timeline:
- clauses over concepts at any hierarchy level, with slot constraints,
- lag relations (to t and between clauses),
- order,
- absences,
- fit filters on company attributes,
- a reference to proxy outcomes (§7.3).

There is **no fixed clause limit**. Complexity grows only as evidence pays for it (§3.2).
Patterns are JSON in a small DSL, evaluated by deterministic code, and explained in plain
language by the LLM.

### 7.2 Hypothesis sources (all only *propose*)

1. **LLM priors** from O's beliefs: general reasoning about how this kind of buyer buys.
2. **History mining:** sequential case-control over the org's reconstructed past customers vs.
   matched controls (adaptive count, §3.2).
3. **World-dynamics lift (W):**
   - Concepts that W shows *precede the proxy outcomes relevant to this org*. Example: for a
     tender-driven seller, what precedes "tender published in our CPV".
   - This is where most day-one-to-month-one discovery comes from, because it needs no org labels.
4. **Error-driven:** the LLM compares true and false positives that share a pattern and proposes
   a separating clause.
5. **Missed-opportunity analysis:** reconstruct the timeline of every missed opportunity and ask
   which pattern *would* have caught it. The answer is a new or refined pattern **plus** a new
   search program (§8.4).
6. **Cross-org pool (later):** patterns validated in ≥ several similar orgs, offered as priors.
7. **Owner:** "we always win after X". Entered as a hypothesis with an owner prior; tested like
   any other.

### 7.3 Proxy chain: the answer to sparse outcomes

```
P(opportunity for O | timeline) =  Σ_proxy  P(proxy event within Δ | timeline)      ← W: public, label-free, data-rich
                                         ×  P(O-opportunity | proxy, fit, O context)  ← B: sparse, org-specific
                                  + direct pattern terms (for buying that has no public proxy)
```

- **Proxy events** are publicly observable signs of a buying process: a tender published, a
  supplier selected, an RFQ posted, a contract award, an import shipment record where lawful,
  "seeking suppliers" posts.
- **O decides which proxies matter** (a tender-driven seller vs. a distributor-driven one).
- **Proxies give dense learning signal from the public world**, so B only has to learn the last
  link from the org's own sparse outcomes.
- **When no public proxy exists,** direct patterns learned from org outcomes carry the load.

### 7.4 Validation and lifecycle

```
proposed → exploring → exploiting → degraded → retired
```

- Every transition is decided on **data after the proposal date** (time holdout), with a
  false-discovery-rate cut across the batch.
- Promotion and retirement are decision-theoretic (§3.2).
- Every validated pattern is labelled "predictive, not shown to be causal".

### 7.5 How B changes search and investigation (not just scores)

- **Compilation.** Each pattern compiles into **search programs** that look for its *first*
  observable clause (the cheapest entry point) and **investigation clauses** for the rest. A
  refined pattern (with a new absence clause) changes what investigation checks, automatically.
- **Allocation.** Patterns with high expected value get exploit search budget. Patterns with
  high *uncertainty that matters* get **test** budget (§9.2).
- **Retirement stops searching.** A retired pattern's programs are de-funded, which saves money
  and stops a source of false positives.
- **Lag densities schedule work.** If the posterior window is 30–90 days after a trigger, the
  system checks matched companies inside that window, not on discovery day.

### 7.6 The scoring mechanism (implementation, swappable)

Current implementation: a **Bayesian log-odds ledger**. Its terms are:
- the base rate,
- fit terms,
- pattern terms evaluated at their lag density,
- proxy-chain terms,
- disqualifiers,
- an evidence-quality term.

It uses informative priors from meta-calibrated sources and a Laplace-approximated posterior
refit nightly, with hierarchical calibration. It is chosen because it does credit assignment
across overlapping patterns at small n, accepts priors, gives uncertainty, and is explainable.

It sits behind an interface, so it can be replaced (e.g. by a cross-org hierarchical model at
scale) without touching the other learners:

```
predict(company, t) → distribution over P(good) and over the opportunity window
explain(company, t) → contributing terms with evidence ids
update(labels with propensities)
information_value(pattern | hypothetical evidence) → used by the allocator
export_beliefs() → for strategy versions and "What I learned"
```

### 7.7 Evaluation

- Useful-opportunity rate at the owner's K.
- Calibration.
- Lead time.
- Out-of-time validation rate of promoted patterns.
- Share of briefs from exploiting vs. exploring patterns.
- Recall of known opportunities.

---

## 8. Research-policy learner (R)

**Question it answers:** given what we want to know, which search or check gets a decisive,
verified answer at the lowest cost?

### 8.1 State

- **Search programs:** query templates, sources, filters, schedules. Each has yield models:
  verified claims per call, relevant events per dollar, distinct new companies, false-positive
  rate downstream.
- **Investigation action models:** P(resolves clause | action type, clause concept, company
  context, source), with cost and latency. Beta/hierarchical, pooled across orgs as priors.
- **Source catalogue:** known sources and *candidate* new sources (found while investigating,
  proposed by the LLM, or surfaced by W).
- **Model-tier routing statistics** (§3.2).

### 8.2 How it learns

- **Every action is a labelled example:** did it resolve the question, at what cost, and was the
  claim later contradicted? Updated from the action log with propensities.
- **Generate → test → select for queries.** The LLM writes variants of low-yield templates;
  the allocator gives each a small experiment budget; yield decides survival. This is evolution
  of search strategy measured by results, not prompt folklore.
- **Source discovery:** when investigations keep resolving clauses via a domain not yet
  catalogued (e.g. a regional procurement portal), R proposes it as a source. The safe-fetch
  and terms-of-use checks are invariants; the source starts with low trust, which W updates.
- **Stopping:** learned from how often extra steps changed decisions, by context.

### 8.3 Per-candidate investigation

**State:** the candidate's posterior + **open questions**. The question set is generated from:
- B's unresolved pattern clauses and disqualifiers,
- W's pending expectations,
- O's uncertain constraints that apply to this company,
- entity-resolution doubts.

The set therefore changes as soon as any learner changes. For example, a new disqualifier
learned from an error appears as a new check on every future relevant candidate.

**Choice:** one-step VOI per cost:
```
VOI(a) = Σ_o P(o | a, question, context) · [best decision value after o] − best decision value now
```
- P(o | ·) comes from R's action models.
- The decision value comes from B.
- Actions include search, fetch, tender lookup, news by date, registry, **schedule a watch**
  (wait for an expectation), **ask the owner**, **escalate**, and **stop**.

**Why one step?** Episodes are short, rewards sparse, and greedy VOI is explainable. Two-step
lookahead is added only if logs show greedy stopping too early where a two-step plan would have
resolved the case. That is an R hypothesis, tested like any other.

### 8.4 Coverage learning from missed opportunities

For every missed opportunity:
1. Replay: would any current program have surfaced it, and when?
2. **Not surfaced** → R proposes a program, B proposes a pattern, W checks whether the needed
   concept exists.
3. **Surfaced but dropped** → the stage that dropped it is a mistake routed by §12.
4. **Surfaced too late** → the lag density or the re-check schedule is wrong.

This is how the system learns to *look* somewhere new, not just to rank better.

### 8.5 Evaluation

- Cost per resolved question.
- Cost per useful opportunity.
- Search yield per program.
- Recall of known opportunities (from inbound, wins, public awards).
- Share of investigations that changed the decision.
- Agreement of routed-down model tiers.

---

## 9. The attention allocator (A): where learning becomes behaviour

### 9.1 The portfolio

Each cycle (nightly, plus event-triggered), A chooses among **candidate uses of effort**, all
logged with propensities:

| Kind | Purpose | Example | Proposed by |
|---|---|---|---|
| **Exploit search** | find opportunities from validated patterns | run pattern P's program in the regions O rates likely | B, R |
| **Test search** | reduce a *pattern's* uncertainty | find historical instances of P in public data and check proxy outcomes; or find instances to brief for owner feedback | B |
| **World experiment** | reduce a *world-dynamics* uncertainty | does K₁ really precede K₂ for this company type? check 50 past instances | W |
| **Frontier search** | reduce *org-context* uncertainty | small search in an adjacent segment | O |
| **Program trial** | evaluate a new query/source | give template v3 10 calls | R |
| **Watch** | check an expectation at the right time | look for K₂ at company c in days 20–60 | W, B |
| **Investigate** | resolve open questions on a candidate | per §8.3 | R |
| **Ask** | resolve something only the owner knows | per §6.3 | O |
| **Brief slot** | spend the owner's review time | top cases by Thompson-sampled value | B |

### 9.2 One value scale

```
value(x) = E[opportunity value from x] × P(novel to owner)   ← B's predictions, O's deal values; novelty learned from "already knew?" taps
         + Σ_learners E[improvement in future decisions from what x teaches]   ← information value
value per cost = value(x) / (compute $ + API $ + owner-minutes × learned owner cost)
```

- **Information value** is estimated by each learner's `information_value()` (§7.6). It is
  approximated as how much the expected posterior change would move future allocations (a
  knowledge-gradient-style estimate).
- **Allocation:** sample from the posteriors (Thompson), rank by value per cost, and fill
  budgets under the hard caps. Keep the exploration floor and the trust-region limit on how
  much the portfolio can shift per cycle.
- **The budget split between exploit and learn is not set by hand.** It follows from
  information value, which is naturally high early and falls as beliefs firm up. That *is* the
  day-one → maturity transition, now visible in where the money goes.

### 9.3 Concrete ways learning changes what the system does

1. **Owner marks five "hiring surge" cases irrelevant.**
   - B: the pattern's weight falls.
   - A: the hiring program loses exploit budget.
   - B: the conjunction "hiring surge + contract award" stays exploring, so a test search is
     funded to check it on public history.
   - Behaviour: fewer hiring searches, one new targeted experiment.
2. **W finds that "planning permission granted" precedes "tender published" by about 4 months
   in this region.**
   - B links it to the tender proxy.
   - R compiles a planning-portal search program.
   - A funds a program trial.
   - Watches are scheduled 3–5 months out for matched companies.
   - Behaviour: a new place to look, and work booked in the future.
3. **An inbound request arrives from a company type we never searched** (missed opportunity).
   - §8.4 replay.
   - O widens the segment distribution.
   - B proposes a pattern from the requester's pre-request timeline.
   - A funds a frontier search in that segment.
4. **Investigation failure:** a briefed case turns out to have chosen a supplier already.
   - B adds the absence clause "no supplier announced".
   - R notes the clause's VOI was underestimated.
   - From then on every matching candidate is checked for it *first*.
5. **A source keeps producing claims that owners mark wrong.**
   - W: the source's trust falls.
   - R: its programs are de-funded, and investigation prefers other sources for the same
     questions.

---

## 10. Reasoning roles (LLM vs. code)

| Role | Implementation | Sees | Isolated from |
|---|---|---|---|
| Scout | code: executes funded programs | program | scores |
| Extractor / normalizer (W) | LLM fast | one fenced document | other docs, goals |
| Verifier | code quote check → LLM fast support check | claim + quote | case goal |
| Entity resolution | code → LLM for uncertain pairs → review | two records | — |
| Gate (buyer vs seller) | LLM mid on verified claims + O's offer | company claims, offer | score, patterns |
| Pattern matcher, scorer, allocator, VOI | **code** | beliefs, timelines | — |
| Skeptic | LLM mid with its own search budget, seeking disconfirming facts | company, claims, matched patterns | score, owner history |
| Judge (interpreter) | LLM deep: answers specific semantic questions (does this event mean what the pattern needs? do skeptic findings trigger a disqualifier? angle, role) | for/against claim ids, patterns, skeptic output | — |
| Hypothesis proposers (all learners) | LLM deep, offline | aggregated evidence | live cases |
| Question phrasing, drafts, lessons, explanations | LLM | the chosen item + verified facts | unverified text |

- **No advocate.** Matched patterns + supporting claims are the case for.
- **Judge confidence is logged and calibrated, never used raw.**
- **Contradictions** are explicit: for / against / open questions. A case cannot be briefed as
  strong while a high-value open question is unresolved. It goes to investigate or watch.

---

## 11. Temporal model

- **Three times per event:** occurred, published, `available_at`. Lag is measured from
  occurred; availability gates replay and validation.
- **Lag densities**, adaptive (§3.2), per pattern and per world-dynamics relation, stratified by
  context only when evidence supports it.
- **Expectations** make time *active*: the system books future checks where the lag density has
  its mass, and absence by the end of the window is evidence.
- **Cycles:** per-customer inter-order hazards from order history (reorder moments).
  Seasonality only when evidence supports it, shrunk to zero otherwise.
- **Time-to-outcome** per rung, used for censoring and follow-up timing.
- **"Too early" / "too late"** update the lag density of the matched pattern directly.

---

## 12. Learning from mistakes: routed to a learner, changing behaviour

| Failure | Learner | Belief change | Behaviour change |
|---|---|---|---|
| Wrong company | W | ER rules; merge undone | ER check added earlier for similar names |
| Wrong fact | W | claim unverified; source trust ↓ | source loses budget; extractor eval case added |
| Misread event | W | concept assignment fixed; split proposed if recurring | programs for the split concept |
| Weak fit | O / B-fit | segment / size / type beliefs | search budget moves away from that segment |
| Wrong buyer role | B (playbook) | role model | investigation looks for a different role |
| Too early | B | lag density shifts later | watch scheduled instead of brief |
| Too late | B / R | lag density shifts earlier; re-check rate ↑ | earlier entry clause searched; more frequent checks |
| Already solved / supplier chosen | B / R | absence clause proposed; its VOI ↑ | checked first on future candidates |
| Competitor / seller | B (gate) | gate eval case | company marked competitor; similar companies gated harder |
| Irrelevant signal | B | pattern weight ↓ | pattern's exploit budget ↓; conjunction tests funded |
| Misleading correlation | B | fails out-of-time → degraded / retired | programs de-funded |
| Insufficient evidence | B / A | owner's evidence bar learned | more investigation before briefing |
| Investigation failure | R | action model for that clause | different action or more budget for that clause |
| Search failure / missed | R / B / W | coverage analysis (§8.4) | new program / pattern / concept |
| Reasoning failure | LLM prompts | eval case added; prompt version flagged | tier routed up for that task until fixed |
| Owner assumption wrong | O | challenge question with evidence | after answer, search space changes |

- **Feedback capture:** rating + reason chips in owner language + optional text. The LLM maps
  free text to codes and the owner confirms with one tap. If a reason is unclear, the update is
  spread with low weight across the candidate components.
- **Lessons** ("What I learned") are generated **from** a recorded belief + behaviour change, and
  cite both. Example: *"Hiring surges alone rarely meant buying for you (31 rated cases). I've
  cut those searches by 70% and am testing hiring + contract award together."*

---

## 13. Avoiding self-deception (including of the adaptive mechanisms)

| Threat | Safeguard |
|---|---|
| Base-rate blindness / survivorship | case-control with matched controls; proxy rates vs. base rates |
| Overfitting / accidental patterns | complexity earned by out-of-time evidence; shrinkage to parents; FDR across batches |
| Same-data validation | time holdout for every hypothesis in every learner |
| Temporal leakage | point-in-time builder; `available_at`; asserted in code; live-fetched pages are not replay-safe |
| LLM hindsight leakage | anonymized entities in replay prompts; replay periods after the model's training cutoff where possible; a no-LLM baseline beside every replay |
| Duplicate / correlated evidence | event clustering; evidence counted per cluster and per independent original source |
| **Search-induced selection bias** (we only see what we searched for) | propensities logged for searches and investigations, not just briefs; exploration floor; inbound and public awards as unselected outcome sources |
| **Adaptive knobs overfitting** | each knob's update is validated on a *separate* time slice from the one its learner used (meta-holdout); trust-region limits per update |
| **Feedback loops** (budget → data → budget) | exploration floor; periodic forced re-tests of retired patterns at low cost; decisions compared to a frozen baseline policy in replay |
| Bad labels | labels weighted, not truth; outcomes recalibrate ratings; inconsistency raises a question |
| Org anomaly treated as universal | only patterns validated in several orgs enter the cross-org pool; W never uses org labels |
| Confirmation bias in reasoning | skeptic and verifier don't see scores or goals; judge cites claim ids |

Honesty vocabulary, tied to statistics:
- **"insufficient evidence"** — interval spans no-effect and exposure is low;
- **"interesting hypothesis, not yet validated"** — status exploring;
- **"correlation observed; causality unknown"** — always on validated patterns;
- **"may be spurious"** — in-sample only, or driven by few independent companies.

---

## 14. Memory, by learner and by kind

| Kind | W | O | B | R |
|---|---|---|---|---|
| **Facts** (immutable, sourced) | documents, claims, events | owner statements (as statements, with date), orders, deals, stages | — | action logs |
| **Beliefs** (distributions) | source trust, change rates, dynamics | slots | pattern effects, lags, fit, calibration | action models, program yields |
| **Hypotheses** | concept splits, dynamics relations | belief changes, challenges | patterns, refinements, disqualifiers | programs, templates, sources |
| **Procedural** | normalizer prompts | question templates | playbooks | programs, routing |
| **Episodic** | — | questions/answers/skips, drift events | case files, feedback, lessons | missed-opportunity post-mortems |

- **Ephemeral:** chain-of-thought, investigation scratch state, per-run budgets. Dropped after
  case close; summaries kept.
- **Discarded:** unverified claim text (counts kept), expired snapshots, recomputable embeddings.
- **Embeddings** are used only where similarity is the operation: concepts, lookalikes,
  pre-filtering.

---

## 15. Inbound: visible and answerable in the agent era (Gateway)

Buyers and buyers' AI agents should find the business, understand it correctly, and file a
request, with no AI commitments.

| Layer | What |
|---|---|
| Machine-readable facts | schema.org JSON-LD, structured catalog JSON (HS codes, specs, certifications, owner-published MOQ and lead-time ranges), `llms.txt`, sitemap. Every fact traces to a verified claim or a dated owner statement |
| Agent interfaces | A2A agent card, read-only MCP server (`view_catalog`, `get_product`, `request_quote`, `request_samples`), OpenAPI. One swappable adapter each; the standards are still moving |
| Receptionist | facts only; never price (unless published), discount, date, terms; always says when a person will reply |
| Intake | `quote_requests` + inbound case + deal brief |

**How inbound feeds the learners:**
- **B:** inbound requests are positives our outbound did not select. Their pre-request
  timelines feed pattern discovery.
- **O:** inbound demand reveals real segments and drift, and triggers challenge questions.
- **R:** inbound requests from companies we never surfaced are missed opportunities (§8.4) and
  drive coverage learning.
- **W:** aggregated agent queries are anonymous demand events in the world layer.
- **A:** unanswered buyer questions are clustered. VOI = frequency × conversion impact, which
  ranks them as owner questions ("publish a lead-time range to Rotterdam?").
- **Visibility as a learned outcome:** realistic sourcing queries are probed on a schedule. The
  system records whether the business appears and whether returned facts are correct, linked
  to profile changes so the effect of each change can be measured.

**Safety:** untrusted fencing, recorded and verified agent identity where possible, rate limits,
and a red-team set (commitment bait, injection) in `make golden`. **The commitment-refusal rate
must be 100%.**

---

## 16. The closed loop: what updates, where, by what rule

| Step | Learner | Update rule | Stored in | Evaluated by | Reverted by |
|---|---|---|---|---|---|
| Normalize + cluster events | W | LLM + embeddings; split/merge by usefulness | `event_concepts`, `events` | coherence, dynamics likelihood | strategy version |
| Update dynamics + source trust | W | hierarchical rates, out-of-time | `beliefs` (W) | next-event prediction | strategy version |
| Emit expectations | W, B | lag densities | `expectations` | hit rate vs base | — |
| Update org slots | O | Bayesian on answers, choices, contradictions | `beliefs` (O) | owner-choice prediction | strategy version |
| Update pattern effects, lags, fit, calibration | B | ledger refit with propensity weights | `beliefs` (B) | useful@K, calibration, lead time | strategy version |
| Pattern lifecycle | B | out-of-time + FDR + decision rule | `hypotheses` | promoted-pattern hold-up rate | strategy version |
| Update action models, program yields | R | Beta/hierarchical from action log | `beliefs` (R) | cost per resolved question | strategy version |
| Program evolution, source discovery | R | generate → trial → select | `search_programs` | yield | strategy version |
| Coverage post-mortems | R, B, W | replay of missed opportunities | `hypotheses` | recall | — |
| Policy knobs (§3.2) | meta | each knob's rule, meta-holdout | `policy_params` | its own metric | strategy version |
| Allocation | A | Thompson + value per cost under caps | `decisions` | outcomes per unit attention | — |
| Version + lessons | all | snapshot + diff | `strategy_versions`, `lessons` | promotion gate | restore snapshot |

---

## 17. Cold start → maturity (as seen in where effort goes)

| Stage | W | O | B | R | Allocation looks like |
|---|---|---|---|---|---|
| Day 1 | shared world + pooled dynamics | website + ~VOI questions + 8 examples | LLM priors + W proxy links | pooled action/source priors | mostly test + frontier; brief from strongest priors with "general reasoning" label |
| Week 1 | org-specific concepts appear | revealed preferences from ~25 ratings | first weights move; history case-control if uploaded | first local yields | test budget concentrating; first retirements |
| Month 1 | expectations hitting/missing | drift checks; first challenge | patterns split into exploit/explore; lag densities shaped | weak templates replaced | exploit share up; watches booked months ahead |
| Month 3 | stable local concepts | stable; asks rarely | first discovered patterns validated out-of-time; proxy chain calibrated | org-specific playbooks | mostly exploit + targeted experiments |
| Month 6 | — | drift-driven | own data dominates priors on core patterns | stopping learned | experiments mainly from missed opportunities and drift |
| Year 1 | contributes to pooled dynamics | — | seasonality possible; cross-org priors for new patterns | contributes to pooled models | stable; learning effort scales with surprise |

---

## 18. Evaluation

### 18.1 System metrics (outcomes per unit attention)

1. **Net-new reach:** good opportunities the owner did not already know about, per week, and
   the number of new regions/segments that produced at least one of them.
2. Useful opportunities per owner-hour and per dollar.
3. Useful-opportunity rate at the owner's K (SPEC headline).
4. **Evidence correctness** (audited; any drop blocks release).
5. Lead time vs. the opportunity becoming obvious.
6. **Recall** of known opportunities (inbound, wins, public awards in category) briefed before
   they became obvious.
7. Calibration of P(good).
8. Downstream conversion per briefed case (sparse, with intervals).

### 18.2 Per-learner metrics

See §5.4, §6.6, §7.7, §8.5. A system gain is credited to a learner only through **ablation
replays**: freeze that learner and see what is lost.

### 18.3 Historical replay

- **Point-in-time corpus** with trusted `available_at`: TED notices (immutable, dated), dated
  news, archived website snapshots where available.
- **Each simulated day:**
  1. Build timelines from available data only.
  2. The allocator spends a fixed budget.
  3. A simulated owner rates cases good if a ground-truth outcome follows within horizon. Noise
     and delay are added. Ground truth = a proxy event in the org's category, the org's real
     later customers, or inbound.
  4. All learners update.
- **Controls:** anonymized entities for the LLM, a no-LLM baseline, and a frozen-policy baseline.
- **Searches are replayed too:** a program only "finds" documents available at t *and*
  reachable by that program's sources. Learning to search better is therefore measurable.

### 18.4 Proving version 10 beats version 1, and gating every change

- Same corpus, days, budget, simulated-owner seed. Bootstrap intervals over days.
- **Learning curves** for:
  - (a) priors only, no learning,
  - (b) full system,
  - (c) score learning only, search frozen (proves learning changes *search*, not just ranking),
  - (d) no controls (shows the bias),
  - (e) each learner ablated.
- **Promotion gate** for any learned change (weights, patterns, programs, knobs):
  - no regression in evidence correctness,
  - non-inferior useful@K and recall,
  - golden set passes.

  Otherwise it stays in shadow or rolls back.
- **Live, once there are users:** off-policy estimates from logged propensities; interleaved
  briefs between versions.

---

## 19. Architecture alternatives (summary)

| | A. LLM agent + memory notes | B. Statistical predictor | C. Four learners + allocator (this) | D. End-to-end RL policy |
|---|---|---|---|---|
| Day one | high | none | high | low |
| Learns from history | anecdotal | needs volume | yes (case-control, proxies) | weak |
| Discovers new patterns | unverified prose | within features only | yes, validated | no |
| Learns where to search | in prompts, untestable | no | **yes, measured** | in principle; data-starved |
| Sparse data | brittle | fails | proxies + priors + shrinkage | fails |
| Explainable | plausible, unverifiable | low | high | low |
| Hallucination / overfit risk | high / high | low / high | low / controlled | medium / high |
| Hackathon feasibility | high | low | medium | low |

**C is chosen.** A's reasoning becomes proposals and priors. B's rigour appears as small
models inside each learner. D's idea appears only where justified: Thompson allocation and
learned action models.

---

## 20. Where Nemotron (LLMs) belong

- **Perceive:** extract, normalize, name concepts, map feedback text to codes.
- **Propose:** org beliefs, patterns, refinements, query variants, candidate sources,
  explanations of failure clusters.
- **Interpret:** quote-support check, gate, skeptic reading, judge questions.
- **Speak:** questions, drafts, lessons, plain-language patterns, receptionist.

**Never trusted to decide:**
- facts (code check),
- identity (review),
- dates and lags,
- probabilities (calibrated mapping only),
- validation and retirement,
- allocation,
- prices and commitments.

**Routing:**
| Tier | Use |
|---|---|
| Fast (Nano-class) | high-volume perception |
| Mid (Super-class) | gate, skeptic, receptionist, drafts |
| Deep (Ultra-class, reasoning) | judge on finalists, hypothesis proposal, failure analysis, onboarding inference |
| Embed | concepts, lookalikes |

Routing is adapted by disagreement sampling (§3.2). Exact model ids must be confirmed against
Token Factory.

**No fine-tuning now.** Verified claims and confirmed normalizations accumulate into a clean
dataset to distil perception into the fast tier later, for cost.

---

## 21. Data model changes (described; SQL after agreement)

- `documents`: `available_at` (trusted availability; NULL = not replay-safe).
- `event_concepts`: hierarchy (`parent_id, level, label, description, embedding, status`),
  seeded with the 12 generic types.
- `events`: `concept_id`, `slots jsonb`; keep `event_type` as level 0.
- `hypotheses`: one registry for all learners (`learner, kind, body jsonb, status, origin,
  proposed_at, tests jsonb, decided_at`).
- `patterns` view over hypotheses of kind pattern; `playbooks` (procedural half of `theses`).
- `search_programs`: `id, workspace_id (NULL = shared), source_hypothesis, templates, sources,
  filters, schedule, status, yields jsonb`.
- `expectations`: `company_id, concept_id, window_start, window_end, origin, status
  (pending|met|missed), value`.
- `beliefs`: `learner, workspace_id, strategy_version, kind, key, params jsonb, n_evidence,
  prior_source`.
- `belief_source_calibration`: learned bias/spread per prior source (meta-calibration).
- `policy_params`: every adaptive knob with default, current value, update rule id, metric.
- `decisions`: every brief/search/investigation/question choice with features, value estimate,
  **propensity**, cost, strategy version.
- `failure_attributions`: `feedback_id, code, learner, component, target_id, weight, confirmed`.
- `missed_opportunities`: source (inbound/win/public award), company, date, post-mortem result.
- `controls`, `lessons`, `inbound_queries`.
- Fixes from v1:
  - `case_evidence` gains an open-question companion table,
  - `cases` gets a unique key on (workspace, company, pattern, open window),
  - `contacts` gets `workspace_id`.
- `theses.alpha/beta` → `beliefs`. `strategy_versions.snapshot` → all learner states +
  `policy_params` + prompt versions.

---

## 22. Hackathon minimum (by 30 Oct): what is real vs. defaulted

Every one of the 8 required properties is real in a minimal form. Adaptive knobs exist as
`policy_params` with defaults. Only some get their update rule implemented in time.

| Property | Minimum real version |
|---|---|
| Day-one usefulness | website → O slots → VOI questions (cost model: fixed default) + example choice → LLM priors + W proxy links → brief |
| Learns from history | customer list → point-in-time timelines (TED + dated news) → sequential case-control → B priors |
| Discovers patterns | W dynamics on TED + news (concept → proxy lift), plus single-concept and pair mining for B, out-of-time + FDR |
| Learns from mistakes | 8 reason chips + "already knew?" tap → routed updates → **visible behaviour change** + lesson |
| **Grows reach** | net-new reach counter on Today; frontier searches shown as "new markets I'm testing"; buyer-language queries for target regions |
| Adaptive investigation | open questions generated from B/W/O; one-step VOI over 6 actions with Beta action models |
| **Learning changes search** | patterns compile into programs; allocator funds exploit/test/watch by value per cost; retirement de-funds; one generate→trial→select loop for query templates |
| Temporal reasoning | log-normal lag densities with posterior; expectations + watches |
| Improves with use | TED replay: curves (a) priors only, (b) full, **(c) score-only learning with search frozen**, (d) no controls |

**Adaptive in the MVP:**
- lag densities,
- meta-calibration of LLM priors (from replay),
- allocation (VOI / Thompson),
- pattern complexity by out-of-time evidence (up to pairs + one absence in practice, because
  data limits it, not because code does),
- query template evolution,
- investigation stopping.

**Defaulted with update rule stubbed:**
- owner attention and capacity models,
- concept split-by-usefulness (use LLM clustering + fixed threshold for now),
- tier routing,
- sequential control sampling.

Each is listed in the README as "adaptive by design; default in this build".

### Build order (fits the existing 4 weeks)

**Week 1 (→ 8 Oct): substrate**
1. Skeleton, schema (§21), queue, Makefile.
2. `llm.py`. Confirm Token Factory model ids, structured output, embedding dimension. Test
   deploy + Postgres/pgvector on Nebius now.
3. Sensors with `available_at`: safe fetch, TED (confirm date + CPV search), Tavily.
4. Evidence ledger; normalization + seed concepts + clustering.
5. Point-in-time timeline builder; pattern DSL evaluator; decision log.

**Week 2 (→ 15 Oct): learners, first pass**
6. W: dynamics on TED/news (concept → proxy lift, lag densities), expectations.
7. O: slots, VOI questions, example choice.
8. B: LLM priors, case-control, proxy chain, ledger behind its interface.
9. Replay harness + simulated owner + golden set.

**Week 3 (→ 22 Oct): behaviour changes from learning**
10. R + A: search programs from patterns, allocator with value per cost, watches,
    investigation VOI, template evolution.
11. Feedback chips → routing → behaviour changes → lessons → strategy versions + rollback.
12. Missed-opportunity post-mortem (from replay ground truth).
13. Frontend: Today, Case file (trace + why each action), Setup chat, What I learned (including
    "what I now search for").

**Week 4 (→ 30 Oct): Gateway-lite + ship**
14. Gateway-lite: JSON-LD + catalog + agent card + read-only MCP + receptionist + red-team set.
15. Deploy, README (Nemotron / Token Factory / Tavily usage), licence, secrets scan.
16. Video:
    - day-one brief,
    - a rejection with a reason → **the search portfolio visibly shifts**,
    - the replay curves (b) vs (c),
    - a buyer agent files a request through MCP → it becomes a case and a missed-opportunity
      lesson.

**Cut order if behind:**
1. template evolution,
2. pair mining,
3. frontier search,
4. receptionist (keep static facts + agent card + MCP).

**Never cut:** the evidence ledger, controls, point-in-time replay, the decision log with
propensities, and patterns compiling into search programs.

---

## 23. What NOT to build

- A fixed signal catalog or industry rules in code.
- A per-org trained classifier or neural model.
- End-to-end RL; multi-step planners before greedy VOI is shown to fail.
- An advocate agent, debate loops, swarms.
- A graph database or a separate vector database.
- Fine-tuning before a distillation dataset and a cost case exist.
- Raw LLM confidence as a score; lessons that aren't backed by a recorded change.
- Live-web replay.
- Adaptive mechanisms without a meta-holdout and a trust region.
- Auto-sending, auto-negotiation, AI answers on price, discount, date or terms.
- Scraping where forbidden.

---

## 24. Open questions for the founder

1. Workspace #1: what history exists (customers with dates, orders, lost deals, inbound)?
2. Is a TED-based replay acceptable as the learning proof if the real business sells mainly
   to private buyers?
3. Which public proxy events are legal and available for your buyers (tenders, planning
   portals, import records)?
4. Solo or team? This affects whether Gateway-lite runs in parallel from week 2.
5. Named contacts or roles only?
