"""Tests for scripts/check_invariants.py (ticket T1.5). Nothing here touches the network."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
# Built at runtime so this file never trips the banned-word or secrets scan itself.
WORD = "gran" + "ite"
FAKE_KEY = "sk-" + "a1B2" * 6


def _load() -> ModuleType:
    path = REPO / "scripts" / "check_invariants.py"
    spec = importlib.util.spec_from_file_location("nv_check_invariants", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, relpath: str, text: str) -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def inv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """The module pointed at an empty temp tree with one banned term."""
    module = _load()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "APP", tmp_path / "northvaine")
    monkeypatch.setattr(module, "FRONTEND_SRC", tmp_path / "frontend" / "src")
    monkeypatch.setattr(
        module, "tracked_files", lambda: [p for p in tmp_path.rglob("*") if p.is_file()]
    )
    _write(tmp_path, "factory/banned_terms.txt", f"# comment\n{WORD}\n")
    return module


def _clean_tree(root: Path) -> None:
    _write(root, "schema.sql", "CREATE TABLE claims (id bigint PRIMARY KEY);\n")
    _write(root, "migrations/sql/0001_base.sql", "CREATE TABLE documents (id bigint);\n")
    _write(root, "migrations/versions/0001_base.py", "revision = '0001'\n")
    _write(root, "northvaine/core/models.py", "import json\n")


# --- SQL banned terms -------------------------------------------------------------------


def test_banned_word_in_migration_sql_is_reported(inv: ModuleType, tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "migrations/sql/0002_bad.sql", f"CREATE TABLE {WORD}_orders (id int);\n")
    problems = inv.check_sql_banned_terms(inv.sql_files(), inv.load_banned_terms())
    assert problems == [f"migrations/sql/0002_bad.sql:1: industry word '{WORD}' in SQL"]
    assert inv.main() == 1


def test_banned_word_in_migration_py_is_reported(inv: ModuleType, tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "migrations/versions/0002_bad.py", f"x = 1\nTABLE = '{WORD.upper()}'\n")
    problems = inv.check_sql_banned_terms(inv.sql_files(), inv.load_banned_terms())
    assert problems == [f"migrations/versions/0002_bad.py:2: industry word '{WORD.upper()}' in SQL"]
    assert inv.main() == 1


def test_banned_word_in_schema_sql_is_reported(inv: ModuleType, tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "schema.sql", f"-- {WORD} buyers\n")
    assert inv.main() == 1


def test_sql_files_lists_schema_and_migrations_only(inv: ModuleType, tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "migrations/README", f"{WORD}\n")
    _write(tmp_path, "docs/notes.sql", f"{WORD}\n")
    names = sorted(p.relative_to(tmp_path).as_posix() for p in inv.sql_files())
    assert names == [
        "migrations/sql/0001_base.sql",
        "migrations/versions/0001_base.py",
        "schema.sql",
    ]


def test_clean_tree_passes(inv: ModuleType, tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    assert inv.main() == 0


def test_word_inside_a_longer_word_is_not_banned(inv: ModuleType, tmp_path: Path) -> None:
    path = _write(tmp_path, "schema.sql", f"CREATE TABLE x (col_{WORD}ish int);\n")
    assert inv.check_sql_banned_terms([path], [WORD]) == []


def test_no_terms_means_no_problems(inv: ModuleType, tmp_path: Path) -> None:
    path = _write(tmp_path, "schema.sql", f"{WORD}\n")
    assert inv.check_sql_banned_terms([path], []) == []


def test_real_repo_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert _load().main() == 0, capsys.readouterr().out


# --- existing rules (behaviour unchanged) -----------------------------------------------


def test_banned_word_in_app_code_is_reported(inv: ModuleType, tmp_path: Path) -> None:
    bad = _write(tmp_path, "northvaine/radar/funnel.py", f"KIND = '{WORD}'\n")
    good = _write(tmp_path, "northvaine/radar/gate.py", "KIND = 'buyer'\n")
    terms = inv.load_banned_terms()
    assert inv.check_banned_terms([bad], terms) == [
        f"northvaine/radar/funnel.py:1: industry word '{WORD}' in code"
    ]
    assert inv.check_banned_terms([good], terms) == []


def test_llm_sdk_only_in_brain_llm(inv: ModuleType, tmp_path: Path) -> None:
    bad = _write(tmp_path, "northvaine/radar/court.py", "import openai\n")
    good = _write(tmp_path, "northvaine/brain/llm.py", "from openai import AsyncOpenAI\n")
    assert inv.check_imports([bad]) == [
        "northvaine/radar/court.py: imports 'openai'; LLM calls must go through brain/llm.py"
    ]
    assert inv.check_imports([good]) == []


def test_network_libs_only_in_sensors_and_brain_llm(inv: ModuleType, tmp_path: Path) -> None:
    bad = _write(tmp_path, "northvaine/radar/theses.py", "import httpx\n")
    bad_urllib = _write(tmp_path, "northvaine/api/x.py", "from urllib.request import urlopen\n")
    sensor = _write(tmp_path, "northvaine/sensors/tavily.py", "import httpx\n")
    llm = _write(tmp_path, "northvaine/brain/llm.py", "import httpx\n")
    assert inv.check_imports([bad]) == [
        "northvaine/radar/theses.py: imports 'httpx'; network access belongs in sensors/"
    ]
    assert inv.check_imports([bad_urllib]) == [
        "northvaine/api/x.py: imports 'urllib.request'; network access belongs in sensors/"
    ]
    assert inv.check_imports([sensor, llm]) == []


def test_no_sending_libraries_anywhere(inv: ModuleType, tmp_path: Path) -> None:
    bad = _write(tmp_path, "northvaine/sensors/mail.py", "import smtplib\n")
    good = _write(tmp_path, "northvaine/radar/brief.py", "import email.message\n")
    assert inv.check_imports([bad]) == [
        "northvaine/sensors/mail.py: imports 'smtplib'; no real sending in this build"
    ]
    assert inv.check_imports([good]) == []


def test_secrets_scan(inv: ModuleType, tmp_path: Path) -> None:
    bad = _write(tmp_path, "config/local.py", f"KEY = '{FAKE_KEY}'\n")
    good = _write(tmp_path, ".env.example", "NEBIUS_API_KEY=\n")
    binary = tmp_path / "logo.png"
    binary.write_bytes(FAKE_KEY.encode())
    assert inv.check_secrets([bad]) == ["config/local.py:1: looks like a secret"]
    assert inv.check_secrets([good, binary]) == []


def test_secrets_scan_ignores_key_prefix_inside_a_word(inv: ModuleType, tmp_path: Path) -> None:
    slug = _write(
        tmp_path,
        "fixture.json",
        '"url": "https://example.org/maers' + 'k-nimmt-neues-zentrum-in-x"\n',
    )
    assert inv.check_secrets([slug]) == []


# --- M4 ledger rules (T4.0) -------------------------------------------------------------------


def test_banned_word_in_a_prompt_is_reported(inv: ModuleType, tmp_path: Path) -> None:
    bad = _write(tmp_path, "northvaine/brain/prompts/x.v1.md", f"Find a {WORD} buyer.\n")
    _write(tmp_path, "northvaine/brain/prompts/ok.v1.md", "Find a buyer of the offer.\n")
    files = inv.prompt_files()
    assert sorted(p.name for p in files) == ["ok.v1.md", "x.v1.md"]
    problems = inv.check_prompt_banned_terms(files, inv.load_banned_terms())
    assert len(problems) == 1
    assert "northvaine/brain/prompts/x.v1.md:1" in problems[0] and "a prompt" in problems[0]
    assert bad.exists()


def test_prompt_files_without_a_directory_is_empty(inv: ModuleType) -> None:
    assert inv.prompt_files() == []


@pytest.mark.parametrize(
    "line",
    [
        "SELECT * FROM claims WHERE id = 1",
        "INSERT INTO claims (id) VALUES (1)",
        "UPDATE claims SET verified = true",
        "SELECT 1 FROM documents d JOIN claims c ON c.document_id = d.id",
        "q = 'SELECT 1 FROM   claims'",
    ],
)
def test_sql_on_claims_outside_core_ledger_is_reported(
    inv: ModuleType, tmp_path: Path, line: str
) -> None:
    bad = _write(tmp_path, "northvaine/radar/peek.py", f"{line}\n")
    problems = inv.check_claims_sql([bad])
    assert len(problems) == 1 and "northvaine/radar/peek.py:1" in problems[0]


def test_sql_on_claims_is_allowed_in_core_ledger(inv: ModuleType, tmp_path: Path) -> None:
    allowed = _write(tmp_path, "northvaine/core/ledger.py", "q = 'SELECT 1 FROM claims'\n")
    assert inv.check_claims_sql([allowed]) == []


def test_prose_about_claims_does_not_trip_the_sql_rule(inv: ModuleType, tmp_path: Path) -> None:
    prose = _write(
        tmp_path,
        "northvaine/radar/doc.py",
        '"""Facts from claims, and joins into claims-like lists; update claims later."""\n'
        "# select from claims_view is not the table either\n"
        "view = 'verified_claims'\n",
    )
    assert inv.check_claims_sql([prose]) == []


def test_claim_row_import_outside_models_and_core_ledger_is_reported(
    inv: ModuleType, tmp_path: Path
) -> None:
    bad = _write(
        tmp_path, "northvaine/radar/peek.py", "from northvaine.core.models import ClaimRow\n"
    )
    also = _write(
        tmp_path, "northvaine/api/x.py", "from northvaine.core.models import EventRow, ClaimRow\n"
    )
    problems = inv.check_claim_row_imports([bad, also])
    assert len(problems) == 2
    assert "northvaine/radar/peek.py:1" in problems[0] and "ClaimRow" in problems[0]


def test_claim_row_import_is_allowed_in_models_and_core_ledger(
    inv: ModuleType, tmp_path: Path
) -> None:
    models = _write(tmp_path, "northvaine/core/models.py", "class ClaimRow: ...\n")
    ledger = _write(
        tmp_path, "northvaine/core/ledger.py", "from northvaine.core.models import ClaimRow\n"
    )
    other = _write(
        tmp_path, "northvaine/radar/ok.py", "from northvaine.core.models import ClaimCheck\n"
    )
    assert inv.check_claim_row_imports([models, ledger, other]) == []


def test_main_runs_the_ledger_rules(inv: ModuleType, tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "northvaine/radar/peek.py", "from northvaine.core.models import ClaimRow\n")
    assert inv.main() == 1
    _write(tmp_path, "northvaine/radar/peek.py", "x = 1\n")
    _write(tmp_path, "northvaine/brain/prompts/p.v1.md", f"{WORD}\n")
    assert inv.main() == 1
    _write(tmp_path, "northvaine/brain/prompts/p.v1.md", "ok\n")
    _write(tmp_path, "northvaine/radar/sql.py", "q = 'SELECT 1 FROM claims'\n")
    assert inv.main() == 1
    _write(tmp_path, "northvaine/radar/sql.py", "q = 1\n")
    assert inv.main() == 0


def test_main_reports_a_secret(inv: ModuleType, tmp_path: Path) -> None:
    _clean_tree(tmp_path)
    _write(tmp_path, "notes.txt", f"{FAKE_KEY}\n")
    assert inv.main() == 1
