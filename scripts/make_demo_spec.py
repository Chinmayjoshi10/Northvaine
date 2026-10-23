"""Make the public demo client spec from a private one.

  uv run python scripts/make_demo_spec.py --source <private spec.json> \
      --out deploy/demo/clients/stone_exporter_demo.json --forbid acme --forbid "jane doe"

Copies the spec, sets the id and name, empties `existing_customers`, and refuses (exit 1) if any
string in the result still contains a forbidden word (case-insensitive). The message names the
JSON path of the field, never its value.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEMO_ID = "stone_exporter_demo"
DEMO_NAME = "An Indian natural-stone exporter"


def find_forbidden(node: Any, words: list[str], path: str = "$") -> list[str]:
    """JSON paths of every string (keys included) that contains a forbidden word."""
    found: list[str] = []
    lowered = [w.lower() for w in words if w.strip()]
    if isinstance(node, str):
        if any(w in node.lower() for w in lowered):
            found.append(path)
    elif isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and any(w in key.lower() for w in lowered):
                found.append(f"{path}.{key} (key)")
            found += find_forbidden(value, words, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += find_forbidden(value, words, f"{path}[{i}]")
    return found


def make_demo(spec: dict[str, Any]) -> dict[str, Any]:
    demo = dict(spec)
    demo["id"] = DEMO_ID
    demo["name"] = DEMO_NAME
    demo["existing_customers"] = []
    return demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--source", required=True, help="path to the private client spec")
    parser.add_argument("--out", required=True, help="where to write the demo spec")
    parser.add_argument("--forbid", action="append", default=[], help="word that must not remain")
    args = parser.parse_args(argv)
    source = Path(args.source)
    if not source.is_file():
        print(f"source spec not found: {source}", file=sys.stderr)
        return 2
    demo = make_demo(json.loads(source.read_text(encoding="utf-8")))
    bad = find_forbidden(demo, args.forbid)
    if bad:
        print("REFUSED, nothing written. A forbidden word remains in:", file=sys.stderr)
        for path in bad:
            print(f"  {path}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(demo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
