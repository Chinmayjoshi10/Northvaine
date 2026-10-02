"""Mechanical checks for the project's non-negotiable rules (CLAUDE.md, ARCHITECTURE §3.1).

Run: uv run python scripts/check_invariants.py   (exit code 1 on any violation)
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "northvaine"
FRONTEND_SRC = ROOT / "frontend" / "src"

LLM_SDKS = {"openai", "anthropic"}
LLM_ALLOWED = {"northvaine/brain/llm.py"}

NETWORK_LIBS = {"httpx", "requests", "aiohttp", "urllib3", "socket", "tavily"}
NETWORK_ALLOWED_PREFIXES = ("northvaine/sensors/",)
NETWORK_ALLOWED_FILES = {"northvaine/brain/llm.py"}

SENDING_LIBS = {"smtplib", "sendgrid", "twilio", "slack_sdk", "telegram", "mailgun", "postmarker"}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"tvly-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"""(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['"][A-Za-z0-9_\-/+]{16,}['"]"""),
]
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_banned_terms() -> list[str]:
    path = ROOT / "factory" / "banned_terms.txt"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#")]


def check_banned_terms(files: list[Path], terms: list[str]) -> list[str]:
    if not terms:
        return []
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, terms)) + r")\b", re.IGNORECASE)
    problems = []
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = pattern.search(line)
            if match:
                problems.append(f"{rel(path)}:{n}: industry word '{match.group(0)}' in code")
    return problems


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
            if node.module == "urllib" or node.module.startswith("urllib.request"):
                found.add("urllib.request")
    return found


def check_imports(py_files: list[Path]) -> list[str]:
    problems = []
    for path in py_files:
        name = rel(path)
        mods = imported_modules(path)
        for mod in sorted(mods & LLM_SDKS):
            if name not in LLM_ALLOWED:
                problems.append(f"{name}: imports '{mod}'; LLM calls must go through brain/llm.py")
        net = (mods & NETWORK_LIBS) | ({"urllib.request"} & mods)
        allowed = name in NETWORK_ALLOWED_FILES or name.startswith(NETWORK_ALLOWED_PREFIXES)
        for mod in sorted(net):
            if not allowed:
                problems.append(f"{name}: imports '{mod}'; network access belongs in sensors/")
        for mod in sorted(mods & SENDING_LIBS):
            problems.append(f"{name}: imports '{mod}'; no real sending in this build")
    return problems


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        return [ROOT / line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        return [
            p for p in ROOT.rglob("*")
            if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)
        ]


def check_secrets(files: list[Path]) -> list[str]:
    problems = []
    for path in files:
        if not path.is_file() or path.suffix in {".zip", ".png", ".jpg", ".pdf", ".ico", ".woff2"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in SECRET_PATTERNS):
                problems.append(f"{rel(path)}:{n}: looks like a secret")
    return problems


def main() -> int:
    py_files = sorted(APP.rglob("*.py")) if APP.exists() else []
    code_files = list(py_files)
    if FRONTEND_SRC.exists():
        code_files += [p for p in FRONTEND_SRC.rglob("*") if p.suffix in {".ts", ".tsx"}]

    problems = (
        check_banned_terms(code_files, load_banned_terms())
        + check_imports(py_files)
        + check_secrets(tracked_files())
    )
    for problem in problems:
        print(f"INVARIANT  {problem}")
    print(f"invariants: {len(problems)} violation(s) in {len(code_files)} code files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
