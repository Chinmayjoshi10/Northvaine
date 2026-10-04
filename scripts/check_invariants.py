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

CLAIMS_SQL_ALLOWED = {"northvaine/core/ledger.py"}
CLAIMS_SQL = re.compile(r"\b(FROM|JOIN|INTO|UPDATE)\s+claims\b")
CLAIM_ROW_ALLOWED = {"northvaine/core/models.py", "northvaine/core/ledger.py"}

LLM_MODULE = "northvaine.brain.llm"
LLM_PACKAGE = "northvaine.brain"
CODE_ONLY_MODULES = {"northvaine/radar/brief.py", "northvaine/radar/entities.py"}

SENDING_LIBS = {"smtplib", "sendgrid", "twilio", "slack_sdk", "telegram", "mailgun", "postmarker"}

SECRET_PATTERNS = [
    # The lookbehind stops URL slugs such as ".../maersk-nimmt-..." matching as a key.
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])tvly-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"""(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['"][A-Za-z0-9_\-/+]{16,}['"]"""
    ),
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


def _scan_terms(
    files: list[Path], terms: list[str], where: str, left: str = r"\b", right: str = r"\b"
) -> list[str]:
    if not terms:
        return []
    body = "|".join(map(re.escape, terms))
    pattern = re.compile(left + "(" + body + ")" + right, re.IGNORECASE)
    problems = []
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = pattern.search(line)
            if match:
                problems.append(f"{rel(path)}:{n}: industry word '{match.group(0)}' in {where}")
    return problems


def check_banned_terms(files: list[Path], terms: list[str]) -> list[str]:
    return _scan_terms(files, terms, "code")


def check_sql_banned_terms(files: list[Path], terms: list[str]) -> list[str]:
    """The same rule for the schema and migrations: table and column names are code too."""
    # In SQL an underscore separates words (`x_orders`), so only letters and digits join.
    return _scan_terms(files, terms, "SQL", r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])")


def prompt_files() -> list[Path]:
    """The prompt templates under northvaine/brain/prompts/ (rule a: no industry words)."""
    directory = APP / "brain" / "prompts"
    return sorted(directory.glob("*.md")) if directory.exists() else []


def check_prompt_banned_terms(files: list[Path], terms: list[str]) -> list[str]:
    """Prompts are code too (CLAUDE.md #1): business knowledge reaches them as data."""
    return _scan_terms(files, terms, "a prompt")


def check_claims_sql(py_files: list[Path]) -> list[str]:
    """Rule b: SQL on `claims` lives only in core/ledger.py (migrations, schema, tests exempt)."""
    problems = []
    for path in py_files:
        name = rel(path)
        if name in CLAIMS_SQL_ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CLAIMS_SQL.search(line):
                problems.append(
                    f"{name}:{n}: SQL on claims; only core/ledger.py may touch the table "
                    "(read through the verified_claims view)"
                )
    return problems


def check_claim_row_imports(py_files: list[Path]) -> list[str]:
    """Rule c: `ClaimRow` is imported only in core/models.py and core/ledger.py."""
    problems = []
    for path in py_files:
        name = rel(path)
        if name in CLAIM_ROW_ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == "ClaimRow" for a in node.names):
                problems.append(
                    f"{name}:{node.lineno}: imports ClaimRow; use core/ledger.py instead"
                )
    return problems


def sql_files() -> list[Path]:
    """schema.sql plus every .sql and .py file under migrations/."""
    files = [ROOT / "schema.sql"] if (ROOT / "schema.sql").is_file() else []
    migrations = ROOT / "migrations"
    if migrations.exists():
        files += sorted(
            p
            for p in migrations.rglob("*")
            if p.is_file()
            and p.suffix in {".sql", ".py"}
            and not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)
        )
    return files


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


def check_code_only_modules(py_files: list[Path]) -> list[str]:
    """Rule d (M5, D62-D64): ranking, rendering and identity are code, so these modules never
    import `northvaine.brain.llm` (nor `from northvaine.brain import llm`)."""
    problems = []
    for path in py_files:
        name = rel(path)
        if name not in CODE_ONLY_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            hit = False
            if isinstance(node, ast.Import):
                hit = any(a.name == LLM_MODULE for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                hit = node.module == LLM_MODULE or (
                    node.module == LLM_PACKAGE and any(a.name == "llm" for a in node.names)
                )
            if hit:
                problems.append(
                    f"{name}:{node.lineno}: imports brain.llm; this module is code only"
                )
    return problems


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return [ROOT / line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        return [
            p
            for p in ROOT.rglob("*")
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

    terms = load_banned_terms()
    sql = sql_files()
    problems = (
        check_banned_terms(code_files, terms)
        + check_sql_banned_terms(sql, terms)
        + check_prompt_banned_terms(prompt_files(), terms)
        + check_claims_sql(py_files)
        + check_claim_row_imports(py_files)
        + check_imports(py_files)
        + check_code_only_modules(py_files)
        + check_secrets(tracked_files())
    )
    for problem in problems:
        print(f"INVARIANT  {problem}")
    print(
        f"invariants: {len(problems)} violation(s) in {len(code_files)} code files"
        f" and {len(sql)} SQL/migration files"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
