# Classifier experiment: can a small trained model imitate or pre-filter the Nemotron gate? (D92)

Date: 9 Oct 2026. Experiment only; no product code changed. Script:
`scripts/experiments/gate_classifier.py` (run with `uv run --group experiments python
scripts/experiments/gate_classifier.py --setfit --zeroshot`). Fact status marks:
**confirmed** (read at the source this session), **inferred** (reasoned from confirmed facts),
**unknown** (could not be found), **recalled** (from general knowledge, not re-checked today).

## Short answer

1. **Not now.** The recorded data holds only **98 Nemotron-decided gate rows**, and **89 of them
   (91%) passed**. A classifier that always says "passed" already agrees with Nemotron 90.8% of the
   time. None of the cheap classifiers beat that on accuracy, and at a threshold that keeps 95% of
   Nemotron-passed rows they would skip only about 4 to 6% of gate calls; at 99% kept, **0%**.
2. **The gate is not where the money or time goes.** One gate call is about 2,000 input and 300
   output tokens (plan estimate in `scripts/radar.py`), roughly **$0.0009 on the mid model**
   (0.30 / 0.90 USD per million tokens, `pricing.json`, if the gate uses the Super model: inferred).
   Skipping 5% of about 100 calls saves under half a cent per run.
3. **A classifier has a better home: learning from owner ratings** (rank and "ask the owner"
   decisions), once there are hundreds of real labels. Not as a replacement for the gate's
   buyer/competitor verdict.
4. **JEV**: the best match is **Jev by TypeSafe AI**, a hosted, proprietary "System One" model,
   announced mid-September 2026. Details, sources and a fit assessment are in the next section.

## Scope set by the founder: pages and sources only (9 Oct)

After this experiment the founder set the scope: classifiers are for sorting **pages and
sources** before extraction, never for buyer decisions. The gate result above therefore matters
less than it seems. The real target is the per-page extraction call.

- **What a page classifier labels:**
  - relevance (real project, purchase or organisation, versus noise);
  - document type;
  - source type;
  - event type.
- **Free labels:** each extracted page either produced verified claims or did not, so the
  pipeline labels its own training data.
- **Next experiment:** the same method as here, on recorded web pages with those labels. It
  needs more recorded full-text pages than today's mostly structured runs. Candidates are Jev,
  GLiClass, a small model of our own, and the LLM as the reference.
- **Plan:** docs/research/UPGRADE_PLAN.md, "Classifiers beyond the hackathon".

## JEV: what it is

The founder named "JEV" without details. Searches for "JEV classification model", "JEV text
classifier", "JEV huggingface / github / arxiv" return one consistent answer, and I found nothing
else called JEV that classifies text (the other hits were a crash-narrative paper that uses the
same model, and an unrelated video-quality tool).

| Fact | Status | Source |
|---|---|---|
| Jev is a classification model from **TypeSafe AI** (San Francisco), cofounder and CEO Diogo Almeida, ex-OpenAI. | confirmed (two independent write-ups) | [The Batch](https://www.deeplearning.ai/the-batch/models-built-to-do-one-thing-well), [Raschka](https://magazine.sebastianraschka.com/p/classifier-history-and-jev) |
| TypeSafe left stealth 15 Sep 2026 with a $40M seed led by DCVC. | confirmed (one secondary page; names may be out of date) | [drawpie.com](https://drawpie.com/blog/what-is-jev-typesafe-ai-model/) |
| It is **not a text generator**. You send a `state` (the text) plus typed questions, and get typed answers with probabilities. Question types: **Choice** (pick one of up to 255 options, with per-class probabilities and a confidence), **Noul** (probability a yes/no statement is true), **Score** (ordinal 2 to 10 levels). | confirmed | Raschka, drawpie, [aimlapi.com](https://aimlapi.com/models/typesafe-jev-latest) |
| **Proprietary, hosted API only.** One endpoint `POST /v1/systemone`, model id `jev-1.13.0` (aliases `jev-latest`, `jev-preview`). Also routed through Vercel AI Gateway, Cloudflare Workers AI, OpenRouter, MotherDuck and AIMLAPI. | confirmed (Raschka: "Jev is a proprietary model"; routes from drawpie, which says route availability for new users was not verified) | Raschka, drawpie |
| **No open weights. Licence terms: unknown.** Raschka: "a strong open-weight version would be nice." No licence, fine-tuning or local-run option found. | unknown (absence of information) | Raschka, drawpie |
| Size, architecture, training data: **not disclosed**. CEO quoted: "100% of our data is synthetic." Training method named "Reinforcement Learning for Calibrated Decisions". Raschka guesses a small ModernBERT-like model; that is his guess. | confirmed that it is undisclosed; the guess is inferred | Raschka, The Batch |
| Price about **$0.042 per million input tokens, output free** (another listing shows $0.058). On Raschka's IMDb run: 25,000 reviews, 15.5M tokens, **$0.65**, 22 min 24 s. | confirmed from two secondary sources, which disagree slightly; TypeSafe's own pricing page not read | drawpie, Raschka, aimlapi |
| Limits: text and each question reported as 32,000 tokens (64,000 per request on one page; Vercel/Cloudflare list 32,000). Text only. **English is currently best.** Rate limits 1,200 requests/min. | confirmed on one secondary page; sources conflict on the context size | drawpie |
| **New signups on TypeSafe's console were paused on 22 Sep 2026.** Existing accounts work. Whether the third-party routes admit new users is unverified. | confirmed (one page, dated 22 Sep) | drawpie |
| Accuracy: 96.47% on the IMDb test set (about the same as ModernBERT with little tuning, about 95%). The author does not know whether IMDb was in its training data. TypeSafe's own benchmark: about 67% on four internal datasets, matching mid-tier LLMs at about $0.0007 per example; labels came from other LLMs; no public benchmark. | confirmed as reported; independent verification: none | Raschka, The Batch |
| Calibration: the docs call outputs "well-calibrated", but Raschka reports no calibration metrics. The `confidence` field measures how concentrated the distribution is, not the winner's probability. | confirmed (claim only; no evidence) | Raschka |
| An academic analysis exists: "Jev in the Wild" (arXiv 2609.30216). I could not read the PDF text this session. | unknown (content not read) | [arXiv](https://arxiv.org/pdf/2609.30216) |

**Did I run it? No.** It is hosted and there is no Northvaine account, key or public weights.
Running it would also send candidate text, including quotes from fetched pages, to a new third
party that is not Nebius; that needs a founder decision (new vendor, data leaving the stack, no
sending-of-data rule in CLAUDE.md covers it explicitly). I ran the **closest open, runnable
equivalents** instead: a frozen sentence-embedding plus logistic regression, SetFit, and a small
NLI zero-shot model (below).

**Other names it could be (considered).** GLiClass (an open zero-shot classifier family from
Knowledgator, **Apache-2.0**, small variant about 144M parameters, English, runs on CPU with
`pip install gliclass`: confirmed on the [model card](https://huggingface.co/knowledgator/gliclass-small-v1.0))
is the nearest open analogue to Jev's "pick a label with no training" design. SetFit and GEV/JEPA
are phonetic or architectural neighbours but not classification products by that name. I judge
**Jev (TypeSafe)** the most likely meaning (inferred: it is the only classification model
named Jev, and it is the subject of a September 2026 wave of coverage), and GLiClass the most
useful open alternative. If the founder meant something else, we need the name's source.

### Fit of Jev for our tasks (all inferred, since not tested)

| Task | Fit | Why |
|---|---|---|
| Buyer-vs-seller gate | Possible, not better | It replaces a prompt with a typed Choice question and gives probabilities and a stable schema, which would be cheaper and faster than Nemotron. But the gate needs `cited_refs`, reasons and a "direct buyer" explanation that downstream code and the brief use; Jev returns labels, not reasons. Zero-shot, it is no more accurate than a mid-tier LLM by TypeSafe's own numbers (about 67% on its hard sets). |
| Relevance pre-filter | Best fit | A yes/no Noul question per candidate at $0.042/M input is a cheap triage. Recall at the 95% mark still needs measuring; with 91% of candidates passing, there is little to filter (see results). |
| Event-type classification | Good fit | A Choice question over our fixed event concepts, English text. Needs a check on tender text in other languages (English is its best language). |
| Learning from owner ratings | Poor fit | Closed API, no fine-tuning found: it cannot learn from our labels. It could only be prompted with them as context. |
| Platform risks | Material | New vendor, signups paused, no open weights or licence found, data leaves the Nebius/NVIDIA stack. That also weakens the hackathon story (Nemotron on Token Factory). |

Verdict on JEV: **interesting, but not for the hackathon build.** Revisit as a cheap triage and
event-typing option after the hackathon, when signups are open and the licence and data-handling
terms are readable. Do not depend on it.

## Alternatives compared

Status marks apply to the facts in the table; "recalled" licences and sizes should be re-checked
at the model card before adopting anything.

| Option | Labels needed | Cost | Speed | Accuracy expectation | Calibration | Multilingual | Hosting |
|---|---|---|---|---|---|---|---|
| Embeddings + logistic regression | Tens per class to start; hundreds for reliable | Near zero after a one-off embed (MiniLM is 22M parameters, recalled) | Milliseconds per item on CPU | Good on topic-like labels, weak on subtle ones (measured below: no gain over majority at n=98) | Reasonable after Platt or isotonic scaling, which needs more rows than we have | Only if the encoder is multilingual (for example multilingual-e5, recalled) | Our own process, CPU |
| TF-IDF + logistic regression | Same | Zero | Microseconds | Measured below | Reasonable, needs scaling | Needs per-language text | Our process |
| SetFit | 8 to 16 per class is the design goal (recalled); we have 9 negatives in total | A few minutes of CPU per fit | Same as embeddings at inference | Strong in few-shot papers on topic tasks; measured below | Head is logistic regression, so scaling needed | Via a multilingual encoder | Our process |
| ModernBERT / DeBERTa-v3 fine-tune | Hundreds to thousands | GPU minutes (Raschka: 23 min on a DGX Spark for IMDb); CPU is slow | Fast on GPU, tolerable on CPU | Best of the small models given enough labels (about 95% on IMDb with little tuning: confirmed via Raschka) | Needs temperature scaling | English for ModernBERT and DeBERTa-v3; mDeBERTa for multilingual (recalled) | Our GPU, or Nebius serverless job |
| GLiClass (GLiNER-style zero-shot) | None (labels are text); a few dozen to calibrate a threshold | Zero per call; 144M parameters (confirmed for `small-v1.0`) | One forward pass, CPU-feasible | Unknown for buyer vs seller; no number found for our task | Scores are not calibrated probabilities (inferred); tune a threshold | English (confirmed for `small-v1.0`) | Our process; Apache-2.0 (confirmed) |
| NLI zero-shot (DeBERTa-v3 xsmall) | None | Zero per call; 70.8M parameters (confirmed), MIT (confirmed) | One pass per label per item | Measured below | Poor: an NLI entailment score is not our probability | English only (confirmed) | Our process |
| Nemotron prompting (today's gate) | None to start, few-shot optional | About $0.0009 per call on the mid model (inferred from plan tokens and `pricing.json`) | Seconds per call | The reference we measure against; by design the strictest reasoner we have | Not a probability; no calibration | Strong | Nebius Token Factory |
| Jev (TypeSafe) | None (prompted by question) | $0.042 per million input tokens (secondary sources) | Raschka: 25,000 reviews in 22 minutes, about 19 per second | 96.5% on IMDb (possible contamination); about 67% on vendor's hard sets | Claims "well-calibrated"; no evidence | English best | Vendor API only; signups paused |

## Data and method

- **Source.** The three recorded runs, replayed offline through `scripts/radar.py`
  (`run_replay`), with no network. Recordings and client fixtures untouched.
- **Rows.** Only gate decisions with `by == "llm"` count. Code rejections are counted apart:
  **41 rows, all `unidentified`** (stone 8, cold-chain 26, packaging 7); they are not labels.
- **Labels (98 rows).** `passed` 89 and `not_a_buyer` 9. **There is not one `competitor`,
  `reseller`, `publisher` or `not_an_organisation` row.** Per client: stone 39 passed / 1 rejected;
  cold-chain 34 / 6; packaging 16 / 2.
- **Text.** Name, roles, stream, claim statements with source quotes, and events: the same
  information the gate prompt sees. A second variant removes the company name.
- **Splits.** Leave-one-client-out (3 folds), 5-fold stratified-by-label, and 5-fold stratified
  grouped by normalised company name.
- **Metrics.** Accuracy and macro-F1 across the labels; precision and recall for `passed`; Brier
  score on P(passed); **pre-filter value**: the share of rows scoring below the threshold that
  keeps 95% (and 99%) of Nemotron-passed rows, which equals the share of gate calls saved.

## Results (pooled out-of-fold predictions; chance-level reference is the majority row)

`Accuracy` is multi-class, `Macro-F1` over the two labels present. `Saved` is the fraction of gate
calls that could be skipped while still sending 95% / 99% of Nemotron-passed rows on to the gate.
The thresholds are picked on the same scores they are scored on, so the 95% column is optimistic.

Leave-one-client-out, company name included:

| Model | Accuracy | Macro-F1 | Passed precision | Passed recall | Brier | Saved at 95% | Saved at 99% |
|---|---|---|---|---|---|---|---|
| Majority ("always passed") | 0.908 | 0.476 | 0.908 | 1.000 | 0.089 | 0.0% | 0.0% |
| TF-IDF + LR | 0.847 | 0.517 | 0.911 | 0.921 | 0.130 | 4.1% | 0.0% |
| MiniLM embedding + LR | 0.867 | 0.464 | 0.904 | 0.955 | 0.110 | 4.1% | 0.0% |

Grouped by company, 5-fold, name included:

| Model | Accuracy | Macro-F1 | Passed precision | Passed recall | Brier | Saved at 95% | Saved at 99% |
|---|---|---|---|---|---|---|---|
| Majority | 0.908 | 0.476 | 0.908 | 1.000 | 0.084 | 0.0% | 0.0% |
| TF-IDF + LR | 0.878 | 0.592 | 0.923 | 0.944 | 0.101 | 6.1% | 0.0% |
| MiniLM embedding + LR | 0.867 | 0.531 | 0.913 | 0.944 | 0.119 | 5.1% | 0.0% |

Stratified 5-fold (company may appear on both sides), name included: TF-IDF + LR accuracy 0.888,
macro-F1 0.603, Brier 0.111, saved 6.1% at 95%; embedding + LR 0.867, 0.531, 0.119, 5.1%.
With the name removed the picture is the same: LOCO TF-IDF 0.837 / 0.456, embedding 0.878 / 0.467;
grouped TF-IDF 0.878 / 0.592, embedding 0.888 / 0.547. Every Brier score is **worse than the
majority baseline's** (0.084 to 0.089 against 0.10 to 0.13).

SETFIT_AND_ZEROSHOT

## Reading the numbers honestly

- **Agreement is not accuracy.** These rows are Nemotron's decisions, not ground truth. The
  question measured is "can a cheap model reproduce Nemotron", not "is it right".
- **The task is almost trivial on this data.** With 91% passed, the majority class wins. The
  macro-F1 differences (0.46 to 0.60) come from a handful of the 9 negatives, so they are noise:
  one negative moved changes macro-F1 by several points. I would not rank the models.
- **The negatives are not the hard cases.** Nemotron rejected only `not_a_buyer`. The
  competitor, reseller and publisher cases that the gate exists for (CLAUDE.md rule 3) do not occur
  in these recordings, so we have **no evidence at all** about them. Those would be the cases a
  pre-filter must never drop.
- **Pre-filter value is tiny because the funnel already filtered.** `build_candidates` and the
  upstream discovery have already removed most of the junk before the gate sees anything; 41 of
  139 candidates (29%) were removed by code, and the gate then passes 91% of the rest.
- **Leakage.** The same company could appear in several clients, and a name carries a lot of
  signal. I checked: **no company name appears in more than one client, and no name repeats in
  the dataset**, so the grouped split equals the plain split here, and leave-one-client-out is the
  honest test. Leakage of another kind remains: candidates from one source site, or one run, share
  wording, so fold scores are still optimistic. The name-removed variant tests whether the name
  alone is doing the work; it does not change the conclusion.
- **Small sample.** With 98 rows and 9 minority rows, a 95% confidence interval on any rate
  is wide (a recall of 0.944 on 89 positives is about 0.88 to 0.98).
- **Thresholds are tuned on the test scores** (see above), so the "saved" figures are upper
  bounds. The 99% column is the one to trust, and it is 0%.

## Recommendation

**Pre-filter: not now. Revisit after about 500 real gate decisions that include the other
verdicts.** Reasons: nothing to save at the safe threshold, a negligible saving even at the
optimistic one, and a classifier that can silently drop a real buyer is worse than a sub-cent call.
The recorded gate is "one mid-tier call per candidate", not a bottleneck.

**What a reliable version needs**
- Labels: Nemotron's own decisions from live runs are free, so volume is cheap. For a
  pre-filter that only removes candidates, at least **500 to 1,000 decisions**, with **at least 50
  per rejection class** (competitor, reseller, publisher, not an organisation), pooled across many
  clients, because rare classes do not exist in a three-client sample.
- To trust a 99% recall target you need on the order of **300 or more passed rows in the held-out
  set** (a 99% recall estimate from 89 positives has an interval wider than the margin).
- **Spot-check**: send a random 5 to 10% of "skipped" candidates to Nemotron anyway and track the
  disagreements. If one passed candidate is dropped, tighten the threshold.
- A fixed threshold, chosen on a validation set from other clients, not on the test scores.

**Where it would plug in** (a describe-only change; `northvaine/` is untouched by this ticket)
- In `northvaine/radar/run.py`, between `build_candidates` and `gate_candidate`: for each
  candidate compute `score = triage(candidate)`; candidates under the threshold become a
  `RejectedEntry` with `gate.by = "code"` (new reason "triage") and **never an LLM verdict
  invented by the classifier** (rule 3: the gate comes first; rule 8: LLM calls through
  `llm.py`). Skipped candidates are still saved with their score, so they can be audited and so
  the classifier can later be scored against Nemotron's verdicts on the sampled spot-check.
- Behind a setting (`radar_triage_threshold`, off by default), with the model file as data, and with
  the feature text built by the same function that builds the gate's claim lines
  (`claim_lines`), so it is trained on exactly what the gate sees. The classifier is generic: no
  industry words in code (rule 1).

**In the learning loop (owner-feedback classifier)**
- This is the better use. `docs/research/learning_loop_design.md` maps owner ratings to
  labels; a small model (embedding + regularised logistic regression, one per workspace, with a
  shared prior across workspaces) would predict "owner will like this" to order and surface the
  brief. That needs real ratings, which come in tens, not thousands, per owner. Start with the
  logistic regression on a handful of hand-built features and add the text embedding only after
  roughly **100 ratings per workspace**. Below that, use the pooled model and a posterior with wide
  uncertainty, not a point estimate.
- Calibrate with isotonic or Platt scaling once there are about 200 ratings pooled; report Brier
  against the "always the base rate" baseline, as above; do not show a score to an owner that is
  not beating that baseline.
- Never train a classifier on Nemotron verdicts and then use its output to teach the gate's
  prompt: that is a loop that amplifies Nemotron's own errors.

**On Jev and GLiClass specifically**: do not integrate Jev now (closed, signups paused, data
leaves the stack, licence unknown). Do keep GLiClass or the NLI zero-shot as the first thing to
try when we need label-free triage, since both run locally on CPU under permissive licences.

## What this does not tell us

Whether any of these models could separate competitors, resellers and publishers from buyers.
Whether performance holds in other languages (all three recorded clients are largely English
sources). How Jev behaves on our task, since we did not run it.
