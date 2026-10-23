"""Make a radar report safe to publish as the public demo.

Drops every entry and rejection that mentions a forbidden word (the anonymised client's own
group and customers; the list is private and arrives through an environment variable, never in
the repo), removes company contact details, and fails if any forbidden word, email address or
phone number is still left anywhere in the report.

    uv run python scripts/sanitize_demo_report.py demo_reports/radar --forbid-env DEMO_FORBID

DEMO_FORBID holds the words separated by ";". Rewrites each run.json in place; prints counts only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_sensor_fixtures import find_pii  # the recorder's own contact check


def _mentions(obj: Any, words: list[str]) -> bool:
    return any(w in json.dumps(obj, ensure_ascii=False).casefold() for w in words)


def sanitize(report: dict[str, Any], words: list[str]) -> tuple[dict[str, Any], int]:
    """The report without entries or rejections naming a forbidden word, contacts removed."""
    dropped = 0
    for field in ("entries", "rejected"):
        items = report.get(field) or []
        kept = [item for item in items if not _mentions(item, words)]
        dropped += len(items) - len(kept)
        report[field] = kept
    for n, entry in enumerate(report.get("entries") or [], start=1):
        entry["company_contact"] = None
        entry["rank"] = n
    return report, dropped


def problems(report: dict[str, Any], words: list[str]) -> list[str]:
    """What still makes the report unsafe: forbidden words (named by count only) and contacts."""
    found = [f"forbidden word #{i + 1}" for i, w in enumerate(words) if _mentions(report, [w])]
    return found + find_pii(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("reports", type=Path)
    parser.add_argument("--forbid-env", default="DEMO_FORBID")
    args = parser.parse_args(argv)
    words = [w.strip().casefold() for w in os.environ.get(args.forbid_env, "").split(";")]
    words = [w for w in words if w]
    if not words:
        print(f"{args.forbid_env} is empty: refusing to publish without the private word list")
        return 1
    runs = sorted(args.reports.glob("*/*/run.json"))
    if not runs:
        print("no run.json found")
        return 1
    for path in runs:
        report, dropped = sanitize(json.loads(path.read_text(encoding="utf-8")), words)
        left = problems(report, words)
        if left:
            print(f"UNSAFE, not written: {path.parent.name}: {len(left)} problem(s)")
            for p in left[:10]:
                print(f"  {p}")
            return 1
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"sanitized {path.parent.name}: {dropped} item(s) dropped, contacts removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
