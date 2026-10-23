"""Copy the nightly workflow's secrets from `.env` into GitHub Actions secrets.

  uv run python scripts/gh_secrets.py --repo OWNER/REPO

Writes a temporary env file holding only the names below, runs `gh secret set --env-file`, and
deletes the file afterwards. Prints names only, never a value.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# What .github/workflows/nightly.yml reads (plus the Hugging Face pair, when present).
SECRET_NAMES = (
    "DATABASE_URL",
    "NEBIUS_API_KEY",
    "NEBIUS_BASE_URL",
    "MODEL_FAST",
    "MODEL_MID",
    "MODEL_DEEP",
    "MODEL_EMBED",
    "EMBED_DIM",
    "TAVILY_API_KEY",
    "COMPANIES_HOUSE_API_KEY",
    "DAILY_BUDGET_USD",
    "TOTAL_BUDGET_USD",
    "HF_TOKEN",
    "HF_SPACE",
)


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of a .env file; malformed lines are skipped without being shown."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value
    return values


def main(argv: list[str] | None = None, *, env_path: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    args = parser.parse_args(argv)
    if shutil.which("gh") is None:
        print("The GitHub CLI (gh) is not installed. Install it from https://cli.github.com/")
        print("(Windows: winget install GitHub.cli), then run: gh auth login")
        return 1
    env = read_env(env_path or ROOT / ".env")
    if not env.get("DEMO_DATABASE_URL"):
        print("DEMO_DATABASE_URL is missing from .env: the public nightly job must never get the")
        print("production DATABASE_URL. Create a separate demo database and add it first.")
        return 1
    env["DATABASE_URL"] = env["DEMO_DATABASE_URL"]  # the public job uses the demo database
    chosen = {n: env[n] for n in SECRET_NAMES if env.get(n)}
    missing = [n for n in SECRET_NAMES if n not in chosen]
    if not chosen:
        print("No secret names found in .env; nothing to set.")
        return 1
    fd, tmp_name = tempfile.mkstemp(prefix="nv_gh_secrets_", suffix=".env")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for name, value in chosen.items():
                handle.write(f"{name}={value}\n")
        result = subprocess.run(
            ["gh", "secret", "set", "--env-file", tmp_name, "--repo", args.repo],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    if result.returncode != 0:
        print("gh secret set failed (is `gh auth login` done, and the repo name right?)")
        return result.returncode
    for name in chosen:
        print(f"set: {name}")
    for name in missing:
        print(f"not in .env, skipped: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
