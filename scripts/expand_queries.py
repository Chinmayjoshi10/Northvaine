"""Propose local-language searches and product words for one client (D93). SPENDS MONEY (one
fast-tier call, well under one cent). The proposal goes to reports/proposals/ for a person to
review; the client spec is never changed.

    uv run python scripts/expand_queries.py --client coldchain_maker --targets de:DE,fr:FR --yes
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from northvaine.brain.budget import RunContext  # noqa: E402
from northvaine.radar.expand import expand_queries, parse_targets  # noqa: E402
from northvaine.radar.models import load_client_spec  # noqa: E402


async def _run(client: str, targets: str) -> Path:
    from northvaine.core.db import session_scope

    spec = load_client_spec(client)
    async with session_scope() as session:  # every live call is logged and budgeted
        proposal = await expand_queries(
            spec, parse_targets(targets), run=RunContext(), session=session
        )
    out = ROOT / "reports" / "proposals" / f"{client}_queries.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
    for q in proposal.queries_to_add:
        print(f"query  {','.join(q.countries)}  {q.text}")
    for t in proposal.offer_terms_to_add:
        print(f"term   {t}")
    for d in proposal.dropped:
        print(f"dropped  {d}")
    print(f"cost ${proposal.cost_usd}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="expand_queries.py")
    parser.add_argument("--client", required=True)
    parser.add_argument("--targets", required=True, help="e.g. de:DE,fr:FR")
    parser.add_argument("--yes", action="store_true", help="actually call the model")
    args = parser.parse_args(argv)
    parse_targets(args.targets)  # fail early on a bad target
    if not args.yes:
        print("Nothing was called. Re-run with --yes (one fast-tier call).", file=sys.stderr)
        return 1
    path = asyncio.run(_run(args.client, args.targets))
    print(f"wrote {path}  (a proposal: review it, then copy what you approve into the spec)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
