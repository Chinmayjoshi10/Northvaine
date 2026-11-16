"""One real "Build my radar" on the live site, the way a judge would do it (17 Nov).

Starts a session, waits for the website read and the proposed answers, confirms the answers in
`scripts/synthetic/answers.json`, waits for the radar and checks that it opens. Exit code 0 when the
radar finished and opens, 1 otherwise, so a scheduled workflow fails (and notifies) when the demo
would fail a judge. Uses only the public API; no keys. Each run uses one free radar (a fresh
example.com address), about one model-dollar-tenth and a few dozen search credits.

    uv run python scripts/synthetic_check.py [--base https://northvaine.onrender.com]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ANSWERS = Path(__file__).resolve().parent / "synthetic" / "answers.json"


def log(*parts: object) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def wait(client: httpx.Client, url: str, stages: tuple[str, ...], every: int, limit: int) -> dict:
    started, last = time.time(), None
    while time.time() - started < limit:
        try:
            session = client.get(url).json()
        except (httpx.HTTPError, ValueError) as exc:
            log("poll failed:", type(exc).__name__)
            time.sleep(every)
            continue
        now = (session.get("stage"), session.get("progress"))
        if now != last:
            log(*now)
            last = now
        if session.get("stage") in stages:
            return session
        time.sleep(every)
    raise TimeoutError(f"no {stages} after {limit} s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base", default="https://northvaine.onrender.com")
    args = parser.parse_args(argv)
    api = args.base.rstrip("/") + "/api/onboarding"
    answers = json.loads(ANSWERS.read_text(encoding="utf-8"))
    with httpx.Client(timeout=90) as client:
        client.get(args.base.rstrip("/") + "/health")  # wake the free server
        start = {
            "company": answers["company"],
            "website": answers["website"],
            "email": f"synthetic-{int(time.time())}@example.com",
        }
        response = client.post(api, json=start)
        if response.status_code != 201:
            log("start refused:", response.status_code, response.text[:200])
            return 1
        sid = response.json()["id"]
        log("session", sid)
        try:
            wait(client, f"{api}/{sid}", ("ready", "failed"), 5, 300)
            client.post(f"{api}/{sid}/propose")
            wait(client, f"{api}/{sid}", ("proposed", "failed"), 5, 600)
            confirmed = client.post(f"{api}/{sid}/answers", json=answers)
            if confirmed.status_code != 200:
                log("answers refused:", confirmed.status_code, confirmed.text[:200])
                return 1
            done = wait(client, f"{api}/{sid}", ("done", "failed"), 30, 60 * 60)
        except TimeoutError as exc:
            log("timed out:", exc)
            return 1
        if done.get("stage") != "done":
            log("the radar failed:", done.get("error"))
            return 1
        radar = client.get(f"{args.base.rstrip('/')}/api/clients/{done['client_id']}/runs/latest")
        if radar.status_code != 200:
            log("the radar does not open:", radar.status_code)
            return 1
        view = radar.json()
        log("radar opens:", len(view.get("accounts", [])), "leads,", view.get("coverage"))
        return 0


if __name__ == "__main__":
    sys.exit(main())
