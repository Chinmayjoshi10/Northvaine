"""HTML to plain text and link extraction (T3.2). Pure; stores text as data, never obeys it."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

_SKIP = {"script", "style", "noscript", "template"}
_BLOCK = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header",
    "footer", "nav", "main", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
}  # fmt: skip


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.skip_depth = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip_depth += 1
        elif tag == "title":
            self.in_title = True
        elif tag in _BLOCK:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag == "title":
            self.in_title = False
        elif tag in _BLOCK:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        elif not self.skip_depth:
            self.parts.append(data)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.hrefs.append(value.strip())


def html_to_text(html: str) -> tuple[str | None, str]:
    """(title, plain text) with scripts, styles and markup removed, whitespace normalized."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    title = " ".join("".join(parser.title_parts).split()) or None
    text = " ".join("".join(parser.parts).split())
    return title, text


def extract_links(html: str, base_url: str) -> list[str]:
    """Absolute http(s) links found in `html`, resolved against `base_url`, fragments dropped."""
    parser = _LinkParser()
    parser.feed(html)
    parser.close()
    seen: dict[str, None] = {}
    for href in parser.hrefs:
        absolute, _ = urldefrag(urljoin(base_url, href))
        if urlsplit(absolute).scheme in ("http", "https"):
            seen.setdefault(absolute)
    return list(seen)
