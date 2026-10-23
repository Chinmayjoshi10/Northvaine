"""Manage the Hugging Face Docker Space that serves the public demo.

  uv run python scripts/hf_space.py init    --space USER/NAME --owner GHCR_OWNER
  uv run python scripts/hf_space.py secrets --space USER/NAME
  uv run python scripts/hf_space.py restart --space USER/NAME

The token is HF_TOKEN, from the environment or `.env`. Prints names only, never a value.
`huggingface_hub` is a dev dependency of this script; northvaine/ never imports it.
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPACE_DIR = ROOT / "deploy" / "hf_space"
OWNER_PLACEHOLDER = "OWNER"

# Runtime keys the app needs on the Space (same names as the nightly workflow).
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
    "TOTAL_BUDGET_USD",
)
DEFAULT_DAILY_BUDGET = Decimal("2")


def _read_env(path: Path) -> dict[str, str]:
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


def load_env(env_path: Path | None = None) -> dict[str, str]:
    """`.env` values, with real environment variables winning."""
    values = _read_env(env_path or ROOT / ".env")
    for name in (*SECRET_NAMES, "HF_TOKEN", "DAILY_BUDGET_USD"):
        if os.environ.get(name):
            values[name] = os.environ[name]
    if values.get("DEMO_DATABASE_URL"):
        # the public Space never gets the production database: the demo one stands in for it
        values["DATABASE_URL"] = values["DEMO_DATABASE_URL"]
    return values


def daily_budget(env: dict[str, str]) -> str:
    """2, unless .env has a lower valid number."""
    try:
        wanted = Decimal(env.get("DAILY_BUDGET_USD", ""))
    except InvalidOperation:
        return str(DEFAULT_DAILY_BUDGET)
    return str(wanted if 0 < wanted < DEFAULT_DAILY_BUDGET else DEFAULT_DAILY_BUDGET)


def _api(env: dict[str, str], api: Any | None) -> Any:
    if api is not None:
        return api
    token = env.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is not set (put it in .env or the environment).")
    from huggingface_hub import HfApi

    return HfApi(token=token)


def cmd_init(space: str, owner: str, api: Any) -> int:
    api.create_repo(repo_id=space, repo_type="space", space_sdk="docker", exist_ok=True)
    for path in sorted(SPACE_DIR.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").replace(OWNER_PLACEHOLDER, owner.lower())
        api.upload_file(
            path_or_fileobj=text.encode("utf-8"),
            path_in_repo=path.name,
            repo_id=space,
            repo_type="space",
        )
        print(f"uploaded: {path.name}")
    return 0


def cmd_secrets(space: str, env: dict[str, str], api: Any) -> int:
    for name in SECRET_NAMES:
        if not env.get(name):
            print(f"not in .env, skipped: {name}")
            continue
        api.add_space_secret(repo_id=space, key=name, value=env[name])
        print(f"set: {name}")
    api.add_space_variable(repo_id=space, key="DAILY_BUDGET_USD", value=daily_budget(env))
    print("set: DAILY_BUDGET_USD (variable)")
    return 0


def cmd_restart(space: str, api: Any) -> int:
    api.restart_space(repo_id=space, factory_reboot=True)
    print("restarted (factory reboot)")
    return 0


def main(
    argv: list[str] | None = None, *, api: Any | None = None, env: dict[str, str] | None = None
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "secrets", "restart"):
        p = sub.add_parser(name)
        p.add_argument("--space", required=True, help="USER/NAME")
        if name == "init":
            p.add_argument("--owner", required=True, help="GitHub owner of the GHCR image")
    args = parser.parse_args(argv)
    values = env if env is not None else load_env()
    client = _api(values, api)
    if args.command == "init":
        return cmd_init(args.space, args.owner, client)
    if args.command == "secrets":
        return cmd_secrets(args.space, values, client)
    return cmd_restart(args.space, client)


if __name__ == "__main__":
    sys.exit(main())
