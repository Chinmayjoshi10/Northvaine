"""Tests for scripts/gate.py (ticket T1.5). Nothing here spawns a real process."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
LINT_PATHS = ["northvaine", "tests", "scripts", "migrations"]
RENDER = [PY, "-m", "alembic", "upgrade", "head", "--sql"]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nv_gate", REPO / "scripts" / "gate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _touch(root: Path, relpath: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """The module with ROOT at an empty tmp repo and process spawning forbidden."""
    module = _load()
    monkeypatch.setattr(module, "ROOT", tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"tried to spawn a process: {args}")

    monkeypatch.setattr(module.subprocess, "run", forbidden)
    return module


def _full_repo(root: Path) -> None:
    for relpath in [
        "pyproject.toml",
        "alembic.ini",
        "tests/test_x.py",
        "tests/golden/test_cases.py",
        "frontend/package.json",
    ]:
        _touch(root, relpath)


def test_step_order_with_everything_present(gate: ModuleType, tmp_path: Path) -> None:
    _full_repo(tmp_path)
    names = [name for name, _ in gate.steps()]
    assert names == [
        "invariants",
        "lint",
        "migrations render",
        "unit tests",
        "golden set",
        "frontend build",
    ]


def test_step_commands(gate: ModuleType, tmp_path: Path) -> None:
    _full_repo(tmp_path)
    plan = dict(gate.steps())
    assert plan["invariants"] == [PY, "scripts/check_invariants.py"]
    assert plan["lint"] == [PY, "-m", "ruff", "check", *LINT_PATHS]
    assert plan["migrations render"] == RENDER
    assert plan["unit tests"] == [
        PY,
        "-m",
        "pytest",
        "-q",
        "-m",
        "not live and not db",
        "--ignore=tests/golden",
    ]
    assert plan["golden set"] == [PY, "-m", "pytest", "-q", "tests/golden"]


def test_render_step_only_when_alembic_ini_exists(gate: ModuleType, tmp_path: Path) -> None:
    _touch(tmp_path, "pyproject.toml")
    _touch(tmp_path, "tests/test_x.py")
    assert [name for name, _ in gate.steps()] == ["invariants", "lint", "unit tests"]


def test_empty_repo_runs_only_invariants(gate: ModuleType) -> None:
    assert [name for name, _ in gate.steps()] == ["invariants"]


def test_real_repo_plan_includes_render() -> None:
    names = [name for name, _ in _load().steps()]
    assert names[:4] == ["invariants", "lint", "migrations render", "unit tests"]


def test_failing_render_fails_the_gate(
    gate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _full_repo(tmp_path)
    ran: list[str] = []

    def runner(name: str, cmd: list[str]) -> int:
        ran.append(name)
        return 1 if name == "migrations render" else 0

    monkeypatch.setattr(gate, "run_step", runner)
    assert gate.main() == 1
    assert ran == ["invariants", "lint", "migrations render"]
    assert "GATE FAILED at step: migrations render" in capsys.readouterr().out


def test_all_green_passes(
    gate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _full_repo(tmp_path)
    monkeypatch.setattr(gate, "run_step", lambda name, cmd: 0)
    assert gate.main() == 0
    assert "GATE PASSED" in capsys.readouterr().out


def test_render_runs_without_database_url_and_discards_stdout(
    gate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db.invalid/x")
    monkeypatch.setenv("NV_GATE_MARKER", "kept")
    calls: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 3)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate.run_step("migrations render", RENDER) == 3
    call = calls[0]
    env = call["env"]
    assert isinstance(env, dict)
    assert "DATABASE_URL" not in env
    assert env["NV_GATE_MARKER"] == "kept"
    assert call["stdout"] is subprocess.DEVNULL
    assert call["cwd"] == tmp_path
    # The caller's own environment is untouched.
    assert os.environ["DATABASE_URL"] == "postgresql://user:pw@db.invalid/x"


def test_other_steps_inherit_env_and_stdout(
    gate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate.run_step("lint", [PY, "-m", "ruff"]) == 0
    assert calls == [{"cwd": tmp_path}]
