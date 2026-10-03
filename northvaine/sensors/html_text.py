"""HTML to plain text and link extraction (T3.2). Pure; stores text as data, never obeys it."""

from __future__ import annotations


def html_to_text(html: str) -> tuple[str | None, str]:
    """(title, plain text) with scripts, styles and markup removed. T3.2."""
    raise NotImplementedError("T3.2")


def extract_links(html: str, base_url: str) -> list[str]:
    """Absolute http(s) links found in `html`, resolved against `base_url`. T3.2."""
    raise NotImplementedError("T3.2")
