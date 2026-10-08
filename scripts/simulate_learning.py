"""SIMULATED learning study (D89): replay a recorded run offline, then run the learning loop
against simulated owners whose taste is data (tests/fixtures/owners/*.json). No network, no
model calls, no database. Every number is SIMULATED; reports go to reports/eval/ (never
committed).

    uv run python scripts/tasks.py learn-sim -- --client coldchain_maker
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from northvaine.eval.simulate import load_owner, render_report, simulate  # noqa: E402


def _radar_script():
    spec = importlib.util.spec_from_file_location("nv_radar_cli", ROOT / "scripts" / "radar.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simulate_learning.py")
    parser.add_argument("--client", required=True)
    parser.add_argument("--owners", default=str(ROOT / "tests" / "fixtures" / "owners"))
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args(argv)

    radar = _radar_script()
    from northvaine.core.settings import Settings
    from northvaine.radar.models import load_client_spec

    settings = Settings(_env_file=None)
    spec = load_client_spec(args.client, ROOT / settings.radar_clients_dir)
    recording = radar.load_replay(ROOT / settings.radar_fixtures_dir / args.client, args.client)
    run = asyncio.run(radar.run_replay(spec, recording))

    out_dir = ROOT / "reports" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(Path(args.owners).glob("*.json")):
        owner = load_owner(path)
        report = simulate(run, owner, seeds=args.seeds, rounds=args.rounds)
        text = render_report(report)
        target = out_dir / f"learning_sim_{args.client}_{owner.name}.md"
        target.write_text(text, encoding="utf-8")
        print(text)
        print(f"wrote {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
