"""Live view of the agent factory: workflow runs, each agent's status and latest action,
the ticket board, builder worktrees, and recent commits.

Run:  python scripts/factory_status.py            (one snapshot)
      python scripts/factory_status.py --watch 10 (refresh every 10 s; Ctrl+C to stop)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = Path.home() / ".claude" / "projects"


def workflow_runs(limit: int) -> list[Path]:
    runs = [
        p for p in PROJECTS.glob("*/*/subagents/workflows/wf_*") if (p / "journal.jsonl").exists()
    ]
    runs = [p for p in runs if "hack" in p.parts[-5].lower()]
    return sorted(runs, key=lambda p: (p / "journal.jsonl").stat().st_mtime, reverse=True)[:limit]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # partially written last line
    except OSError:
        pass
    return rows


def ago(ts: str | None) -> str:
    if not ts:
        return "?"
    then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    secs = int((datetime.now(UTC) - then).total_seconds())
    return f"{secs}s" if secs < 90 else f"{secs // 60}m" if secs < 5400 else f"{secs // 3600}h"


def describe(tool: dict[str, Any]) -> str:
    args = tool.get("input") or {}
    for key in ("command", "file_path", "pattern", "url", "query", "prompt", "description"):
        if key in args:
            text = re.sub(r"\s+", " ", str(args[key]))
            return f"{tool.get('name')}: {text[:70]}"
    return str(tool.get("name"))


def agent_activity(run: Path, agent_id: str) -> tuple[str, str | None, int]:
    rows = read_jsonl(run / f"agent-{agent_id}.jsonl")
    last_action, last_ts, calls = "starting", None, 0
    for row in rows:
        last_ts = row.get("timestamp") or last_ts
        content = (row.get("message") or {}).get("content")
        if row.get("type") == "assistant" and isinstance(content, list):
            for item in content:
                if item.get("type") == "tool_use":
                    calls += 1
                    last_action = describe(item)
    return last_action, last_ts, calls


def show_run(run: Path) -> None:
    entries = read_jsonl(run / "journal.jsonl")
    agents: dict[str, dict[str, Any]] = {}
    for e in entries:
        if e.get("type") == "started":
            agents[e["key"]] = {
                "label": e.get("label", "?"),
                "phase": e.get("phase", ""),
                "id": e.get("agentId"),
                "done": False,
            }
        elif e.get("type") == "result" and e.get("key") in agents:
            agents[e["key"]]["done"] = True
    running = sum(not a["done"] for a in agents.values())
    state = f"{running} running" if running else "no agent running (between steps or finished)"
    print(f"\n▶ {run.name}   agents: {len(agents)}   {state}")
    for a in agents.values():
        action, ts, calls = agent_activity(run, a["id"])
        mark = "✔" if a["done"] else "…"
        detail = (
            f"done ({calls} actions)"
            if a["done"]
            else f"{action}   [{calls} actions, last {ago(ts)} ago]"
        )
        print(f"  {mark} {a['phase']:<10} {a['label']:<40} {detail}")


def show_board() -> None:
    board = ROOT / "factory" / "board"
    tickets = sorted(board.glob("M*/T*.md"))
    if not tickets:
        print("\nBoard: no tickets yet")
        return
    print("\nBoard:")
    for t in tickets:
        head = (
            t.read_text(encoding="utf-8").split("---")[1]
            if t.read_text(encoding="utf-8").startswith("---")
            else ""
        )
        status = re.search(r"^status:\s*(\S+)", head, re.M)
        title = re.search(r"^title:\s*(.+)$", head, re.M)
        state = status.group(1) if status else "?"
        name = title.group(1)[:60] if title else ""
        print(f"  {t.parent.name}/{t.stem[:40]:<40} {state:<12} {name}")


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        return ""


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", type=int, default=0, help="refresh every N seconds")
    parser.add_argument("--runs", type=int, default=2, help="how many recent workflow runs to show")
    args = parser.parse_args()
    while True:
        if args.watch:
            print("\033[2J\033[H", end="")  # clear screen
        print(f"Northvaine factory — {datetime.now():%H:%M:%S}")
        runs = workflow_runs(args.runs)
        if not runs:
            print("\nNo workflow runs found.")
        for run in runs:
            show_run(run)
        show_board()
        print("\nWorktrees:\n  " + (git("worktree", "list") or "-").replace("\n", "\n  "))
        print(
            "\nRecent commits:\n  "
            + (git("log", "--oneline", "--all", "-8") or "-").replace("\n", "\n  ")
        )
        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
