"""Tests for scripts/tasks.py (ticket T1.3). Nothing here spawns a process."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
LINT_PATHS = ["northvaine", "tests", "scripts", "migrations"]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nv_tasks", REPO / "scripts" / "tasks.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tasks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """The module with ROOT at an empty tmp repo and process spawning forbidden."""
    module = _load()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"tried to spawn a process: {args}")

    monkeypatch.setattr(module.subprocess, "run", forbidden)
    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    return module


def _golden_tests(root: Path) -> None:
    (root / "tests" / "golden").mkdir(parents=True)
    (root / "tests" / "golden" / "test_case.py").write_text("", encoding="utf-8")


def _nightly(root: Path) -> None:
    (root / "northvaine" / "jobs").mkdir(parents=True)
    (root / "northvaine" / "jobs" / "nightly.py").write_text("", encoding="utf-8")


def test_task_names_in_order(tasks: ModuleType) -> None:
    assert list(tasks.TASKS) == [
        "setup",
        "dev",
        "test",
        "golden",
        "lint",
        "migrate",
        "db-check",
        "db-test",
        "gate",
        "nightly",
        "smoke",
    ]


def test_help_lists_every_task(tasks: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        tasks.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in tasks.TASKS:
        assert f"  {name} " in out


def test_exact_argv_for_every_task(
    tasks: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _golden_tests(tmp_path)
    _nightly(tmp_path)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/t")
    expected = {
        "setup": [["uv", "sync"]],
        "dev": [[PY, "-m", "uvicorn", "northvaine.api.main:app", "--reload", "--port", "8000"]],
        "test": [[PY, "-m", "pytest", "-q", "-m", "not live and not db", "--ignore=tests/golden"]],
        "golden": [[PY, "-m", "pytest", "tests/golden", "-v", "--tb=short"]],
        "lint": [
            [PY, "-m", "ruff", "check", *LINT_PATHS],
            [PY, "-m", "ruff", "format", "--check", *LINT_PATHS],
        ],
        "migrate": [[PY, "-m", "alembic", "upgrade", "head"]],
        "db-check": [[PY, "-m", "northvaine.core.db"]],
        "db-test": [[PY, "-m", "pytest", "-q", "-m", "db"]],
        "gate": [[PY, "scripts/gate.py"]],
        "nightly": [[PY, "-m", "northvaine.jobs.nightly"]],
        # The only task that spends money; never invoked by the gate (T2.5a).
        "smoke": [[PY, "scripts/smoke_llm.py"]],
    }
    assert set(expected) == set(tasks.TASKS)
    for name, argv in expected.items():
        assert tasks.TASKS[name]() == argv, name


def test_no_shell_make_or_psql(tasks: ModuleType, tmp_path: Path) -> None:
    source = (REPO / "scripts" / "tasks.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
    _golden_tests(tmp_path)
    _nightly(tmp_path)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text("TEST_DATABASE_URL=x\n", encoding="utf-8")
    for build in tasks.TASKS.values():
        for argv in build():
            exe = Path(argv[0]).name.lower()
            assert exe not in {"make", "make.exe", "psql", "psql.exe", "sh", "bash", "cmd"}


def test_print_runs_nothing(tasks: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert tasks.main(["--print", "lint"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert "ruff check northvaine tests scripts migrations" in lines[0]
    assert "ruff format --check northvaine tests scripts migrations" in lines[1]


def test_run_executes_each_command_from_root(
    tasks: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], Path]] = []

    class Done:
        def __init__(self, code: int) -> None:
            self.returncode = code

    def fake_run(cmd: list[str], cwd: Path) -> Done:
        calls.append((cmd, cwd))
        return Done(3 if "format" in cmd else 0)

    monkeypatch.setattr(tasks.subprocess, "run", fake_run)
    assert tasks.main(["lint"]) == 3
    assert [c for c, _ in calls] == tasks.lint()
    assert all(cwd == tmp_path for _, cwd in calls)


def test_golden_without_tests_exits_zero(
    tasks: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "tests" / "golden").mkdir(parents=True)
    (tmp_path / "tests" / "golden" / "conftest.py").write_text("", encoding="utf-8")
    assert tasks.main(["golden"]) == 0
    assert "no golden tests yet" in capsys.readouterr().out


def test_db_test_without_url_fails_before_pytest(
    tasks: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".env").write_text("# TEST_DATABASE_URL=x\nTEST_DATABASE_URL=\n", encoding="utf-8")
    assert tasks.main(["db-test"]) == 1
    assert "TEST_DATABASE_URL" in capsys.readouterr().err


def test_db_test_reads_dotenv(tasks: ModuleType, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "DATABASE_URL=a\nTEST_DATABASE_URL = 'postgresql+asyncpg://u@h/t'\n", encoding="utf-8"
    )
    assert tasks.TASKS["db-test"]() == [[PY, "-m", "pytest", "-q", "-m", "db"]]


def test_db_test_reads_environment(tasks: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://u@h/t")
    assert tasks.TASKS["db-test"]() == [[PY, "-m", "pytest", "-q", "-m", "db"]]


def test_nightly_missing_module_exits_two(
    tasks: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tasks.main(["nightly"]) == 2
    assert "nightly is available from a later milestone" in capsys.readouterr().err


@pytest.mark.parametrize(("platform", "npm"), [("win32", "npm.cmd"), ("linux", "npm")])
def test_dev_starts_frontend_when_present(
    tasks: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, npm: str
) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tasks.sys, "platform", platform)
    cmds = tasks.TASKS["dev"]()
    assert cmds[0] == [PY, "-m", "uvicorn", "northvaine.api.main:app", "--reload", "--port", "8000"]
    assert cmds[1] == [npm, "--prefix", "frontend", "run", "dev"]
    assert len(cmds) == 2


def test_dev_without_frontend_is_api_only(tasks: ModuleType) -> None:
    assert len(tasks.TASKS["dev"]()) == 1


def test_unknown_task_is_rejected(tasks: ModuleType) -> None:
    with pytest.raises(SystemExit) as exc:
        tasks.main(["deploy"])
    assert exc.value.code == 2
