"""The lead-quality scoreboard (D106): how many buyers found by hand did a radar run find alone?

    uv run python scripts/scoreboard.py --run <reports>/<client>/<date>/run.json --targets <file>

`--targets` is a JSON file kept outside the repo (client names never enter git):

    {"markets": ["GB", "US"],
     "targets": [{"name": "Example Trading", "country": "GB", "aliases": ["EXAMPLE TRADE UK"]}]}

Each target is matched on its name and aliases against the run's entries (briefed) and the gate's
rejections, by the register name key (legal form and punctuation ignored). Two scores: all
targets, and the fair score over targets in the client's markets. No network, no model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from northvaine.sensors.companies_house import name_key

MIN_KEY = 4  # shorter keys match too much by accident


def _keys(target: dict[str, Any]) -> list[str]:
    names = [target["name"], *target.get("aliases", [])]
    return [k for k in (name_key(n) for n in names) if len(k) >= MIN_KEY]


def _matches(keys: list[str], company: str) -> bool:
    found = name_key(company)
    return len(found) >= MIN_KEY and any(k in found or found in k for k in keys)


def _company(record: dict[str, Any]) -> str:
    candidate = record.get("candidate", {})
    return str(candidate.get("name") or "")


def score(run: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    markets = {m.upper() for m in targets.get("markets", [])}
    rows = []
    for target in targets["targets"]:
        keys = _keys(target)
        status, detail = "missed", ""
        for entry in run.get("entries", []):
            if _matches(keys, _company(entry)):
                status, detail = "briefed", f"rank {entry.get('rank')}: {_company(entry)}"
                break
        else:
            for rejected in run.get("rejected", []):
                if _matches(keys, _company(rejected)):
                    gate = rejected.get("gate", {})
                    status = "rejected"
                    detail = f"{_company(rejected)}: {gate.get('rejected_as')}"
                    break
        country = str(target.get("country", "")).upper()
        rows.append(
            {
                "name": target["name"],
                "country": country,
                "in_market": not markets or country in markets,
                "status": status,
                "detail": detail,
            }
        )
    in_market = [r for r in rows if r["in_market"]]
    return {
        "found": sum(r["status"] == "briefed" for r in rows),
        "total": len(rows),
        "found_in_market": sum(r["status"] == "briefed" for r in in_market),
        "total_in_market": len(in_market),
        "rows": rows,
    }


def render(result: dict[str, Any]) -> str:
    lines = [
        f"Found {result['found']} of {result['total']} hand-found buyers; "
        f"{result['found_in_market']} of {result['total_in_market']} in the client's markets.",
        "",
        "| Buyer | Country | In markets | Result | Detail |",
        "|---|---|---|---|---|",
    ]
    order = {"briefed": 0, "rejected": 1, "missed": 2}
    for r in sorted(result["rows"], key=lambda r: (order[r["status"]], not r["in_market"])):
        lines.append(
            f"| {r['name']} | {r['country']} | {'yes' if r['in_market'] else 'no'} "
            f"| {r['status']} | {r['detail']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--targets", required=True, type=Path)
    args = parser.parse_args(argv)
    run = json.loads(args.run.read_text(encoding="utf-8"))
    targets = json.loads(args.targets.read_text(encoding="utf-8"))
    print(render(score(run, targets)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
