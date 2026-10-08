# Learning loop design: learning from little feedback, and proving it improves

Date checked: 2026-10-09. Author: researcher. No code written; this is a design note.

Tags: **[confirmed]** = stated in the cited source (abstract or page read this session; full
texts were not read unless said). **[inferred]** = my reasoning from sources or from the repo.
**[unknown]** = could not be confirmed; how to confirm is given.

## 1. Summary

- With 10-100 labels, the realistic learner is **not a model**. It is a set of **Beta posteriors
  with pooled priors** (empirical-Bayes shrinkage) over a few named things: search program,
  source, country, pattern. Each label moves one posterior a little, and a client's first labels
  change nothing until a posterior is clearly away from its prior. [inferred]
- **Off-policy evaluation (IPS, doubly robust) cannot prove anything at 10-100 labels.** Variance
  is too high. Keep logging propensities now (cheap, needed later), use IPS/DR only as a v2
  tool, and in v0 prove improvement with **point-in-time replay on public history** plus a
  **frozen-baseline comparison on the same replays**. [inferred, supported by the OPE sources
  below]
- Today every `decisions` row is written with propensity 1 (D86, `persist.py`). Propensity 1
  everywhere means OPE has nothing to work with. v0 must add **one small randomized exploration
  slot** with a real propensity. This is the single most important change for later proof.
  [confirmed from repo: `persist.py` line 282 hardcodes `1`]
- `decisions.features` does **not** currently record the search program, query, or source that
  found the candidate (only `stream`, `country`, counts, `window_start`). Search-program yield
  learning needs that credit link. [confirmed from repo, `_features()`]
- Hard rule that follows from D79: every label, outcome and result produced by the simulated
  owner carries a `simulated` marker and is never mixed into a real client's posteriors.

## 2. Facts table (sourced)

| # | Fact | Source | Conf. |
|---|---|---|---|
| 1 | Thompson sampling is a tutorial-level, computationally efficient method balancing exploiting known-good options with exploring; worked examples include Bernoulli bandits and product recommendation. | Russo, Van Roy, Kazerouni, Osband, Wen, "A Tutorial on Thompson Sampling", https://arxiv.org/abs/1707.02038 (checked 2026-10-09) | confirmed (abstract) |
| 2 | Thompson sampling performed strongly in simulated and real-data experiments and is simple enough to be a standard baseline. | Chapelle and Li, "An Empirical Evaluation of Thompson Sampling", NIPS 2011, https://papers.nips.cc/paper/2011/hash/e53a0a2978c28872a4505bdb51db06dc-Abstract.html | confirmed (abstract via search) |
| 3 | A hierarchical Thompson sampling algorithm (HierTS) shares knowledge across tasks; a more informative prior lowers regret. | Hong, Kveton, Zaheer, Ghavamzadeh, "Hierarchical Bayesian Bandits", AISTATS 2022, https://arxiv.org/abs/2111.06929 | confirmed (abstract) |
| 4 | MetaTS meta-learns an unknown prior over bandit instances as it goes, and adapts quickly to the unknown prior (Gaussian bandits). | Kveton et al., "Meta-Thompson Sampling", https://arxiv.org/abs/2102.06129 | confirmed (abstract) |
| 5 | Shrinking raw rates toward a prior mean with a Beta prior gives posterior mean (a + h)/(a + b + n); weight on the prior is kappa/(kappa + n), kappa = a + b. Low-count items are "shrunken" toward the overall average. Playing time (here: volume) can correlate with true rate, so one shared prior can misfit low-volume items. | Efron-Morris baseball example and David Robinson's empirical-Bayes series (blog, last resort source), https://www.r-bloggers.com/2016/05/understanding-beta-binomial-regression-using-baseball-statistics/ ; Efron-Morris field test https://arxiv.org/pdf/0803.3697 | confirmed (blog summary; the blog is a non-official source) |
| 6 | Doubly robust (DR) policy evaluation combines a reward model and a propensity model; estimates are accurate if either model is good; reduces variance vs IPS. | Dudik, Langford, Li, https://arxiv.org/abs/1103.4601 | confirmed (abstract) |
| 7 | Replay evaluation on logged data from a (uniformly) random logging policy gives provably unbiased offline estimates; matched online results in a Yahoo news study. | Li, Chu, Langford, Wang, https://arxiv.org/abs/1003.5956 | confirmed (abstract). Needs randomized logging: confirms the exploration slot is required. |
| 8 | Too little randomization in logging gives high-variance IPS (tiny propensities give huge weights). Clipping weights trades small bias for lower variance; shrinkage estimators (Su et al., ICML 2020) do the same with a better finite-sample tradeoff. | Su et al., https://proceedings.mlr.press/v119/su20a.html ; https://arxiv.org/pdf/1907.09623 | confirmed (search summary of abstracts) |
| 9 | Plain IPS can overfit propensities when learning; the self-normalized estimator avoids this. | Swaminathan and Joachims, NIPS 2015, https://papers.nips.cc/paper/2015/hash/39027dfad5138c9ca0c474d71db915c3-Abstract.html | confirmed (abstract) |
| 10 | Open Bandit Pipeline is an open-source Python library with many OPE estimators and a real logged dataset with several logging policies. | Saito et al., https://arxiv.org/abs/2008.07146 ; docs https://zr-obp.readthedocs.io/ | confirmed (abstract). Which estimators are included: unknown; check the docs. |
| 11 | Delayed feedback: model the delay; a non-converting user is either a real negative (enough time passed) or not yet known (drop it from training). | Chapelle, "Modeling Delayed Feedback in Display Advertising", KDD 2014, https://unpaywall.org/10.1145%2F2623330.2623634 | confirmed (summary) |
| 12 | Assessors find pairwise preference judgments easier than absolute ones (hypothesis, with evidence from a study); you need not compare all pairs, using inference and careful pair selection. | Carterette, Bennett, Chickering, Dumais, "Here or There", ECIR 2008, https://www.microsoft.com/en-us/research/uploads/prod/2008/01/HereOrThere-ECIR-2008.pdf | confirmed (abstract via search). Study numbers not read. |
| 13 | A strong LLM judge reached over 80 percent agreement with human preferences, similar to human-human agreement. Known biases: position, verbosity, self-enhancement, limited reasoning. | Zheng et al., "Judging LLM-as-a-Judge", https://arxiv.org/abs/2306.05685 | confirmed (abstract). Chat-quality setting, not B2B lead rating: transfer is inferred. |
| 14 | Prediction-powered inference gives valid confidence intervals from a small gold-labelled set plus model predictions; better predictions give narrower intervals. | Angelopoulos et al., https://arxiv.org/abs/2301.09633 | confirmed (abstract) |
| 15 | LLMs can leak future knowledge in backtests (lookahead bias); remedies are statistical tests of memorization, inference-time corrections, and time-cutoff models. | Gao, Jiang, Yan, arXiv:2512.23847; Sarkar and Vafa 2024; DatedGPT arXiv:2603.11838 (found via search, abstracts only) | confirmed that the problem is documented. Specific effect sizes (e.g. a "37%" figure in a secondary summary): **unknown, not used**. |
| 16 | User simulation is an established method for evaluating and generating training data for interactive systems. | Balog and Zhai, https://arxiv.org/abs/2501.04410 ; monograph https://arxiv.org/pdf/2306.08550 | confirmed (existence and framing). Validity guidance in the paper: not read, unknown. |
| 17 | Continuous active learning for high-recall review (e-discovery) works from a short seed and relevance feedback; the papers study effectiveness and failure frequency. | Cormack and Grossman, https://arxiv.org/abs/1504.06868 | confirmed (abstract). The recall-estimation procedure was not read: unknown. |
| 18 | Selection bias in logged clicks can be estimated and corrected in learning to rank (personal search). | Wang, Bendersky, Metzler, Najork, SIGIR 2016, https://research.google/pubs/learning-to-rank-with-selection-bias-in-personal-search/ | confirmed (abstract via search) |
| 19 | Recommender poisoning attacks (fake users with crafted ratings) are a documented threat, with taxonomies of countermeasures. | https://arxiv.org/abs/2404.14942 ; https://arxiv.org/abs/2406.01022 | confirmed (abstracts) |
| 20 | Feedback loops are named among ML-specific production risks; production ML needs data, model and monitoring tests (28 tests in a rubric). | Sculley et al., NIPS 2015, https://research.google/pubs/hidden-technical-debt-in-machine-learning-systems/ ; Breck et al., https://research.google/pubs/pub46555/ | confirmed (abstract-level) |
| 21 | Practitioner guidance (blog/podcast, last resort): read real traces first, count failure frequency, prefer binary pass/fail judgements, validate LLM judges against human labels; teams rarely add error bars to evals. | Husain, summarised at https://www.lennysnewsletter.com/p/evals-error-analysis-and-better-prompts | confirmed as summarised; non-official source |
| 22 | Peeking at running tests inflates false positives; fix sample size in advance or use sequential methods. | Practitioner posts (e.g. https://www.atticusli.com/blog/posts/peeking-problem-checking-test-early-destroys-validity/); Evan Miller essay not retrieved | confirmed (blog-level); original essay: unknown |

## 3. What is realistic at 10-100 labels

All arithmetic below is mine. [inferred]

- **Precision is only known roughly.** At 50 labels with a true 20 percent good rate, the standard
  error is sqrt(0.2 x 0.8 / 50) = 0.057, so a 95 percent interval is about 9 to 31 percent.
- **A real lift is expensive to detect.** To see 20 percent go to 35 percent with 80 percent
  power (two-sided 5 percent, two groups), about 140 labelled cases **per arm**. This is why v0
  never claims a per-client lift from owner labels alone.
- **Contextual models are out.** Any model with more parameters than labels fits noise. Allowed
  parameters at 10-100 labels: one rate per (program), per (source), per (country), per
  (pattern), each shrunk to a parent. No interactions in v0.
- **OPE.** With a 10 percent exploration slot, a case in that slot has weight 10 under IPS; a
  few such cases dominate the estimate. IPS/DR intervals will be wider than the effect you want
  to prove. Use them from roughly several hundred randomized, labelled decisions (a **rule of
  thumb**, not a sourced number). [inferred; unknown exact threshold]
- **Pooling is what makes small n useful.** A new client starts at the pooled prior across
  clients, then a client-specific posterior forms as labels arrive. Sources 3, 4 and 5 support
  this shape. The pooled prior must come from **other clients' or simulated** data only if
  clearly separated and marked (see section 8).

## 4. Design: learning loop v0 (about two sessions)

Everything fits existing tables. Names below are schema names. Schema additions are listed in
4.6 and are small.

### 4.1 Label mapping (feedback and outcomes to evidence)

Do not treat all four ratings as one negative. [inferred]

| `feedback.rating` | Meaning for learning | Goes to |
|---|---|---|
| `good` | positive for buying fit and for the search path that found it | B (pattern), R (program/source/country) |
| `not_relevant` | negative for fit; `reason` (too_small, wrong_region, already_customer, ...) says which belief | O/B; reason maps to a component via `failure_attributions` |
| `wrong_facts` | **not** a buying-fit negative. A data-quality failure | W (source reliability); verifier/extractor tests. Never lowers a pattern's rate. |
| `later` | timing, not fit. Count as "not now" | lag belief; a recheck date. Neither positive nor negative for the pattern. |

Outcomes (`outcomes.stage`: replied, meeting, quoted, won, lost) are stronger labels but arrive
late and rarely. Treat them as **right-censored** (fact 11): a case contacted less than the
censoring horizon ago with no reply is "unknown", not negative. Horizon = a policy param
(`learning.censor_days`, default 45, a guess [unknown], to be set from the first 20 real
outcomes' lag distribution).

### 4.2 What is learned in v0 (all in `beliefs`, one row per key)

Each key holds `params = {a, b}` of a Beta posterior and `n_evidence`; `prior_source` records
where the prior came from.

| `beliefs.learner` / `kind` | `key` | Updated by |
|---|---|---|
| `research` / `program_yield` | search program id (or query template hash) | good / not_relevant labels of cases that program found; plus public-history hits |
| `research` / `source_yield` | source name (tavily, ted, website, ...) | same, by source |
| `research` / `country_yield` | ISO country | same, by country (feature already in `decisions.features`) |
| `buying` / `pattern_rate` | pattern hypothesis id | labels and outcomes of cases with `pattern_id` |
| `world` / `source_reliability` | source | `wrong_facts` ratings and claim-check failures (not owner fit labels) |

Update rule (empirical Bayes, fact 5): prior Beta(a0, b0) with pseudo-count kappa chosen from
pooled data (start kappa = 10 as a stated default [inferred], re-fit by method of moments when at
least 5 parents have >= 5 labels). Posterior mean = (a0 + good) / (a0 + b0 + n). A **child**
(program) shrinks to its **parent** (source, then client mean, then pooled prior). Owner-given
statements are priors with their own `belief_source_calibration` row (that table already exists
for this).

Weights, not truths: a label from a rater with a low consistency score (see 4.5) gets weight < 1
(`failure_attributions.weight` and a per-update weight).

### 4.3 What changes behaviour (this is the point)

1. **Search allocation by Thompson sampling.** Each night, for each active program draw
   `theta ~ Beta(a, b)` from its posterior, multiply by cost-per-call, and fund the top programs
   within budget (facts 1, 2). Log the **propensity**: with Monte-Carlo draws (e.g. 200), the
   share of draws in which this program was selected is its propensity. Write it to
   `decisions` (`kind = 'search'`, `propensity` > 0). [inferred; the allocator's section 9 already
   specifies "sample from posteriors (Thompson)"]
2. **Exploration floor** (already an invariant, ARCHITECTURE section 13): no active program below
   a minimum call share, e.g. 5 percent of search budget, so that a bad early label cannot kill
   a program forever.
3. **Retirement rule.** A program moves `active` to `paused` when the posterior probability that
   its good-rate is below the client's mean is > 0.9 **and** n >= 8 labelled cases **and** it has
   consumed >= a minimum number of calls. These numbers are starting guesses [unknown]. `paused`,
   not `retired`; a low-rate forced retest (every N weeks) can revive it (ARCHITECTURE section 13).
4. **One randomized brief slot.** Among gated candidates that missed the brief cut, pick one at
   random (propensity = 1 / number eligible) and brief it, flagged `exploration` in `choice`.
   This is the only way to get unbiased labels about what the cut throws away (fact 7, fact 8).
   Cost: one slot of the daily brief. [inferred]
5. **Brief ranking** still comes from the existing deterministic strength; the posterior only
   re-orders ties and trims programs with proven low yield. No new score is introduced in v0.

### 4.4 Logging fixes needed first (session 1, blockers)

- Add to `decisions.features` for `kind='brief'`: `program_id`/`query_template`, `source`,
  `thesis_id`/`pattern_id`, `strategy_version`. Currently missing (checked `_features()`).
  Without it, credit cannot flow from a label to a program. [confirmed gap]
- Replace propensity 1 with the real selection probability (1 for deterministic top-k stays
  correct; for exploration slot use 1/m; for searches use the Thompson share).
- Persist `strategy_version` on every decision and case trace (column exists on `decisions`).

### 4.5 Owner rating handling

- **Collect more than a thumb.** Absolute 4-way rating stays (cheap, one tap). Add an optional
  **A-vs-B pairwise choice** among two briefed cases once the owner has >= 6 rated cases. Reason:
  assessors find preferences easier (fact 12), and pairs remove personal scale differences. The
  cost is that pairs need a Bradley-Terry-style model; only collect them in v0 and fit in v1.
  [inferred; no table exists: see 4.6]
- **LLM-as-judge is a helper, never the label.** v0: use the judge only to **pre-sort** which
  cases to show for rating and to write the `reason` suggestions. The judge must be calibrated
  to the owner on a small gold set: keep >= 20 owner-rated cases, measure agreement, report it
  with an interval; below the agreement bar, judge outputs are not used for anything.
  Position-swap every pairwise judge call (fact 13: position and verbosity bias). Prediction-
  powered inference (fact 14) is the principled way, in v1, to use judge labels to tighten
  intervals while the owner's labels keep the estimate valid.
- **Consistency check.** Re-show 1 in 10 previously rated cases (blind). Rater consistency under
  about 70 percent (guess [unknown]) lowers that rater's update weight and raises a question to
  the owner instead of silently learning.

### 4.6 Schema additions (small; ask founder before applying)

| Change | Why |
|---|---|
| `feedback.source text CHECK IN ('owner','simulated','judge')` and `feedback.weight real DEFAULT 1` | simulated honesty (D79) and weighted labels |
| `outcomes.source` same values | same |
| `decisions.features` convention (no DDL) | program/source/thesis/strategy_version |
| `pairwise_preferences(workspace_id, user_id, case_a, case_b, winner, created_at)` | v1 pairwise (only collected in v0) |
| `search_programs.yields` (exists, jsonb) | holds `{calls, docs, claims_verified, cases, good, n_labelled, cost_usd}` per program: no DDL |
| `strategy_versions.snapshot` (exists) | holds all `beliefs` for the workspace at that version: no DDL |

### 4.7 Strategy versions and rollback

- Nightly learning writes **one new `strategy_versions` row**: the full belief set as `snapshot`,
  a plain-language `changes`, and one `lessons` row per behaviour change (the schema already
  forces a lesson to have a recorded change).
- **Trust region:** per night, a belief's posterior mean may move the funded share of a program by
  at most X (start 25 percent relative) [guess, unknown]. This stops one night's labels from
  re-routing the whole budget.
- **Promotion gate (section 5.3):** a new version becomes `current` only if it passes the replay
  gate. If not, it stays in shadow (computed, not used). Rollback = point the workspace at an
  earlier `version`; nothing is deleted.
- Never learn from a label until the **claim-check and truth tests are green on that case**
  (a `wrong_facts` case should not yield a "this program is good" update even if rated good
  elsewhere).

## 5. Evaluation

### 5.1 Metrics and how they are computed (all from existing tables)

| Metric | Definition | Data needed |
|---|---|---|
| precision@k of briefs | share of the top-k briefed cases per run rated `good` (and, separately, reaching `replied`+) | `cases`, `feedback`; report with Wilson/Beta interval |
| cost per good lead | sum `llm_calls` + search cost over runs / count of good-rated, owner-new cases | `decisions.cost_usd`, `llm_calls`, `feedback` |
| coverage / recall | of known real opportunities (public awards in category, inbound, wins) how many were briefed before they became public/obvious | `missed_opportunities.postmortem_status` (surfaced_in_time / late / dropped / not_surfaced) |
| time-to-signal | days between the first public signal's `available_at` and the brief date | `documents.available_at`, `cases.created_at` |
| calibration | for bins of predicted strength/P(good): observed good rate; report Brier and a reliability table | `decisions.value_estimate`, `feedback` |
| program yield | good cases per search call and per dollar, with intervals | `search_programs.yields` |
| evidence correctness | zero violations (existing level 1) | existing gate |

### 5.2 Small-team practice (adopted)

- **Golden set + regression gate.** Already in `EVALUATION.md` level 2. Extend with a **labelled
  gate set**: each owner rating becomes a (case snapshot, label) example, replayed on each
  release. [inferred, matches EVALUATION.md "Next"]
- **Read data before building judges** and prefer binary judgements (fact 21, blog-level).
- **Always report intervals.** No "improved" claim without one (fact 21: error bars are rarely
  shown, so showing them is itself a differentiator).
- **Fix the test before looking** (fact 22): the evaluation window and metric are written down in
  the `strategy_versions.changes` entry **before** the replay result is read; no repeated peeking
  to a pass.
- Prefer a separate **meta-holdout** time slice for tuning knobs (ARCHITECTURE section 13).

### 5.3 v0 proof method: point-in-time replay on public history

Goal: show learned version N+1 is at least as good as N on events **after** the learning data.

1. Choose `as_of` dates. Build everything from documents with `available_at <= as_of` (the repo
   already caps `available_at` at `as_of`; asserted in code per ARCHITECTURE section 13).
2. **Ground truth label** for a signal-case: "a tender, award or RFQ in the same category and
   buyer/company appeared within horizon H after the brief date". Taken from TED/award notices
   whose own `available_at` is after `as_of`. Horizon H fixed in advance.
3. Replay version N and version N+1 on the **same days, same budget**; compare precision@k,
   recall of later awards, cost per hit. Bootstrap intervals over days. Also run a **frozen
   baseline** (version 0 or a no-learning policy) and, where an LLM reads text, a **no-LLM
   baseline** (ARCHITECTURE 18.3).
4. **Leakage controls (fact 15):**
   - never use documents with `available_at > as_of`, including for search results (a replayed
     program only "finds" what existed then and what its sources could reach);
   - use only labels whose **event time** is after the training cut: train belief on labels with
     time <= T, test on labels with time > T;
   - anonymize entity names in replay prompts, and prefer test periods **after the model's
     training cutoff**; the model's cutoff date must be read from its model card [unknown for the
     Nemotron ids in use: check the model card on Nebius/NVIDIA before claiming a clean
     period];
   - a **memorization probe**: ask the LLM, with no context, to predict the outcome of a few
     replayed cases; if it does well, the replay on those cases is not trusted (idea from the
     lookahead-bias literature; the exact test is unknown, I did not read the paper bodies);
   - near-duplicate documents (a re-published notice) must be clustered so one story is one
     example, else duplicates leak across the train/test split.
5. **Expectations as free labels.** An `expectations` row (company, concept, window) resolves to
   `met` or `missed`. Resolved rows are labels for the **world** learner and the lag belief, not
   for owner fit. Only count resolution from documents with `available_at` after the expectation
   was created. A `missed` needs a check that the window really ended and the sensor was working
   (else sensor downtime is learned as "the world did not do it"). [inferred]

### 5.4 Missed-opportunity audit (recall)

- Sources: inbound requests, real wins, public awards in the client's categories
  (`missed_opportunities.source`).
- For each: replay, classify into `postmortem_status`, route per ARCHITECTURE 8.4.
- **Estimating total recall** when the true set is unknown: use the above as an unselected
  sample (they did not come from our searches) and report recall with an interval. A
  capture-recapture style estimate is possible [inferred], and the e-discovery literature
  (fact 17) studies high-recall workflows, but I did not read its estimation method: unknown.
- Weakness: public awards cover only tender-driven buying. Say so in the report.

## 6. Simulated owners: honest use

[inferred unless stated; fact 16 only establishes the method exists]

- **Purpose:** exercise the loop end to end and catch bugs and unstable dynamics (does the budget
  collapse onto one program? does a wrong rating get fixed?). **Not** to claim product
  performance.
- **Rules:**
  1. Every row it creates has `source = 'simulated'` (4.6) and a simulated workspace id.
     Reports print "SIMULATED" in the title and per number.
  2. Simulated labels never update beliefs of a real workspace and never feed the pooled prior
     unless the pooled prior row is itself tagged `prior_source = 'simulated'`.
  3. Preferences are **written as data** (a small spec the founder can read: segments liked, size
     limits, regions), not hardcoded industry words (CLAUDE rule 1).
  4. Ground truth for simulated outcomes comes from **public history** (award followed), not from
     the same LLM that wrote the owner persona. Otherwise the loop learns the simulator's quirks.
  5. Add noise and delay (flip 10-20 percent of labels, delay outcomes by weeks in replay time)
     and run **several owner seeds**; a result must hold across seeds.
  6. Add an **adversarial simulated owner** (inconsistent, biased to one country, rates in
     bursts) to test poisoning and drift defenses.
  7. **Calibrate the simulator against reality when real labels exist:** compare the simulated
     owner's answers on the first real cases; if agreement is poor, say so and downgrade it.

## 7. Safety of learning

| Threat | Defence in v0 | Source/basis |
|---|---|---|
| One owner or one bad day dominates | per-update weight; trust region per night; minimum n before retirement | inferred |
| Feedback poisoning (malicious or sloppy labels) | only authenticated members (`memberships`) may label; per-user rate limit; labels are weighted, not truth; large swings are queued as a question to the owner rather than applied | threat documented (fact 19); defence inferred |
| Prompt injection via buyer or page content reaching the label path | fetched content is data; reasons are a closed set (`reason` codes), free text never enters the updater | CLAUDE rules 7 and 10, D85 |
| Feedback loop (we only see what we show) | exploration slot with propensity; exploration floor per program; forced retest of paused programs | fact 20; facts 7 and 8 |
| Drift (the world or the owner changes) | prior pseudo-count caps (n_evidence capped, e.g. effective n <= 50) so old data decays; compare to frozen baseline monthly; a program's recent window vs lifetime yield alarm | inferred |
| Selection bias on what is labelled | the owner labels only what we show; use the exploration slot and inbound/awards as unselected checks | fact 18 and ARCHITECTURE 13 |
| Wrong credit (a source error read as a bad pattern) | `wrong_facts` routes to source reliability only; failure code to learner mapping through `failure_attributions` | repo design |
| Irreversible change | every nightly update is a `strategy_versions` row; rollback by version; shadow mode if the gate fails | repo design |
| Peeking / p-hacking our own gate | metric, window and threshold are written before replay; gates are non-inferiority with margins stated | fact 22 (blog-level) |
| Simulated data counted as real | `source` column; separate workspaces; report headers | D79 |

## 8. Roadmap with evaluation and minimum data

| Version | What | Evaluation method | Minimum data |
|---|---|---|---|
| **v0** (two sessions) | Section 4: label mapping, Beta/shrinkage posteriors for program/source/country/pattern, Thompson search allocation with logged propensities, exploration slot, retirement rule, strategy versions with rollback; plus the replay proof (5.3) and simulated owner harness | Replay on public history: version N+1 vs N vs frozen baseline, precision@k, recall of later awards, cost per hit, bootstrap intervals; unit tests for update math; golden label set | Replay: a few hundred tender/award chains per category (TED); live: **10 or more labelled cases per client** to move any posterior visibly; **no per-client lift claim** below ~140 labels per arm |
| **v1** | Hierarchical pooling across clients and segments (kappa fitted, method-of-moments then full Bayes); delay model for outcomes (survival/hazard, fact 11); pairwise preferences fit with Bradley-Terry; judge calibrated to owner with prediction-powered intervals (fact 14); contextual features limited to 3-5 coarse ones; first off-policy estimates with **self-normalized, clipped IPS** and DR with a simple reward model (facts 6, 8, 9) | Compare estimated vs replay-measured value on the exploration slice (sanity: do OPE and replay agree?); report ESS (effective sample size) of weights; interleaved briefs between two versions for live A/B | ~3-5 clients with >= 30 labels each, or one client with ~200 labels including >= 40 from exploration; >= 20 owner-rated cases for the judge gold set; >= 50 contacted cases with matured outcomes for the delay model |
| **v2** | Contextual bandit over (program x context) with Thompson (HierTS-style sharing, facts 3 and 4); learned owner-attention cost; allocator information-value terms (ARCHITECTURE 9.2); automatic proposal and trial of new programs from missed-opportunity postmortems; cross-client pattern pool with the "validated in several orgs" rule | Ablation replays (freeze each learner); DR/OPE with bootstrap CIs on logged propensities; live interleaving; recall via the missed-opportunity audit | Many clients (>= 10) and thousands of logged randomized decisions; outcomes (replied or better) in the low hundreds; a stable audit set of awards/inbound |

Honest limit: until several clients exist, outcomes (replies, meetings, wins) are too rare for any
learner to rely on. Public award history and simulation carry v0; real labels only nudge it.

## 9. Two-session build split (guide, not a ticket)

- **Session A (plumbing and math):** logging fixes (4.4), label mapping and belief update module
  (`radar/learning.py`, pure functions: prior, update, shrink, Thompson draw, propensity share,
  retirement test), `strategy_versions` writer and rollback, unit tests with fixed seeds. No
  network, no DB needed for the math tests.
- **Session B (proof and loop):** exploration slot, nightly job wiring, simulated owner as data
  spec, replay harness on recorded runs with the leakage controls (5.3), report added to
  `tasks.py eval` (precision@k with intervals, cost per good lead, recall audit), shadow/promote
  gate.

## 10. Open questions

1. **Nemotron training cutoff:** needed to choose clean replay periods. Confirm from the model
   card for the ids in `.env` (`MODEL_MID`, `MODEL_DEEP`); not checked here. [unknown]
2. **Real thresholds** (kappa, censor_days, trust region, retirement n, consistency bar) are
   starting guesses; they should be re-set from the first real labels. [unknown]
3. **Are 140 labels per arm reachable** for the founder's own agency (workspace 1)? If not, the
   honest claim is "the loop works and is safe", proven by replay, not "lifts precision".
4. **Exploration slot cost:** founder to accept one random-ish brief slot per run (only way to get
   unbiased labels).
5. **Pairwise UI:** is a "which of these two?" tap acceptable in the owner flow?
6. **Capture-recapture or other recall estimators:** I did not read a source that validates one
   for this setting. Next step: read Cormack and Grossman's stopping/recall sections
   (https://arxiv.org/pdf/1504.06868) and decide.
7. **OBP estimator list** (to avoid writing OPE code): check https://zr-obp.readthedocs.io/ or run
   `uv pip show obp` after adding it; not verified.
8. To check the full text of any paper cited above beyond its abstract, open the URL in the
   table; only abstracts or search summaries were read this session.
