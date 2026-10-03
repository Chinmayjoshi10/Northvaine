"""A small, documented DDL parser for the SQL subset Northvaine's schema uses (T1.8).

It exists so tests can compare `schema.sql`, the replayed migrations and the Pydantic models
without a database. It adds no dependency; statements come from `northvaine.core.sqlsplit`
(which already drops comments and splits on top-level `;`).

Supported constructs (anything else that looks like DDL raises `DdlParseError`; statements
that are not table DDL, such as INSERT or CREATE EXTENSION, are ignored):

* `CREATE TABLE name (...)`: columns with a type, `NOT NULL`, inline `PRIMARY KEY`, inline
  `CHECK (col IN ('a','b'))` (also `CONSTRAINT n CHECK (...)`, and over several lines), and
  table-level `PRIMARY KEY (a, b)`, `CHECK (...)`, `UNIQUE ...`, `FOREIGN KEY ...`.
* `ALTER TABLE t ADD [COLUMN] ...`, `DROP COLUMN c`, `ALTER COLUMN c TYPE x`,
  `ALTER COLUMN c SET|DROP NOT NULL`, `ADD CONSTRAINT n CHECK (c IN (...))`,
  `DROP CONSTRAINT n` (several comma-separated actions are fine).
* `CREATE VIEW name` and `CREATE [UNIQUE] INDEX name` (names only).
* `DROP TABLE`, `DROP VIEW`, `DROP INDEX`.

Rules: a column is NOT NULL when it says `NOT NULL` or is part of a PRIMARY KEY. Types are
lower-cased with no spaces around `(`, `)` and `,` (`numeric(10,6)`, `vector(1024)`, `text[]`).
`check_values` is the tuple of strings of a `CHECK (col IN ('a','b'))`, or None when the column
has no such check (other checks such as `~` or `>=` are not column value lists). The IN list
must not contain parentheses inside its strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from northvaine.core.sqlsplit import split_sql


class DdlParseError(ValueError):
    """The DDL uses a construct this parser does not support."""


@dataclass(frozen=True)
class ColumnInfo:
    type: str
    nullable: bool
    check_values: tuple[str, ...] | None = None


Tables = dict[str, dict[str, ColumnInfo]]


@dataclass
class ParsedSchema:
    tables: Tables = field(default_factory=dict)
    views: set[str] = field(default_factory=set)
    indexes: set[str] = field(default_factory=set)


_NAME = r'(?:"?[A-Za-z_]\w*"?\.)?"?([A-Za-z_]\w*)"?'
_CREATE_TABLE = re.compile(rf"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_NAME}\s*\(", re.I)
_CREATE_VIEW = re.compile(rf"^CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+{_NAME}", re.I)
_CREATE_INDEX = re.compile(
    rf"^CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?{_NAME}", re.I
)
_ALTER_TABLE = re.compile(
    rf"^ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?{_NAME}\s+(.*)$", re.I | re.S
)
_DROP = re.compile(rf"^DROP\s+(TABLE|VIEW|INDEX)\s+(?:IF\s+EXISTS\s+)?{_NAME}", re.I)

# Statements that are deliberately not table DDL. Everything else beginning CREATE/ALTER/DROP
# must be understood or raise, so a construct this parser cannot read is never silently dropped.
_IGNORABLE = re.compile(
    r"^(?:CREATE|DROP)\s+(?:EXTENSION|SCHEMA)\b"
    r"|^ALTER\s+(?:EXTENSION|SCHEMA|DATABASE)\b",
    re.I,
)
_ANY_DDL = re.compile(r"^(?:CREATE|ALTER|DROP)\b", re.I)
_TABLE_ITEM = re.compile(
    r"^(?:CONSTRAINT\s+\S+\s+)?(PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY|EXCLUDE)\b", re.I
)
_CONSTRAINT_NAME = re.compile(
    r"\bCONSTRAINT\s+\"?(\w+)\"?\s+(?:CHECK|PRIMARY|UNIQUE|FOREIGN)", re.I
)
_COLUMN_KEYWORD = re.compile(
    r"\b(?:NOT\s+NULL|NULL|PRIMARY\s+KEY|DEFAULT|REFERENCES|CHECK|CONSTRAINT|UNIQUE|GENERATED|COLLATE)\b",
    re.I,
)
_CHECK_IN = re.compile(r"CHECK\s*\(\s*\"?(\w+)\"?\s+IN\s*\(([^()]*)\)\s*\)", re.I)
_PK_COLUMNS = re.compile(r"PRIMARY\s+KEY\s*\(([^()]*)\)", re.I)


def _mask(text: str) -> str:
    """Return `text` with everything inside quotes or parentheses replaced by `_`.

    Positions are preserved, so a search on the masked text finds only top-level tokens and
    the hit can be sliced out of the original.
    """
    out: list[str] = []
    depth = 0
    quote = ""
    for ch in text:
        if quote:
            out.append("_")
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            out.append("_")
        elif ch == "(":
            depth += 1
            out.append("_")
        elif ch == ")":
            depth = max(depth - 1, 0)
            out.append("_")
        else:
            out.append("_" if depth else ch)
    return "".join(out)


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are outside parentheses and quotes; each part is stripped."""
    masked = _mask(text)
    parts: list[str] = []
    start = 0
    for index, ch in enumerate(masked):
        if ch == ",":
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def _matching_paren(text: str, open_index: int) -> int:
    depth = 0
    quote = ""
    for index in range(open_index, len(text)):
        ch = text[index]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return index
    raise DdlParseError(f"unbalanced parentheses in: {text[:80]!r}")


def normalize_type(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw.strip().lower())
    return re.sub(r"\s*([(),])\s*", r"\1", cleaned)


def _check_values(raw: str) -> tuple[str, ...]:
    return tuple(re.findall(r"'((?:[^']|'')*)'", raw))


class _Builder:
    def __init__(self) -> None:
        self.schema = ParsedSchema()
        self._constraint_column: dict[tuple[str, str], str] = {}

    # --- columns and constraints -------------------------------------------------------
    def _set_check(self, table: str, item: str) -> None:
        columns = self.schema.tables[table]
        name_match = _CONSTRAINT_NAME.search(item)
        for column, raw in _CHECK_IN.findall(item):
            column = column.lower()
            if column not in columns:
                raise DdlParseError(f"CHECK on unknown column {table}.{column}")
            columns[column] = replace(columns[column], check_values=_check_values(raw))
            if name_match:
                self._constraint_column[(table, name_match.group(1).lower())] = column

    def _parse_column(self, table: str, item: str) -> None:
        match = re.match(r'"?([A-Za-z_]\w*)"?\s+(.*)$', item, re.S)
        if not match:
            raise DdlParseError(f"cannot read column definition: {item!r}")
        name, rest = match.group(1).lower(), match.group(2)
        masked = _mask(rest)
        keyword = _COLUMN_KEYWORD.search(masked)
        type_text = rest if keyword is None else rest[: keyword.start()]
        if not type_text.strip():
            raise DdlParseError(f"column {table}.{name} has no type: {item!r}")
        flags = masked.upper()
        nullable = not (
            re.search(r"\bNOT\s+NULL\b", flags) or re.search(r"\bPRIMARY\s+KEY\b", flags)
        )
        self.schema.tables[table][name] = ColumnInfo(normalize_type(type_text), nullable)
        self._set_check(table, item)

    def _table_item(self, table: str, item: str) -> None:
        columns = self.schema.tables[table]
        for group in _PK_COLUMNS.findall(item):
            for column in (c.strip().strip('"').lower() for c in group.split(",")):
                if column not in columns:
                    raise DdlParseError(f"PRIMARY KEY on unknown column {table}.{column}")
                columns[column] = replace(columns[column], nullable=False)
        self._set_check(table, item)

    def _add(self, table: str, item: str) -> None:
        if _TABLE_ITEM.match(item):
            self._table_item(table, item)
            return
        item = re.sub(r"^COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?", "", item, flags=re.I)
        self._parse_column(table, item)

    # --- statements --------------------------------------------------------------------
    def create_table(self, table: str, statement: str, match: re.Match[str]) -> None:
        open_index = match.end() - 1
        body = statement[open_index + 1 : _matching_paren(statement, open_index)]
        self.schema.tables[table] = {}
        for item in _split_top_level(body):
            if _TABLE_ITEM.match(item):
                self._table_item(table, item)
            else:
                self._parse_column(table, item)

    def alter_table(self, table: str, actions: str) -> None:
        if table not in self.schema.tables:
            raise DdlParseError(f"ALTER TABLE on unknown table {table}")
        columns = self.schema.tables[table]
        for action in _split_top_level(actions):
            if m := re.match(r"ADD\s+(.*)$", action, re.I | re.S):
                self._add(table, m.group(1))
            elif m := re.match(r"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?", action, re.I):
                columns.pop(m.group(1).lower(), None)
            elif m := re.match(r"DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?", action, re.I):
                column = self._constraint_column.pop((table, m.group(1).lower()), None)
                if column in columns:
                    columns[column] = replace(columns[column], check_values=None)
            elif m := re.match(
                r"ALTER\s+(?:COLUMN\s+)?\"?(\w+)\"?\s+(?:SET\s+DATA\s+)?TYPE\s+(.*)$",
                action,
                re.I | re.S,
            ):
                column = self._column(table, m.group(1))
                new_type = re.split(r"\bUSING\b", m.group(2), flags=re.I)[0]
                columns[column] = replace(columns[column], type=normalize_type(new_type))
            elif m := re.match(
                r"ALTER\s+(?:COLUMN\s+)?\"?(\w+)\"?\s+(SET|DROP)\s+NOT\s+NULL", action, re.I
            ):
                column = self._column(table, m.group(1))
                columns[column] = replace(columns[column], nullable=m.group(2).upper() == "DROP")
            else:
                raise DdlParseError(f"unsupported ALTER TABLE action on {table}: {action!r}")

    def _column(self, table: str, name: str) -> str:
        name = name.lower()
        if name not in self.schema.tables[table]:
            raise DdlParseError(f"unknown column {table}.{name}")
        return name

    def statement(self, statement: str) -> None:
        if m := _CREATE_TABLE.match(statement):
            self.create_table(m.group(1).lower(), statement, m)
        elif m := _CREATE_VIEW.match(statement):
            self.schema.views.add(m.group(1).lower())
        elif m := _CREATE_INDEX.match(statement):
            self.schema.indexes.add(m.group(1).lower())
        elif m := _ALTER_TABLE.match(statement):
            self.alter_table(m.group(1).lower(), m.group(2))
        elif m := _DROP.match(statement):
            kind, name = m.group(1).upper(), m.group(2).lower()
            if kind == "TABLE":
                self.schema.tables.pop(name, None)
            elif kind == "VIEW":
                self.schema.views.discard(name)
            else:
                self.schema.indexes.discard(name)
        elif _IGNORABLE.match(statement):
            pass  # not table DDL: CREATE EXTENSION, INSERT, BEGIN, COMMIT, UPDATE, ...
        elif _ANY_DDL.match(statement):
            # M1 carry-over 1. A CREATE/ALTER/DROP form this parser does not understand used to
            # fall through silently, so schema.sql and the migrations could disagree about a
            # construct neither side had ever read. Every consistency test built on this parser
            # would then pass while comparing two incomplete pictures.
            raise DdlParseError(
                "unsupported DDL form; the parser would otherwise ignore it and every schema "
                "consistency check built on it would compare incomplete pictures: "
                f"{statement[:160]!r}"
            )


def parse_schema(sql: str) -> ParsedSchema:
    """Parse a script (or a rendered Alembic offline script) into tables, views and indexes."""
    builder = _Builder()
    for statement in split_sql(sql):
        builder.statement(statement)
    return builder.schema


def parse_ddl(sql: str) -> Tables:
    """Return `{table: {column: ColumnInfo}}` for the script, applying ALTERs in order."""
    return parse_schema(sql).tables
