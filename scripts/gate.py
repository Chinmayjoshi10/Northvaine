"""The factory gate: every ticket and every merge must pass this (docs/FACTORY.md §4).

Run: uv run python scripts/gate.py   (exit code 1 on the first failing step)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINT_PATHS = ["northvaine", "tests", "scripts", "migrations"]
RENDER_STEP = "migrations render"


def has_tests(folder: Path) -> bool:
    return folder.exists() and any(folder.rglob("test_*.py"))


def steps() -> list[tuple[str, list[str]]]:
    py = sys.executable
    plan = [("invariants", [py, "scripts/check_invariants.py"])]
    if (ROOT / "pyproject.toml").exists():
        plan.append(("lint", [py, "-m", "ruff", "check", *LINT_PATHS]))
    if (ROOT / "alembic.ini").exists():
        # Offline render: catches a broken migration with no database.
        plan.append((RENDER_STEP, [py, "-m", "alembic", "upgrade", "head", "--sql"]))
    if has_tests(ROOT / "tests"):
        plan.append((
            "unit tests",
            [py, "-m", "pytest", "-q", "-m", "not live and not db", "--ignore=tests/golden"],
        ))
    if has_tests(ROOT / "tests" / "golden"):
        plan.append(("golden set", [py, "-m", "pytest", "-q", "tests/golden"]))
    if (ROOT / "frontend" / "package.json").exists():
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        plan.append(("frontend build", [npm, "--prefix", "frontend", "run", "build"]))
    return plan


def render_env() -> dict[str, str]:
    """A copy of the environment without DATABASE_URL, so the render can never connect."""
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    return env


def run_step(name: str, cmd: list[str]) -> int:
    """Run one step from the repo root and return its exit code."""
    if name == RENDER_STEP:
        # The rendered SQL is noise here; only the exit code (and stderr) matter.
        result = subprocess.run(cmd, cwd=ROOT, env=render_env(), stdout=subprocess.DEVNULL)
    else:
        result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def main() -> int:
    for name, cmd in steps():
        print(f"\n=== gate: {name}: {' '.join(cmd)}", flush=True)
        if run_step(name, cmd) != 0:
            print(f"\nGATE FAILED at step: {name}")
            return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
