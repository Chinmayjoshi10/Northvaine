"""Windows-friendly task runner: every CLAUDE.md command without make, psql or a shell.

Run: uv run python scripts/tasks.py <task>          (run a task)
     uv run python scripts/tasks.py --print <task>  (print its commands, run nothing)

Stdlib only, so it works before `uv sync`. Each task builds a list of argv lists from
`sys.executable`; commands run with cwd at the repo root and never through a shell.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINT_PATHS = ["northvaine", "tests", "scripts", "migrations"]


class TaskExit(Exception):  # noqa: N818 - it is a control-flow signal, not an error
    """Stop a task before any command runs, with an exit code and a readable message."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _py(*args: str) -> list[str]:
    return [sys.executable, *args]


def setup() -> list[list[str]]:
    return [["uv", "sync"]]


def dev() -> list[list[str]]:
    cmds = [_py("-m", "uvicorn", "northvaine.api.main:app", "--reload", "--port", "8000")]
    if (ROOT / "frontend" / "package.json").exists():
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        cmds.append([npm, "--prefix", "frontend", "run", "dev"])
    return cmds


def test() -> list[list[str]]:
    return [_py("-m", "pytest", "-q", "-m", "not live and not db", "--ignore=tests/golden")]


def golden() -> list[list[str]]:
    folder = ROOT / "tests" / "golden"
    if not (folder.exists() and any(folder.rglob("test_*.py"))):
        raise TaskExit(0, "no golden tests yet")
    return [_py("-m", "pytest", "tests/golden", "-v", "--tb=short")]


def lint() -> list[list[str]]:
    return [
        _py("-m", "ruff", "check", *LINT_PATHS),
        _py("-m", "ruff", "format", "--check", *LINT_PATHS),
    ]


def migrate() -> list[list[str]]:
    return [_py("-m", "alembic", "upgrade", "head")]


def db_check() -> list[list[str]]:
    return [_py("-m", "northvaine.core.db")]


def _dotenv_value(name: str) -> str:
    """The value of `name` in ROOT/.env (simple KEY= scan), or "" when absent."""
    path = ROOT / ".env"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    value = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        if key.strip() == name:
            value = rest.strip().strip("'\"").strip()
    return value


def db_test() -> list[list[str]]:
    if not (os.environ.get("TEST_DATABASE_URL", "").strip() or _dotenv_value("TEST_DATABASE_URL")):
        raise TaskExit(
            1,
            "db-test needs TEST_DATABASE_URL. Set it in the environment or in .env "
            "(see docs/DEVELOPMENT.md). Never point it at the demo database.",
        )
    return [_py("-m", "pytest", "-q", "-m", "db")]


def gate() -> list[list[str]]:
    return [_py("scripts/gate.py")]


def nightly() -> list[list[str]]:
    jobs = ROOT / "northvaine" / "jobs"
    if not ((jobs / "nightly.py").exists() or (jobs / "nightly" / "__init__.py").exists()):
        raise TaskExit(2, "nightly is available from a later milestone")
    return [_py("-m", "northvaine.jobs.nightly")]


def smoke() -> list[list[str]]:
    """The live smoke run. Spends real money; never part of the gate."""
    return [_py("scripts/smoke_llm.py")]


def record_sensors() -> list[list[str]]:
    """Record redacted live TED/Tavily fixtures. Calls live APIs; never part of the gate."""
    return [_py("scripts/record_sensor_fixtures.py")]


def record_llm() -> list[list[str]]:
    """Record redacted LLM fixtures from the live API. Spends money; orchestrator only (D53)."""
    return [_py("scripts/record_llm_fixtures.py")]


def learn_sim() -> list[list[str]]:
    """SIMULATED learning study on a recording (add -- --client <id>); offline, free (D89)."""
    return [_py("scripts/simulate_learning.py")]


def radar() -> list[list[str]]:
    """One radar run for a client, offline from its recording (add -- --client <id>)."""
    return [_py("scripts/radar.py")]


def record_radar() -> list[list[str]]:
    """Record a radar run live. Spends Tavily credits and money; orchestrator only (D65)."""
    return [_py("scripts/radar.py", "--record")]


def evaluate() -> list[list[str]]:
    """Quality and outcome metrics from filled-in scorecards (docs/EVALUATION.md)."""
    return [_py("scripts/evaluate.py")]


TASKS: dict[str, Callable[[], list[list[str]]]] = {
    "setup": setup,
    "dev": dev,
    "test": test,
    "golden": golden,
    "lint": lint,
    "migrate": migrate,
    "db-check": db_check,
    "db-test": db_test,
    "gate": gate,
    "nightly": nightly,
    "smoke": smoke,
    "record-sensors": record_sensors,
    "record-llm": record_llm,
    "radar": radar,
    "learn-sim": learn_sim,
    "record-radar": record_radar,
    "eval": evaluate,
}

HELP = {
    "setup": "uv sync (install Python 3.12 env and dev tools)",
    "dev": "run the API with reload on :8000, plus the frontend if it exists",
    "test": "unit tests: no network, no database",
    "golden": "run the golden set",
    "lint": "ruff check and ruff format --check",
    "migrate": "alembic upgrade head",
    "db-check": "print database status (DATABASE_URL)",
    "db-test": "db tests against TEST_DATABASE_URL",
    "gate": "the factory gate (scripts/gate.py)",
    "nightly": "run one radar cycle",
    "smoke": "live LLM smoke run - SPENDS REAL MONEY (add -- --yes to confirm)",
    "record-sensors": "record redacted TED/Tavily fixtures from live APIs (add -- --yes)",
    "record-llm": "record LLM fixtures for the evidence ledger - SPENDS MONEY (add -- --yes)",
    "radar": "radar brief for one client, offline from its recording (add -- --client <id>)",
    "learn-sim": "SIMULATED learning study on a recording, offline (add -- --client <id>)",
    "record-radar": "record a radar run live - SPENDS MONEY (add -- --client <id> --yes)",
    "eval": "quality and outcome metrics from filled-in scorecards (offline)",
}

# arguments after `--` go to the script
PASSTHROUGH = {
    "smoke", "record-sensors", "record-llm", "radar", "record-radar", "eval", "learn-sim",
}  # fmt: skip

PARALLEL = {"dev"}  # these tasks start every command at once and wait for all


def format_argv(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def run_sequential(cmds: list[list[str]]) -> int:
    for cmd in cmds:
        print(f"> {format_argv(cmd)}", flush=True)
        code = subprocess.run(cmd, cwd=ROOT).returncode
        if code != 0:
            return code
    return 0


def run_parallel(cmds: list[list[str]]) -> int:
    procs = []
    for cmd in cmds:
        print(f"> {format_argv(cmd)}", flush=True)
        procs.append(subprocess.Popen(cmd, cwd=ROOT))
    try:
        codes = [p.wait() for p in procs]
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait()
        return 130
    return next((c for c in codes if c != 0), 0)


def build_parser() -> argparse.ArgumentParser:
    lines = "\n".join(f"  {name:<15} {HELP[name]}" for name in TASKS)
    return argparse.ArgumentParser(
        prog="tasks.py",
        description="Northvaine tasks. Works the same in PowerShell and Git Bash.",
        epilog=f"tasks:\n{lines}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.add_argument("task", choices=list(TASKS), metavar="task", help="one of the tasks below")
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="print the commands without running anything",
    )
    argv = list(sys.argv[1:] if argv is None else argv)
    extra: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, extra = argv[:cut], argv[cut + 1 :]
    args = parser.parse_args(argv)
    if extra and args.task not in PASSTHROUGH:
        parser.error(f"task {args.task!r} takes no extra arguments")
    try:
        cmds = TASKS[args.task]()
        if extra:
            cmds[-1] = [*cmds[-1], *extra]
    except TaskExit as stop:
        print(stop.message, file=sys.stdout if stop.code == 0 else sys.stderr)
        return stop.code
    if args.print_only:
        for cmd in cmds:
            print(format_argv(cmd))
        return 0
    try:
        if args.task in PARALLEL:
            return run_parallel(cmds)
        return run_sequential(cmds)
    except FileNotFoundError as exc:
        print(f"command not found: {exc.filename}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
