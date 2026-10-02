"""Split a PostgreSQL script into single statements (used by migrations).

asyncpg prepares every statement, and PostgreSQL refuses several commands in one prepared
statement, so a migration must run a script one statement at a time.

`split_sql` drops `--` line comments and `/* ... */` block comments (nested, as PostgreSQL
allows) and splits on top-level `;`. It respects single-quoted strings (with `''` and, for
`E'...'` strings, backslash escapes), double-quoted identifiers and `$tag$ ... $tag$` dollar
quotes. Each returned statement is stripped and has no trailing `;`. Empty ones are dropped.
"""

from __future__ import annotations

import re

_DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$"


def _end_of_single_quote(text: str, start: int) -> int:
    """Return the index just past the string literal whose opening quote is at `start`."""
    escapes = (
        start > 0
        and text[start - 1] in "eE"
        and (start == 1 or not _is_ident_char(text[start - 2]))
    )
    i = start + 1
    n = len(text)
    while i < n:
        ch = text[i]
        if escapes and ch == "\\":
            i += 2
            continue
        if ch == "'":
            if i + 1 < n and text[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _end_of_double_quote(text: str, start: int) -> int:
    """Return the index just past the quoted identifier opened at `start`."""
    i = start + 1
    n = len(text)
    while i < n:
        if text[i] == '"':
            if i + 1 < n and text[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _end_of_block_comment(text: str, start: int) -> int:
    """Return the index just past the (possibly nested) block comment opened at `start`."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        pair = text[i : i + 2]
        if pair == "/*":
            depth += 1
            i += 2
        elif pair == "*/":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return n


def split_sql(text: str) -> list[str]:
    """Split `text` into statements without comments or trailing semicolons."""
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(text)

    def flush() -> None:
        statement = "".join(current).strip()
        if statement:
            statements.append(statement)
        current.clear()

    while i < n:
        ch = text[i]
        if ch == "-" and text.startswith("--", i):
            newline = text.find("\n", i)
            i = n if newline == -1 else newline
        elif ch == "/" and text.startswith("/*", i):
            i = _end_of_block_comment(text, i)
            current.append(" ")
        elif ch == "'":
            end = _end_of_single_quote(text, i)
            current.append(text[i:end])
            i = end
        elif ch == '"':
            end = _end_of_double_quote(text, i)
            current.append(text[i:end])
            i = end
        elif ch == "$" and (i == 0 or not _is_ident_char(text[i - 1])):
            match = _DOLLAR_TAG.match(text, i)
            if match is None:
                current.append(ch)
                i += 1
                continue
            tag = match.group(0)
            close = text.find(tag, match.end())
            end = n if close == -1 else close + len(tag)
            current.append(text[i:end])
            i = end
        elif ch == ";":
            flush()
            i += 1
        else:
            current.append(ch)
            i += 1
    flush()
    return statements
