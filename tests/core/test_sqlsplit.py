"""split_sql: comment removal and top-level `;` splitting (T1.1)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sqlalchemy as sa

from northvaine.core.sqlsplit import split_sql

BASELINE = Path(__file__).resolve().parents[2] / "migrations" / "sql" / "0001_v1_baseline.sql"


@pytest.fixture(scope="module")
def baseline_statements() -> list[str]:
    return split_sql(BASELINE.read_text(encoding="utf-8"))


def test_baseline_splits_into_2_extensions_25_tables_1_index(
    baseline_statements: list[str],
) -> None:
    # Counted by hand from schema.sql at e141b6d: 2 extensions, 25 tables, 1 index.
    assert len(baseline_statements) == 28
    kinds = [" ".join(stmt.split()[:2]).upper() for stmt in baseline_statements]
    assert kinds.count("CREATE EXTENSION") == 2
    assert kinds.count("CREATE TABLE") == 25
    assert kinds.count("CREATE INDEX") == 1
    assert kinds[:2] == ["CREATE EXTENSION"] * 2


def test_baseline_statements_have_no_comments(baseline_statements: list[str]) -> None:
    for stmt in baseline_statements:
        assert "--" not in stmt
        assert "2100000" not in stmt  # the jsonb example in the events comment (line 93)
        assert not stmt.endswith(";")


def test_baseline_statements_have_no_bind_parameters(baseline_statements: list[str]) -> None:
    for stmt in baseline_statements:
        assert sa.text(stmt).compile().params == {}


def test_baseline_table_statements_are_complete(baseline_statements: list[str]) -> None:
    for stmt in baseline_statements:
        if stmt.upper().startswith("CREATE TABLE"):
            assert stmt.endswith(")")
            assert stmt.count("(") == stmt.count(")")


def test_semicolon_inside_line_comment_does_not_split() -> None:
    # schema.sql line 5 has "...Pydantic schema;" inside a comment.
    text = "-- rules: one; two\nCREATE TABLE a (x int); -- trailing; comment\nSELECT 1;"
    assert split_sql(text) == ["CREATE TABLE a (x int)", "SELECT 1"]


def test_quoted_semicolons_do_not_split() -> None:
    text = (
        "SELECT ';' AS a;\n"
        'SELECT 1 AS "a;b";\n'
        "CREATE FUNCTION f() RETURNS int AS $$ SELECT 1; SELECT 2; $$ LANGUAGE sql;\n"
        "SELECT $body$ x; -- not a comment $body$;\n"
    )
    assert split_sql(text) == [
        "SELECT ';' AS a",
        'SELECT 1 AS "a;b"',
        "CREATE FUNCTION f() RETURNS int AS $$ SELECT 1; SELECT 2; $$ LANGUAGE sql",
        "SELECT $body$ x; -- not a comment $body$",
    ]


def test_doubled_quotes_and_escape_strings() -> None:
    text = "SELECT 'it''s; fine';SELECT E'a\\'; b';SELECT \"x\"\"; y\";"
    assert split_sql(text) == ["SELECT 'it''s; fine'", "SELECT E'a\\'; b'", 'SELECT "x""; y"']


def test_double_dash_inside_string_is_kept() -> None:
    assert split_sql("SELECT '--x';") == ["SELECT '--x'"]


def test_block_comments_are_removed_including_nested() -> None:
    text = "SELECT 1 /* a; /* nested; */ still; */ + 2; SELECT 3"
    statements = split_sql(text)
    assert len(statements) == 2
    assert re.sub(r"\s+", " ", statements[0]) == "SELECT 1 + 2"
    assert statements[1] == "SELECT 3"


def test_positional_parameter_is_not_a_dollar_quote() -> None:
    assert split_sql("SELECT $1; SELECT $2;") == ["SELECT $1", "SELECT $2"]


def test_empty_statements_are_dropped() -> None:
    assert split_sql(" ;\n; -- only a comment\n;;") == []
    assert split_sql("") == []
