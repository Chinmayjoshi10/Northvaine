# Free public hosting

The Nebius plan in `docs/DEPLOY.md` stays. This is the free route for a public demo.

## Design

Three free pieces:

1. **Pages (static, nightly).** The demo pages judges browse (landing, Station, leads, case page,
   connections, motion, business) are a static site on GitHub Pages: instant, never asleep.
   A nightly workflow (`.github/workflows/nightly.yml`, 02:30 UTC) runs the radar live for ONE
   public demo client, `stone_exporter_demo`, then `scripts/export_static.py` calls the API
   in-process and writes the exact JSON it serves (clients, runs and the `latest` alias, entries,
   feedback, learning, business) to files. The frontend is built with `VITE_STATIC_DATA=1`,
   `VITE_LIVE_API=https://northvaine.onrender.com` and `VITE_BASE=/Northvaine/`, the JSON is
   copied to `<site>/data/`, and the result is deployed with `actions/deploy-pages`.
   If the radar run fails, nothing deploys and yesterday's site stays.
2. **Render (live API, free, sleeps).** One free Docker web service built from `main`
   (`https://northvaine.onrender.com`, the root `Dockerfile`) serves only the live parts:
   onboarding ("Build my radar"), contact and feedback. It sleeps after 15 minutes idle and takes
   up to about a minute to wake; the onboarding page says so and pings `/health` first.
   Set `CORS_ORIGINS=["https://<github user>.github.io"]` on it so the static site may call it.
3. **Neon demo project (database).** Every live model call writes a ledger row (budget checks),
   so the workflow and Render need `DATABASE_URL`. Use a database that holds nothing private.

A client built after the last nightly run is not in the exported files; the static site falls
back to the live API for it.

The demo client is anonymised: id `stone_exporter_demo`, generic name, no existing customers.

## One-time setup (founder, in order)

```
gh auth login
uv run python scripts/gh_secrets.py --repo OWNER/REPO
uv run python scripts/make_demo_spec.py --source <private spec.json> \
    --out deploy/demo/clients/stone_exporter_demo.json --forbid <word> --forbid <word>
```

Read the demo spec by eye, then commit and push it.

Then, once: repo **Settings -> Pages -> Source: GitHub Actions**. Run the workflow by hand
(Actions, Nightly demo, Run workflow; or `gh workflow run nightly.yml`). The site appears at
`https://<github user>.github.io/Northvaine/` (change `VITE_BASE` in the workflow if the repo is
named differently).

On Render set the same runtime secrets as the workflow (see `.env.example`), `DAILY_BUDGET_USD=2`
and `CORS_ORIGINS` as above.

## Cost

Hosting is $0 (Pages, Render free, Neon free). About $0.35 per nightly run (Nebius model calls
and Tavily).

## Safety

- Render has a daily budget cap (`DAILY_BUDGET_USD`, $2) and the lifetime cap `TOTAL_BUDGET_USD`.
- Onboarding live runs are public: anyone can start one, up to the cap.
- The exported JSON is the same output the public API serves; nothing else is published.
- The onboarding folder on Render is ephemeral.

## Later: an always-on host

The same Docker image runs on any paid always-on host (the Nebius plan in `docs/DEPLOY.md`, or a
paid Render instance). Then drop `VITE_STATIC_DATA` and `VITE_LIVE_API`: the frontend is served
by the API itself, same-origin, as it is in local development.

## Not used: Hugging Face Space

Docker Spaces now need a paid plan. `scripts/hf_space.py` and `deploy/hf_space/` stay in the repo
but are unused, and the workflow no longer pushes to the container registry or restarts a Space.
