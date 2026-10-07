# How Northvaine is evaluated

Four levels, from "is it true?" to "does it make money?". Each level has a test, a number and a
place where it runs.

## Level 1: truth (automatic, on every commit)
Is every fact true to its source, is every sentence cited, and does nothing private leak?
- **How it is checked:** the gate (`tasks.py gate`) runs the unit, replay and golden tests on
  the real recorded runs of every sample client:
  - every brief fact traces to a verified claim whose quote is in its document;
  - every model-written sentence cites real claims, and its numbers appear in a quote;
  - no email, phone, key or withheld person appears;
  - nothing is dated after the run;
  - replays are byte-identical.
- **Target:** zero violations. Any violation fails the commit.

## Level 2: component accuracy (known-answer sets)
Do individual steps decide correctly?
- **Quote check:** `tests/golden/quote_check.json` (precision and recall printed by
  `tasks.py golden`). Target: precision 1.0, with known gaps listed.
- **Radar ranges:** `tests/golden/radar_expectations.json` sets loose bounds on documents,
  entries and rejections per client, so a change that silently halves the output is caught.
- **Next:** a labelled gate set. Each founder or rep rating ("relevant" yes/no, "wrong
  rejection") becomes a labelled example. Gate precision and recall are then tracked per release
  by replaying recorded runs against the labels.

## Level 3: brief quality (human ratings), with `tasks.py eval`
Would a salesperson act on it?
- **How it is collected:** the founder fills `scorecard.md` next to each brief. For each full
  entry they mark yes or no on **correct**, **relevant**, **new or worth acting on**
  (for the founder's own business: previously unknown; for other clients: would a salesperson in
  that industry act on this?) and **actionable**, plus a failure chip when the answer is no. They
  then check the rejected list.
- **How it is measured:** `uv run python scripts/tasks.py eval` reads the latest scorecard per
  client and writes `reports/eval/<date>/eval.md` (never committed). It reports the rate of each
  question, entries rated yes on all four, the wrong-rejection rate, and the most common failure,
  which tells us which step to fix first.
- **Quality gate (from M5):** at least 2 entries rated yes on all four, and at most 1 in 3 of
  the checked rejections wrong.

## Level 4: outcomes (the salesperson, after contact)
Does it create action and revenue?
- **How it is collected:** the "After contact" table in the scorecard records, per account
  approached:
  - known already?
  - new intelligence (a date, project, signal, route or reason to act)?
  - contacted?
  - outcome: none, redirect, info request, requirement, sample, quote, meeting, won.
- **How it is measured:** `tasks.py eval` reports the known rate, the new-intelligence rate,
  **leads acted on**, the response rate and the positive-outcome rate.
- **Targets:**
  - Gate 1 (ROADMAP): at least 1 lead acted on per brief on average.
  - Gate 2: retention and cost per useful lead.
- **This is the real proof.** It also becomes the learning data (D79): real outcomes replace the
  simulated owner.

## Head-to-head benchmark (manual)
For the same company and the same week, compare Northvaine's brief with manual research (for
example ChatGPT plus a person). Count verified, new and actionable leads for each. Northvaine
should be at least equal before it is sold, and better before it is called better.

## Learning (once the learners exist)
Replay past months point-in-time (`available_at` prevents leakage). A learned strategy version
goes live only if it ranks real later outcomes at least as well as the current one: award
winners from public history first, then real feedback. Every learned change can be rolled back.
