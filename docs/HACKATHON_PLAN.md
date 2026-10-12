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

## Submission checklist

- [x] Runtime calls to Nemotron on Nebius Token Factory
- [x] Licence file in the repo
- [ ] Public repo, licence shown in the GitHub About section
- [ ] README: what it does, setup, where Nemotron, Token Factory and Tavily are used
- [ ] Working public demo URL
- [ ] Public YouTube video, under 3 minutes
- [ ] Feedback section on Token Factory, Nebius and NVIDIA tools
- [ ] No secrets, personal data or real contacts in the repo or its history

## If time runs short, cut in this order

1. Gateway (already proposed out)
2. "What changed since yesterday"
3. The dawn animation (a plain transition instead)

The demo path — landing → onboarding → Morning → case — is never cut.

## After the hackathon: first client

- Runs on your laptop at 6am; results published as a free static site. Cost: about $5–15/month
  in AI and search usage, no server.
- Charge client #1 (setup fee + monthly). That pays for one shared server (~$40–76/month) from
  client #2 onward.
