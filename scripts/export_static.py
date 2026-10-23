"""Export the demo pages' GET endpoints as static JSON for GitHub Pages.

  uv run python scripts/export_static.py --reports demo_reports/radar --out site_data \
      [--clients-dir deploy/demo/clients]

The app is called in-process (no server, no network) with the reports folder overridden the same
way the tests do it, so each file holds exactly what the API would serve. File paths follow
`static_file()`; the frontend (frontend/src/api.ts `staticPath`) builds the same paths, and the
nightly workflow copies the output to `<site>/data/`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def static_file(api_path: str) -> str:
    """`/api/clients/c/runs/latest` -> `api/clients/c/runs/latest.json`.

    Feedback takes its day in the path: `/api/clients/c/feedback?as_of=D` -> `.../feedback/D.json`.
    """
    path, _, query = api_path.partition("?")
    if query.startswith("as_of="):
        path = f"{path}/{query[len('as_of=') :]}"
    return path.lstrip("/") + ".json"


def endpoints(base: Path, client: str) -> list[str]:
    """The API paths the demo pages request for one client."""
    from northvaine.api import store

    paths = [f"/api/clients/{client}/business", f"/api/clients/{client}/learning"]
    days = store.run_days(base, client)  # newest first
    for day in days:
        run, _ = store.load_run(base, client, day)
        paths.append(f"/api/clients/{client}/feedback?as_of={day}")
        for alias in (day, "latest") if day == days[0] else (day,):
            paths.append(f"/api/clients/{client}/runs/{alias}")
            paths += [f"/api/clients/{client}/runs/{alias}/entries/{e.rank}" for e in run.entries]
    return paths


def export(reports: Path, out: Path) -> list[str]:
    """Write every file; returns the written file paths (relative to `out`)."""
    from fastapi.testclient import TestClient

    from northvaine.api import store
    from northvaine.api.feedback import reports as reports_dep
    from northvaine.api.main import app

    app.dependency_overrides[reports_dep] = lambda: reports
    written: list[str] = []
    try:
        http = TestClient(app)
        wanted = ["/api/clients"]
        for client in store.client_ids(reports):
            if store.run_days(reports, client):
                wanted += endpoints(reports, client)
        for api_path in wanted:
            response = http.get(api_path)
            if response.status_code == 404:  # e.g. a business profile that is not on file
                continue
            response.raise_for_status()
            target = out / static_file(api_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(response.json()), encoding="utf-8")
            written.append(static_file(api_path))
    finally:
        app.dependency_overrides.pop(reports_dep, None)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--clients-dir", help="where client spec files live (business page)")
    args = parser.parse_args(argv)
    if args.clients_dir:
        os.environ["RADAR_CLIENTS_DIR"] = args.clients_dir
        from northvaine.core.settings import get_settings

        get_settings.cache_clear()
    written = export(args.reports.resolve(), args.out)
    if not any(w.endswith("/clients.json") for w in written) or len(written) < 2:
        print("nothing exported: no runs found", file=sys.stderr)
        return 1
    print(f"exported {len(written)} files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
