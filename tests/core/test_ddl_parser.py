"""Unit cases for tests/core/ddl_parser.py, one per supported construct (T1.8)."""

from __future__ import annotations

import pytest

from tests.core.ddl_parser import ColumnInfo, DdlParseError, parse_ddl, parse_schema


def test_create_table_columns_types_and_nullability() -> None:
    tables = parse_ddl(
        """
        CREATE TABLE t (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          name text NOT NULL,
          note text,
          tags text[] NOT NULL DEFAULT '{}',
          cost numeric( 10, 6 ) NOT NULL DEFAULT 0,
          emb vector,
          fixed vector(1024),
          created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    assert tables == {
        "t": {
            "id": ColumnInfo("uuid", False),
            "name": ColumnInfo("text", False),
            "note": ColumnInfo("text", True),
            "tags": ColumnInfo("text[]", False),
            "cost": ColumnInfo("numeric(10,6)", False),
            "emb": ColumnInfo("vector", True),
            "fixed": ColumnInfo("vector(1024)", True),
            "created_at": ColumnInfo("timestamptz", False),
        }
    }


def test_inline_comments_and_a_comma_in_a_comment_are_ignored() -> None:
    tables = parse_ddl(
        """CREATE TABLE t (
          a text NOT NULL,   -- first, with a comma (and parens)
          /* block, comment */ b int,  -- NOT NULL is only in this comment
          c int NOT NULL
        )"""
    )
    assert tables["t"] == {
        "a": ColumnInfo("text", False),
        "b": ColumnInfo("int", True),
        "c": ColumnInfo("int", False),
    }


def test_table_level_primary_key_makes_columns_not_null() -> None:
    tables = parse_ddl(
        """CREATE TABLE m (
          a uuid, b uuid, c text,
          PRIMARY KEY (a, b)
        )"""
    )
    assert [tables["m"][c].nullable for c in "abc"] == [False, False, True]


def test_table_level_constraints_are_not_columns() -> None:
    tables = parse_ddl(
        """CREATE TABLE t (
          a int, b int,
          UNIQUE NULLS NOT DISTINCT (a, b),
          CHECK (a <> b),
          FOREIGN KEY (a, b) REFERENCES u(a, b)
        )"""
    )
    assert set(tables["t"]) == {"a", "b"}


def test_a_column_called_key_is_a_column() -> None:
    tables = parse_ddl("CREATE TABLE b (key text NOT NULL, kind text)")
    assert set(tables["b"]) == {"key", "kind"}


def test_inline_check_in_values() -> None:
    tables = parse_ddl(
        "CREATE TABLE t (role text NOT NULL CHECK (role IN ('owner','manager', 'rep')),"
        " n int CHECK (n >= 0), k text CHECK (k ~ '^[a-z]+$'))"
    )
    assert tables["t"]["role"].check_values == ("owner", "manager", "rep")
    assert tables["t"]["n"].check_values is None
    assert tables["t"]["k"].check_values is None


def test_multi_line_check_with_comments_and_a_named_constraint() -> None:
    tables = parse_ddl(
        """CREATE TABLE cases (
          stage text NOT NULL DEFAULT 'candidate' CONSTRAINT cases_stage_check CHECK (stage IN
                 ('candidate','gated',   -- early
                  'won','lost')),
                 -- a comment line between definitions
          other text
        )"""
    )
    info = tables["cases"]["stage"]
    assert info.check_values == ("candidate", "gated", "won", "lost")
    assert info.nullable is False
    assert tables["cases"]["other"].check_values is None


def test_alter_add_column_with_default_and_references() -> None:
    tables = parse_ddl(
        """CREATE TABLE w (id uuid PRIMARY KEY);
        CREATE TABLE jobs (id bigserial PRIMARY KEY);
        ALTER TABLE jobs ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
        ALTER TABLE jobs ADD COLUMN finished_at timestamptz;
        ALTER TABLE jobs ADD COLUMN max_attempts int NOT NULL DEFAULT 5 CHECK (max_attempts >= 1);
        ALTER TABLE jobs ADD COLUMN workspace_id uuid REFERENCES w(id) ON DELETE CASCADE;
        ALTER TABLE jobs ADD status text NOT NULL CHECK (status IN ('a','b'))"""
    )
    jobs = tables["jobs"]
    assert jobs["created_at"] == ColumnInfo("timestamptz", False)
    assert jobs["finished_at"] == ColumnInfo("timestamptz", True)
    assert jobs["max_attempts"] == ColumnInfo("int", False)
    assert jobs["workspace_id"] == ColumnInfo("uuid", True)
    assert jobs["status"] == ColumnInfo("text", False, ("a", "b"))


def test_alter_drop_column_and_alter_column_type() -> None:
    tables = parse_ddl(
        """CREATE TABLE theses (id uuid PRIMARY KEY, alpha real NOT NULL, embedding vector(1024));
        ALTER TABLE theses DROP COLUMN alpha;
        ALTER TABLE theses ALTER COLUMN embedding TYPE vector;
        ALTER TABLE theses ALTER COLUMN id TYPE text USING id::text"""
    )
    assert set(tables["theses"]) == {"id", "embedding"}
    assert tables["theses"]["embedding"] == ColumnInfo("vector", True)
    assert tables["theses"]["id"] == ColumnInfo("text", False)


def test_alter_column_set_and_drop_not_null() -> None:
    tables = parse_ddl(
        """CREATE TABLE t (a int, b int NOT NULL);
        ALTER TABLE t ALTER COLUMN a SET NOT NULL;
        ALTER TABLE t ALTER COLUMN b DROP NOT NULL"""
    )
    assert (tables["t"]["a"].nullable, tables["t"]["b"].nullable) == (False, True)


def test_alter_add_constraint_check_and_drop_constraint() -> None:
    sql = """CREATE TABLE cases (stage text NOT NULL);
        ALTER TABLE cases ADD CONSTRAINT cases_stage_check CHECK (stage IN ('a','b'));
        ALTER TABLE cases ADD CONSTRAINT cases_pk UNIQUE (stage)"""
    assert parse_ddl(sql)["cases"]["stage"].check_values == ("a", "b")
    dropped = parse_ddl(sql + ";\nALTER TABLE cases DROP CONSTRAINT cases_stage_check")
    assert dropped["cases"]["stage"].check_values is None


def test_add_constraint_replaces_an_earlier_value_list() -> None:
    tables = parse_ddl(
        """CREATE TABLE t (s text CHECK (s IN ('a')));
        ALTER TABLE t ADD CONSTRAINT c2 CHECK (s IN ('a','b'))"""
    )
    assert tables["t"]["s"].check_values == ("a", "b")


def test_several_alter_actions_in_one_statement() -> None:
    tables = parse_ddl(
        "CREATE TABLE t (a int, b int); ALTER TABLE t ADD COLUMN c int NOT NULL, DROP COLUMN a"
    )
    assert set(tables["t"]) == {"b", "c"}


def test_views_and_indexes_are_recorded_by_name() -> None:
    parsed = parse_schema(
        """CREATE TABLE h (id int, kind text);
        CREATE VIEW patterns AS
          SELECT id, kind FROM h WHERE kind = 'pattern';
        CREATE INDEX h_lookup ON h (id, kind) WHERE kind = 'x';
        CREATE UNIQUE INDEX h_open ON h (id) NULLS NOT DISTINCT WHERE kind NOT IN ('a','b');
        CREATE INDEX IF NOT EXISTS h_extra ON h (kind);
        DROP INDEX h_extra"""
    )
    assert parsed.views == {"patterns"}
    assert parsed.indexes == {"h_lookup", "h_open"}
    assert set(parsed.tables["h"]) == {"id", "kind"}


def test_drop_table_and_view() -> None:
    parsed = parse_schema(
        "CREATE TABLE a (x int); CREATE TABLE b (y int); CREATE VIEW v AS SELECT 1;"
        " DROP TABLE a; DROP VIEW v"
    )
    assert set(parsed.tables) == {"b"}
    assert parsed.views == set()


def test_non_table_statements_are_ignored() -> None:
    tables = parse_ddl(
        """BEGIN;
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE t (label text NOT NULL);
        INSERT INTO t (label) VALUES ('CREATE TABLE evil (x int)');
        UPDATE alembic_version SET version_num='0002';
        COMMIT"""
    )
    assert set(tables) == {"t"}


def test_schema_qualified_and_quoted_names() -> None:
    tables = parse_ddl('CREATE TABLE public."Things" (Id uuid PRIMARY KEY, "Name" text)')
    assert tables == {"things": {"id": ColumnInfo("uuid", False), "name": ColumnInfo("text", True)}}


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (a int); ALTER TABLE t RENAME COLUMN a TO b",
        "CREATE TABLE t (a int); ALTER TABLE t ALTER COLUMN zzz TYPE text",
        "ALTER TABLE ghost ADD COLUMN a int",
        "CREATE TABLE t (a int, CHECK (b IN ('x')))",
        "CREATE TABLE t (a int",
    ],
)
def test_unsupported_or_inconsistent_ddl_raises(sql: str) -> None:
    with pytest.raises(DdlParseError):
        parse_ddl(sql)


# --- M1 carry-over 1: unsupported DDL raises instead of being silently ignored (T2.1b) -------


@pytest.mark.parametrize(
    ("label", "statement"),
    [
        ("CREATE SEQUENCE", "CREATE SEQUENCE thing_id_seq START 1"),
        ("CREATE TYPE", "CREATE TYPE mood AS ENUM ('ok', 'bad')"),
        ("CREATE MATERIALIZED VIEW", "CREATE MATERIALIZED VIEW mv AS SELECT 1"),
        ("ALTER INDEX", "ALTER INDEX cases_open_unique RENAME TO cases_open_uniq"),
        ("DROP SEQUENCE", "DROP SEQUENCE thing_id_seq"),
        ("CREATE TRIGGER", "CREATE TRIGGER t AFTER INSERT ON cases EXECUTE FUNCTION f()"),
    ],
)
def test_an_unsupported_ddl_form_raises_and_names_the_statement(label: str, statement: str) -> None:
    """Silently ignoring these is how schema.sql and the migrations drift apart unnoticed."""
    with pytest.raises(DdlParseError) as caught:
        parse_ddl(statement + ";")
    assert statement[:30] in str(caught.value), label


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto",
        "INSERT INTO event_concepts (label) VALUES ('x')",
        "BEGIN",
        "COMMIT",
        "UPDATE theses SET alpha = 1",
    ],
)
def test_non_table_ddl_is_still_ignored(statement: str) -> None:
    """The hardening must not start rejecting the statements the schema legitimately contains."""
    assert parse_ddl(statement + ";") == {}


def test_the_hnsw_index_form_that_migration_0003_creates_is_accepted() -> None:
    sql = (
        "CREATE TABLE theses (id uuid, embedding vector(1024));"
        "CREATE INDEX theses_embedding_hnsw ON theses USING hnsw (embedding vector_cosine_ops);"
    )
    schema = parse_schema(sql)
    assert "theses_embedding_hnsw" in schema.indexes
    assert schema.tables["theses"]["embedding"].type == "vector(1024)"


def test_the_halfvec_expression_index_fallback_form_is_accepted() -> None:
    """The D7 fallback branch: not taken at 1024, but the parser must not choke if it ever is."""
    sql = (
        "CREATE TABLE t (embedding vector(3072));"
        "CREATE INDEX t_embedding_hnsw ON t "
        "USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops);"
    )
    assert "t_embedding_hnsw" in parse_schema(sql).indexes


def test_the_llm_calls_columns_migration_0003_adds_are_accepted() -> None:
    sql = (
        "CREATE TABLE llm_calls (id bigserial PRIMARY KEY);"
        "ALTER TABLE llm_calls ADD COLUMN run_id uuid;"
        "ALTER TABLE llm_calls ADD COLUMN prompt_version text;"
        "ALTER TABLE llm_calls ADD COLUMN latency_ms int;"
        "ALTER TABLE llm_calls ADD COLUMN error text;"
        "ALTER TABLE llm_calls ADD COLUMN provider text NOT NULL DEFAULT 'nebius';"
    )
    columns = parse_ddl(sql)["llm_calls"]
    for name in ("run_id", "prompt_version", "latency_ms", "error", "provider"):
        assert name in columns, name
    assert columns["provider"].type == "text"


def test_named_table_level_check_and_add_constraint_unique_are_accepted() -> None:
    """Migration 0005 shapes: expression CHECKs (no IN list) and ADD CONSTRAINT ... UNIQUE."""
    sql = (
        "CREATE TABLE c (id uuid PRIMARY KEY, verified boolean NOT NULL DEFAULT false,"
        " quote_offset int, verified_by text);"
        "ALTER TABLE c ADD COLUMN status text NOT NULL DEFAULT 'pending'"
        " CHECK (status IN ('pending','verified'));"
        "ALTER TABLE c ADD COLUMN fingerprint text NOT NULL;"
        "ALTER TABLE c ADD CONSTRAINT c_fingerprint_key UNIQUE (fingerprint);"
        "ALTER TABLE c ADD CONSTRAINT c_verified_status CHECK (verified = (status = 'verified'));"
        "ALTER TABLE c ADD CONSTRAINT c_verified_complete"
        " CHECK (NOT verified OR (quote_offset IS NOT NULL AND verified_by IS NOT NULL));"
        "CREATE VIEW v AS SELECT c.* FROM c WHERE c.verified;"
    )
    schema = parse_schema(sql)
    columns = schema.tables["c"]
    assert columns["status"] == ColumnInfo("text", False, ("pending", "verified"))
    assert columns["fingerprint"] == ColumnInfo("text", False)
    assert columns["verified"] == ColumnInfo("boolean", False)
    assert schema.views == {"v"}
    dropped = parse_ddl(
        sql
        + "ALTER TABLE c DROP CONSTRAINT c_verified_complete;"
        + "ALTER TABLE c DROP CONSTRAINT c_fingerprint_key;"
        + "ALTER TABLE c DROP CONSTRAINT c_verified_status;"
    )
    assert dropped["c"]["status"].check_values == ("pending", "verified")
