"""Alembic scaffold and the frozen v1 baseline, checked offline with no database (T1.1)."""

from __future__ import annotations

import configparser
import hashlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "alembic.ini"
BASELINE = ROOT / "migrations" / "sql" / "0001_v1_baseline.sql"
REVISION_0001 = ROOT / "migrations" / "versions" / "0001_v1_baseline.py"

# sha256 of schema.sql at e141b6d, LF line endings.
BASELINE_SHA256 = "829e4837a4a854c564ae86d677f62d2d86be48d6888766e6e0082e193fe70873"

V1_TABLES = {
    "workspaces", "users", "memberships", "companies", "sources", "documents",
    "document_chunks", "claims", "events", "business_profiles", "products",
    "workspace_companies", "theses", "cases", "case_evidence", "contacts", "messages",
    "quote_requests", "feedback", "outcomes", "strategy_versions", "questions", "jobs",
    "llm_calls", "audit_log",
}  # fmt: skip


def load_revision_0001():
    spec = importlib.util.spec_from_file_location("rev_0001_v1_baseline", REVISION_0001)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_is_byte_identical_to_v1_schema() -> None:
    data = BASELINE.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == BASELINE_SHA256


def test_alembic_ini_is_ascii_and_has_no_url() -> None:
    raw = ALEMBIC_INI.read_bytes()
    raw.decode("ascii")  # raises on any non-ASCII byte
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(raw.decode("ascii"))
    for section in parser.sections():
        assert not parser.get(section, "sqlalchemy.url", fallback=""), section
    assert parser.get("alembic", "script_location") == "%(here)s/migrations"
    assert parser.get("alembic", "prepend_sys_path") == "."
    assert "://" not in raw.decode("ascii")


def test_revision_0001_shape() -> None:
    rev = load_revision_0001()
    assert rev.revision == "0001"
    assert rev.down_revision is None
    assert set(rev.V1_TABLES) == V1_TABLES
    assert len(rev.V1_TABLES) == 25
    # Creation order in the frozen file is the order the downgrade reverses.
    created = re.findall(r"^CREATE TABLE (\w+)", BASELINE.read_text(encoding="utf-8"), re.M)
    assert tuple(created) == rev.V1_TABLES


@pytest.fixture
def offline_sql(clean_settings: None) -> str:
    buffer = io.StringIO()
    cfg = Config(str(ALEMBIC_INI), output_buffer=buffer)
    command.upgrade(cfg, "head", sql=True)
    return buffer.getvalue()


def test_offline_upgrade_renders_every_v1_table(offline_sql: str) -> None:
    created = set(re.findall(r"CREATE TABLE (\w+) \(", offline_sql))
    assert created >= V1_TABLES
    assert "CREATE EXTENSION IF NOT EXISTS vector" in offline_sql
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in offline_sql
    assert "CREATE INDEX jobs_ready" in offline_sql
    assert ":2100000" not in offline_sql
    assert "2100000" not in offline_sql


def test_offline_downgrade_keeps_extensions(clean_settings: None) -> None:
    buffer = io.StringIO()
    cfg = Config(str(ALEMBIC_INI), output_buffer=buffer)
    command.downgrade(cfg, "0001:base", sql=True)
    sql = buffer.getvalue()
    dropped = re.findall(r"DROP TABLE (\w+)", sql)
    assert set(dropped) == V1_TABLES
    assert dropped[0] == "audit_log"
    assert dropped.index("cases") < dropped.index("theses")
    assert dropped.index("memberships") < dropped.index("workspaces")
    assert "DROP EXTENSION" not in sql.upper()


def test_cli_offline_upgrade_needs_no_database_url(tmp_path: Path) -> None:
    """`alembic upgrade head --sql` with DATABASE_URL unset and no `.env` in the cwd."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() not in {"DATABASE_URL", "TEST_DATABASE_URL"}
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head", "--sql"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE audit_log" in result.stdout


def test_migrated_url_skips_without_test_database_url(
    pytester: pytest.Pytester, clean_settings: None
) -> None:
    pytester.syspathinsert(ROOT)
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(
        textwrap.dedent(
            """
            from tests.conftest import clean_settings, test_database_url
            from tests.db.conftest import migrated_url
            """
        )
    )
    pytester.makepyfile(
        textwrap.dedent(
            """
            def test_needs_db(clean_settings, migrated_url):
                raise AssertionError("must not run without TEST_DATABASE_URL")
            """
        )
    )
    result = pytester.runpytest_inprocess("-p", "no:cacheprovider", "-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*db: set TEST_DATABASE_URL*"])
