"""Import owner feedback for one saved run into `feedback` (D95), so learning can use it.

The web app writes each answer to reports/feedback/<client>.jsonl. The run must have been saved
first (`radar.py ... --save`). Idempotent: an answer already imported is skipped. No model call.

    uv run python scripts/import_feedback.py --client stone_supplier --as-of 2026-10-08
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from northvaine.api import store  # noqa: E402
from northvaine.radar.labels import cases_for_run, import_feedback  # noqa: E402


async def _run(client: str, as_of: str) -> int:
    from sqlalchemy import text

    from northvaine.core.db import session_scope

    base = store.reports_dir()
    run, _ = store.load_run(base, client, as_of)
    records = [r for r in store.read_feedback(base, client) if r.get("as_of") == as_of]
    async with session_scope() as session:
        found = await session.execute(
            text("SELECT id FROM workspaces WHERE name = :n ORDER BY created_at LIMIT 1"),
            {"n": client},
        )
        workspace_id = found.scalar_one_or_none()
        if workspace_id is None:
            print(f"no saved runs for {client!r}: run radar.py with --save first", file=sys.stderr)
            return 1
        cases = await cases_for_run(session, workspace_id, run)
        written = await import_feedback(session, records, cases)
    print(f"{len(records)} answer(s) read, {written} new label(s) written, {len(cases)} case(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="import_feedback.py")
    parser.add_argument("--client", required=True)
    parser.add_argument("--as-of", required=True, help="the run's date, YYYY-MM-DD")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.client, args.as_of))


if __name__ == "__main__":
    raise SystemExit(main())
