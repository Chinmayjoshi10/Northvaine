"""schema.sql, the migrations, the Pydantic models and the seed concepts must agree (T1.8).

No database is needed: the migrations are replayed from the offline-rendered SQL of
`alembic upgrade head`, and every file is read with tests/core/ddl_parser.py.
"""

from __future__ import annotations

import io
import re
import types
from enum import StrEnum
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel, create_model

from northvaine.core import models as m
from northvaine.core.standards import EMBED_DIM_EXPECTED
from tests.core.ddl_parser import ColumnInfo, Tables, parse_ddl, parse_schema

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "alembic.ini"
SCHEMA = ROOT / "schema.sql"
SPEC = ROOT / "docs" / "SPEC.md"

# Tables that exist only in the migrated database, not in schema.sql.
ALEMBIC_TABLES = {"alembic_version"}

_rendered: dict[str, str] = {}


# --------------------------------------------------------------------------- helpers


def render_upgrade_sql() -> str:
    """The offline SQL of `alembic upgrade head` (no database, no connection)."""
    if "sql" not in _rendered:
        buffer = io.StringIO()
        command.upgrade(Config(str(ALEMBIC_INI), output_buffer=buffer), "head", sql=True)
        _rendered["sql"] = buffer.getvalue()
    return _rendered["sql"]


@pytest.fixture
def rendered_sql(clean_settings: None) -> str:
    return render_upgrade_sql()


def replayed_tables(rendered: str) -> Tables:
    tables = parse_ddl(rendered)
    return {name: cols for name, cols in tables.items() if name not in ALEMBIC_TABLES}


def schema_diff(left_name: str, left: Tables, right_name: str, right: Tables) -> list[str]:
    """Human-readable differences in tables, columns, types, nullability and CHECK lists."""
    problems: list[str] = []
    for table in sorted(left.keys() - right.keys()):
        problems.append(f"table {table} only in {left_name}")
    for table in sorted(right.keys() - left.keys()):
        problems.append(f"table {table} only in {right_name}")
    for table in sorted(left.keys() & right.keys()):
        for column in sorted(left[table].keys() - right[table].keys()):
            problems.append(f"column {table}.{column} only in {left_name}")
        for column in sorted(right[table].keys() - left[table].keys()):
            problems.append(f"column {table}.{column} only in {right_name}")
        for column in sorted(left[table].keys() & right[table].keys()):
            a, b = left[table][column], right[table][column]
            if a != b:
                problems.append(f"column {table}.{column}: {left_name} {a} != {right_name} {b}")
    return problems


IRREGULAR_MODELS = {
    "hypotheses": "HypothesisRow",
    "theses": "ThesisRow",
    "policy_params": "PolicyParamRow",
    "audit_log": "AuditLogRow",
    "llm_calls": "LlmCallRow",
    "jobs": "Job",
}


def model_name(table: str) -> str:
    if table in IRREGULAR_MODELS:
        return IRREGULAR_MODELS[table]
    *head, last = table.split("_")
    if last.endswith("ies"):
        last = last[:-3] + "y"
    elif last.endswith("s") and not last.endswith("ss"):
        last = last[:-1]
    return "".join(word.capitalize() for word in [*head, last]) + "Row"


def _union_members(annotation: Any) -> tuple[Any, ...]:
    if get_origin(annotation) in (Union, types.UnionType):
        return get_args(annotation)
    return (annotation,)


def is_optional(annotation: Any) -> bool:
    return type(None) in _union_members(annotation)


def enum_of(annotation: Any) -> type[StrEnum] | None:
    for member in _union_members(annotation):
        if isinstance(member, type) and issubclass(member, StrEnum):
            return member
    return None


def model_problems(table: str, columns: dict[str, ColumnInfo], model: type[BaseModel]) -> list[str]:
    """Differences between one table and its row model: fields, Optional, enum values."""
    problems: list[str] = []
    fields = model.model_fields
    for column in sorted(columns.keys() - fields.keys()):
        problems.append(f"{table}.{column}: column has no field in {model.__name__}")
    for field in sorted(fields.keys() - columns.keys()):
        problems.append(f"{table}.{field}: field of {model.__name__} has no column")
    for column in sorted(columns.keys() & fields.keys()):
        info, annotation = columns[column], fields[column].annotation
        # An `Any` field (a JSONB scalar) hides nullability, so it is not compared.
        optional = None if annotation is Any else is_optional(annotation)
        if optional is not None and optional != info.nullable:
            want = "Optional" if info.nullable else "required"
            problems.append(f"{table}.{column}: column is {want}, field annotation is {annotation}")
        enum = enum_of(annotation)
        if info.check_values is not None:
            if enum is None:
                problems.append(f"{table}.{column}: CHECK IN list has no StrEnum field")
            elif set(info.check_values) != {member.value for member in enum}:
                problems.append(
                    f"{table}.{column}: CHECK {sorted(info.check_values)} != "
                    f"{enum.__name__} {sorted(e.value for e in enum)}"
                )
        elif enum is not None:
            problems.append(f"{table}.{column}: StrEnum field {enum.__name__} has no CHECK IN list")
    return problems


def all_model_problems(tables: Tables, namespace: Any = m) -> list[str]:
    problems: list[str] = []
    for table, columns in sorted(tables.items()):
        name = model_name(table)
        model = getattr(namespace, name, None)
        if model is None:
            problems.append(f"{table}: no model {name}")
            continue
        problems.extend(model_problems(table, columns, model))
    return problems


def seed_labels(rendered: str) -> list[str]:
    """Labels of the level-0 rows inserted into event_concepts, in order."""
    labels: list[str] = []
    for statement in re.findall(r"INSERT INTO event_concepts\b.*?;\n", rendered, re.S):
        labels += re.findall(r"\(\s*0\s*,\s*'([a-z_]+)'\s*,", statement)
    return labels


def spec_event_types(spec_text: str) -> list[str]:
    """The backticked event types of the 'Event types' bullet of docs/SPEC.md section 1."""
    match = re.search(r"\*\*Event types\*\*(.*?)Add new types", spec_text, re.S)
    assert match, "SPEC.md section 1 no longer has an 'Event types' bullet"
    return re.findall(r"`([a-z_]+)`", match.group(1))


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def schema_tables() -> Tables:
    return parse_ddl(SCHEMA.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- tests


def test_schema_sql_equals_replayed_migrations(rendered_sql: str, schema_tables: Tables) -> None:
    replay = replayed_tables(rendered_sql)
    assert len(schema_tables) >= 39
    assert schema_diff("schema.sql", schema_tables, "migrations", replay) == []


def test_views_and_indexes_agree(rendered_sql: str) -> None:
    schema = parse_schema(SCHEMA.read_text(encoding="utf-8"))
    replay = parse_schema(rendered_sql)
    assert schema.views == replay.views == {"patterns"}
    assert schema.indexes == replay.indexes
    assert {"cases_open_unique", "events_concept", "jobs_claim", "jobs_lease"} <= schema.indexes
    assert "jobs_ready" not in replay.indexes


def test_every_vector_column_is_sized(rendered_sql: str, schema_tables: Tables) -> None:
    """0003 sizes the vectors (D7/D14). The dimension is never an unreviewed literal:
    schema.sql and the rendered migrations must both equal EMBED_DIM_EXPECTED."""
    for label, tables in (
        ("schema.sql", schema_tables),
        ("migrations", replayed_tables(rendered_sql)),
    ):
        vectors = {
            f"{table}.{column}": info.type
            for table, columns in tables.items()
            for column, info in columns.items()
            if info.type.startswith("vector")
        }
        assert set(vectors) == {
            "document_chunks.embedding", "event_concepts.embedding", "theses.embedding",
        }, label  # fmt: skip
        expected = f"vector({EMBED_DIM_EXPECTED})"
        assert set(vectors.values()) == {expected}, f"{label}: {vectors}"


def test_row_models_match_tables(schema_tables: Tables) -> None:
    assert all_model_problems(schema_tables) == []


def test_every_check_in_list_has_a_matching_enum(schema_tables: Tables) -> None:
    lists = [
        (table, column)
        for table, columns in schema_tables.items()
        for column, info in columns.items()
        if info.check_values is not None
    ]
    assert len(lists) >= 20
    for table, column in lists:
        info = schema_tables[table][column]
        enum = enum_of(getattr(m, model_name(table)).model_fields[column].annotation)
        assert enum is not None, f"{table}.{column}"
        assert set(info.check_values or ()) == {e.value for e in enum}, f"{table}.{column}"


def test_event_type_equals_seed_labels_and_spec(rendered_sql: str) -> None:
    labels = seed_labels(rendered_sql)
    spec = spec_event_types(SPEC.read_text(encoding="utf-8"))
    assert len(labels) == len(set(labels)) == 12
    assert {e.value for e in m.EventType} == set(labels) == set(spec)
    assert len(spec) == 12


# ------------------------------------------------------------------ adversarial checks


def test_extra_column_in_schema_sql_is_detected(
    rendered_sql: str, schema_tables: Tables, tmp_path: Path
) -> None:
    text = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE TABLE workspaces (\n" in text
    tampered = tmp_path / "schema.sql"
    tampered.write_text(
        text.replace(
            "CREATE TABLE workspaces (\n", "CREATE TABLE workspaces (\n  extra_col text,\n"
        ),
        encoding="utf-8",
    )
    problems = schema_diff(
        "schema.sql", parse_ddl(tampered.read_text(encoding="utf-8")),
        "migrations", replayed_tables(rendered_sql),
    )  # fmt: skip
    assert problems == ["column workspaces.extra_col only in schema.sql"]


def test_changed_nullability_and_check_list_in_schema_sql_are_detected(
    rendered_sql: str, tmp_path: Path
) -> None:
    text = SCHEMA.read_text(encoding="utf-8")
    assert (
        "name          text NOT NULL," in text
        and "('active','proposed','merged','retired')" in text
    )
    tampered = text.replace("name          text NOT NULL,", "name          text,", 1)
    tampered = tampered.replace("('active','proposed','merged','retired')", "('active','proposed')")
    problems = schema_diff(
        "schema.sql", parse_ddl(tampered), "migrations", replayed_tables(rendered_sql)
    )
    assert len(problems) == 2
    assert any("workspaces.name" in p for p in problems)
    assert any("event_concepts.status" in p for p in problems)


def test_model_missing_a_field_is_detected(schema_tables: Tables) -> None:
    keep = {
        name: (field.annotation, ...)
        for name, field in m.WorkspaceRow.model_fields.items()
        if name != "primary_domain"
    }
    broken = create_model("WorkspaceRow", **keep)  # type: ignore[call-overload]
    problems = model_problems("workspaces", schema_tables["workspaces"], broken)
    assert problems == ["workspaces.primary_domain: column has no field in WorkspaceRow"]


def test_model_with_wrong_optional_or_enum_is_detected(schema_tables: Tables) -> None:
    fields = {name: (f.annotation, ...) for name, f in m.CaseRow.model_fields.items()}
    fields["verdict"] = (dict[str, Any], ...)  # column is nullable, field is required
    fields["stage"] = (str, ...)  # column has a CHECK list, field is not an enum
    fields["bogus"] = (int, ...)  # field without a column
    broken = create_model("CaseRow", **fields)  # type: ignore[call-overload]
    problems = model_problems("cases", schema_tables["cases"], broken)
    assert len(problems) == 3
    assert any("cases.verdict" in p for p in problems)
    assert any("cases.stage" in p for p in problems)
    assert any("cases.bogus" in p for p in problems)


def test_model_enum_with_a_missing_value_is_detected(schema_tables: Tables) -> None:
    class ShortStage(StrEnum):
        CANDIDATE = "candidate"

    fields = {name: (f.annotation, ...) for name, f in m.OutcomeRow.model_fields.items()}
    fields["stage"] = (ShortStage, ...)
    broken = create_model("OutcomeRow", **fields)  # type: ignore[call-overload]
    problems = model_problems("outcomes", schema_tables["outcomes"], broken)
    assert len(problems) == 1 and "outcomes.stage" in problems[0]


def test_seed_label_drift_is_detected(rendered_sql: str) -> None:
    tampered = rendered_sql.replace("(0, 'quote_stale',", "(0, 'quote_stalled',", 1)
    assert tampered != rendered_sql
    assert set(seed_labels(tampered)) != {e.value for e in m.EventType}
