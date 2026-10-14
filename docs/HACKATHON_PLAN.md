# Northvaine — hackathon plan (13 Oct → 30 Oct 2026)

The short-range plan to submission. The long-range phases are in `docs/ROADMAP.md`.

Deadline: **30 Oct, 10:00 PT**. Target: **submit 29 Oct**, everything built by **23 Oct**.
Assumes 1–2 Claude sessions a day (one per usage window). At one a day, everything shifts about
three days later and still fits.

## Where we are (13 Oct)

| Done | Not done |
|---|---|
| Radar engine: find → buyer-or-seller gate → verify quotes → skeptic → brief | Landing page |
| Account roles, evidence levels, company fit (D94–D96) | Onboarding ("Build my radar") |
| Graph of who did what, served by the API (D88, D97) | Nightly run on a schedule |
| Learning loop v0, outcome labels (D89, D95) | Public site and repo |
| **The Morning** prototype on real data | Video |
| Nemotron via Token Factory at runtime; Tavily; TED, World Bank, USAspending | Gateway (proposed cut) |

## The plan

| Dates | What gets built | You |
|---|---|---|
| **14–15 Oct** | Morning polished from your feedback. **The case page** in the same style: the full chain, timeline, evidence for and against, next action, feedback. | React to the Morning |
| **16–17 Oct** | **Landing page: the night.** A real recorded run replayed in the dark: documents arrive, noise falls away, chains lock. **Dawn** transition into the Morning. | React to the landing |
| **18–19 Oct** | **Onboarding: "Build my radar".** Paste a website → Northvaine reads it and proposes what you sell, markets and search terms, each with a quote from the site → you correct → it runs. | Try it on your own site |
| **20 Oct** | **Nightly run** on a schedule, and "what changed since yesterday" on the Morning (new, moved forward, closed). | — |
| **21–22 Oct** | **Go public for free:** `publish` task (run → build → static site on a free host), secrets scan of git history, README refresh with the honest status and the feedback section on Nebius, Token Factory and NVIDIA. | Create the GitHub repo, rotate the Neon password, choose the free host |
| **23 Oct** | Full demo path, start to finish: landing → onboarding → Morning → case. Fix what breaks. | Walk through it once |
| **24–26 Oct** | Spare: polish and fixes. Video script and a demo path that cannot fail. | — |
| **27–28 Oct** | **Record the video** (under 3 minutes), upload to YouTube (public). | Record (about 1 hour) |
| **29 Oct** | **Submit.** Check the list below one last time. | Submit |

## Revised plan (15 Oct): judged to win, two prizes

**Prizes:**
- **Best Apps and Agents** track, first prize **USD 20k** ("useful applications and agents
  powered by Nemotron models through Token Factory").
- **Best use of Tavily**, **USD 3k**.
- 23,243 registered participants (many register, far fewer submit).

**Judging** (Devpost rules, read through a participant digest and the Amsterdam kickoff recap;
the rules page blocks automated reading, so confirm once by hand):
- **Stage 1, pass/fail:** real fit with the track and real use of NVIDIA models on Nebius. A
  superficial rebrand fails. We pass: Nemotron on Token Factory makes every buyer decision and
  skeptic review.
- **Stage 2, four criteria, equal weight:**

| Criterion | Where we stand (15 Oct) | What wins it |
|---|---|---|
| Technological implementation | Strong: code-checked quotes, caps, replays, 1,600+ tests | Agent trace on screen: Nemotron decides, the skeptic argues, code verifies, Tavily checks |
| Design: a complete, coherent product | **Weakest:** 2 of 11 designed screens, no onboarding, landing not in the app | One polished journey with no dead ends; unbuilt screens hidden or marked as roadmap |
| Potential impact | Strong: a real exporter, real importers, the field-test comparison | Real result in the video's first 30 seconds |
| Quality of the idea | Strong: who really buys, import records, proof-only facts | "It saw this buyer coming three months early" (time machine) |

- **Judging runs into December:** the demo URL must stay up and never show an empty screen.

**Tavily as a showcase** (confirm features in Tavily's docs before building; never guess):
- Onboarding reads the client's own site through Tavily and proposes the radar, each item quoted.
- Company fit for every proven buyer: Tavily finds and reads the importer's own site (stockist or
  haulier?). The before/after count goes in the README.
- Why-now news per shortlisted company, verified against the page.
- The case shows the Tavily trace ("found the site → read 3 pages → names the product").

**Order from 15 Oct** (about 10-12 sessions; buyer-intent steps 2-4 wait unless time frees up):

| # | Work | Founder |
|---|---|---|
| 1 | Step 1b: Companies House check (status, age, activity code; ownership and name changes) and daily-edition labels | Regenerate the Companies House keys |
| 2 | Onboarding "Build my radar", powered by Tavily | Try it on your own site |
| 3 | Landing page inside the app, wired to onboarding | React to it |
| 4 | Station and the full case page to the locked design: Overnight, accounts to work, stage bar, history, Tavily and agent trace | React to it |
| 5 | Merge Connections; hide or mark the other sidebar screens | — |
| 6 | Time-machine backtest for "it saw it coming" (real run, never staged) | — |
| 7 | Nightly run; public hosting that stays up through December; secrets scan; README with "How we use Nemotron, Token Factory and Tavily" and the feedback section | GitHub repo, rotate Neon password, pick the host |
| 8 | Full demo walk-through and fixes | Walk it once |
| 9 | Video under 3 minutes (script below), upload | Record (about 1 hour) |
| 10 | Submit 29 Oct | Submit |

**Video (3:00):** problem (0:00) → landing, the night run (0:20) → Station and a real importer
case with sources (0:35) → "it saw it coming" (1:20) → onboarding on a different industry
(1:50) → agents, Nemotron, Token Factory, Tavily, every fact checked (2:20) → learning toast,
roadmap from the design images, the promise (2:40).

**Ask before publishing:** may the field-test case appear in a public video? Importers are
public records; the client stays anonymous unless the founder agrees.

## Submission checklist

- [x] Runtime calls to Nemotron on Nebius Token Factory
- [x] Licence file in the repo
- [ ] Public repo, licence shown in the GitHub About section
- [ ] README: what it does, setup, where Nemotron, Token Factory and Tavily are used (with Tavily numbers)
- [ ] Devpost: feature description, selected track, testing instructions; demo up through December
- [ ] Working public demo URL
- [ ] Public YouTube video, under 3 minutes
- [ ] Feedback section on Token Factory, Nebius and NVIDIA tools
- [ ] No secrets, personal data or real contacts in the repo or its history

## If time runs short, cut in this order

1. Gateway (already proposed out)
2. "What changed since yesterday"
3. The dawn animation (a plain transition instead)

The demo path — landing → onboarding → Station → case — is never cut. Buyer-intent steps 2-4
and the extra sidebar screens are cut before any of it.

## After the hackathon: first client

- Runs on your laptop at 6am; results published as a free static site. Cost: about $5–15/month
  in AI and search usage, no server.
- Charge client #1 (setup fee + monthly). That pays for one shared server (~$40–76/month) from
  client #2 onward.
