# Free public hosting

The Nebius plan in `docs/DEPLOY.md` stays. This is the free route for a public demo.

## Design

1. A nightly GitHub Actions workflow (`.github/workflows/nightly.yml`, 02:30 UTC) runs the radar
   live for ONE public demo client, `stone_exporter_demo`, builds the Docker image with that
   fresh brief baked in (`demo_reports/radar`), pushes it to GHCR
   (`ghcr.io/<owner>/northvaine:latest` plus a date tag), then restarts the Hugging Face Space.
2. The Space (Docker SDK) holds a two-line Dockerfile that is `FROM` that image, and a README
   with the Space front-matter (`deploy/hf_space/`). Runtime secrets live in the Space settings.
3. The demo client is anonymised: id `stone_exporter_demo`, generic name, no existing customers.
4. If the radar run fails, the workflow stops and yesterday's image stays live. Each image
   carries only tonight's run.

## One-time setup (founder, in order)

```
gh auth login
uv run python scripts/gh_secrets.py --repo OWNER/REPO
uv run python scripts/make_demo_spec.py --source <private spec.json> \
    --out deploy/demo/clients/stone_exporter_demo.json --forbid <word> --forbid <word>
```

Read the demo spec by eye, then commit and push it. Put a Hugging Face write token in `.env` as
`HF_TOKEN=` and the Space name as `HF_SPACE=user/northvaine` (names only in `.env.example`); run
`gh_secrets.py` again if you added them after the first run.

```
uv run python scripts/hf_space.py init --space user/northvaine --owner <github owner>
uv run python scripts/hf_space.py secrets --space user/northvaine
```

Then make the GHCR package public (GitHub: your profile, Packages, northvaine, Package settings,
Change visibility) after the first push, and run the workflow once by hand (Actions, Nightly
demo, Run workflow; or `gh workflow run nightly.yml`). The first run has to finish before the
package exists.

## Cost

About $0.35 per nightly run (Nebius model calls and Tavily). The Space and GHCR are free.

## Safety

- The Space has a daily budget cap (`DAILY_BUDGET_USD`, 2 unless `.env` has a lower value) and
  the lifetime cap `TOTAL_BUDGET_USD`.
- The onboarding live run on the Space is public: anyone can start one, up to the cap.
- `DATABASE_URL` is needed by the workflow and the Space because every live model call writes a
  ledger row (budget checks). Use a database that holds nothing private.
- The onboarding folder on the Space is ephemeral.
