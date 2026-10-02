"""The factory gate: every ticket and every merge must pass this (docs/FACTORY.md §4).

Run: uv run python scripts/gate.py   (exit code 1 on the first failing step)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def has_tests(folder: Path) -> bool:
    return folder.exists() and any(folder.rglob("test_*.py"))


def steps() -> list[tuple[str, list[str]]]:
    py = sys.executable
    plan = [("invariants", [py, "scripts/check_invariants.py"])]
    if (ROOT / "pyproject.toml").exists():
        plan.append(("lint", [py, "-m", "ruff", "check", "northvaine", "tests", "scripts"]))
    if has_tests(ROOT / "tests"):
        plan.append((
            "unit tests",
            [py, "-m", "pytest", "-q", "-m", "not live", "--ignore=tests/golden"],
        ))
    if has_tests(ROOT / "tests" / "golden"):
        plan.append(("golden set", [py, "-m", "pytest", "-q", "tests/golden"]))
    if (ROOT / "frontend" / "package.json").exists():
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        plan.append(("frontend build", [npm, "--prefix", "frontend", "run", "build"]))
    return plan


def main() -> int:
    for name, cmd in steps():
        print(f"\n=== gate: {name}: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, cwd=ROOT)
        if result.returncode != 0:
            print(f"\nGATE FAILED at step: {name}")
            return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
