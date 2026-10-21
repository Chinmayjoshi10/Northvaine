"""Which of the client's catalogue lines a company sells, and what it is (D119-D121).

Free page reading (see `fit.py`) gives each company a few product pages. The FAST model then says,
per company, which catalogue lines the pages show, with a quote, and (D120) whether the company
makes, resells or uses this kind of product. Code checks every quote against the page text
(rule 2): a "yes" without a verbatim quote is dropped to "unclear". Never fails a run.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field

from northvaine.brain.budget import RunContext
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import load_prompt
from northvaine.core.models import ModelTier, NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.models import ClientSpec

__all__ = [
    "JudgeResult",
    "LineFitOutput",
    "LineJudgement",
    "VerifiedLine",
    "judge_lines",
    "pages_for_judge",
]

MIN_QUOTE = 12
MIN_BRAND = 2
MAX_BRANDS = 10

Role = Literal["makes", "resells", "uses", "other", "unclear"]


class LineJudgement(NorthvaineModel):
    line: str
    verdict: Literal["yes", "no", "unclear"]
    quote: str = ""


class LineFitOutput(NorthvaineModel):
    what_it_sells: str = ""
    role: Role = "unclear"  # D120 (prompt v2)
    role_quote: str = ""
    brands: list[str] = Field(default_factory=list)  # D121 (prompt v3)
    lines: list[LineJudgement] = Field(default_factory=list)


class VerifiedLine(NorthvaineModel):
    """A "yes" whose quote code found in the page text: the page's own substring."""

    line: str
    url: str
    quote: str


class JudgeResult(NorthvaineModel):
    """Verified lines, and the company's role when its quote was found on the pages (D120)."""

    lines: list[VerifiedLine] = Field(default_factory=list)
    role: Role = "unclear"
    role_url: str = ""
    role_quote: str = ""
    brands: list[str] = Field(default_factory=list)  # D121: the page's own spelling, verified
    own_brand: str = ""  # D121: set by the own-name rule in fit.py, never by the model


def _collapse(text: str) -> str:
    return " ".join(text.split())


def pages_for_judge(pages: list[tuple[str, str]], limit: int) -> list[tuple[str, str]]:
    """The (url, text) pages as they are sent: in the given order, each with its URL header,
    cut to `limit` characters in total. Returns the pieces actually sent, so a quote is checked
    against exactly what the model saw."""
    sent: list[tuple[str, str]] = []
    left = limit
    for url, text in pages:
        header = f"URL: {url}\n"
        room = left - len(header)
        if room <= 0:
            break
        piece = text[:room]
        sent.append((url, piece))
        left -= len(header) + len(piece) + 1
    return sent


def _find_quote(raw: str, sent: list[tuple[str, str]]) -> tuple[str, str] | None:
    """(url, the page's own substring) when the quote is on a page sent, else None."""
    quote = _collapse(raw)
    if len(quote) < MIN_QUOTE:
        return None
    # whitespace-insensitive, but the kept quote is the page's own substring
    pattern = re.compile(r"\s+".join(re.escape(w) for w in quote.split()))
    for url, text in sent:
        found = pattern.search(text)
        if found is not None:
            return url, found.group(0)
    return None


def _verified_brands(raw: list[str], sent: list[tuple[str, str]]) -> list[str]:
    """Brands found in the text sent (casefolded, whitespace-collapsed), as the page spells them.
    At most MAX_BRANDS, deduplicated casefolded (D121)."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        brand = _collapse(item)
        if len(brand) < MIN_BRAND or brand.casefold() in seen:
            continue
        pattern = re.compile(r"\s+".join(re.escape(w) for w in brand.split()), re.IGNORECASE)
        for _, text in sent:
            found = pattern.search(text)
            if found is not None:
                seen.add(brand.casefold())
                out.append(_collapse(found.group(0)))
                break
        if len(out) >= MAX_BRANDS:
            break
    return out


async def judge_lines(
    name: str,
    pages: list[tuple[str, str]],
    spec: ClientSpec,
    *,
    run: RunContext,
    session: Any = None,
    settings: Settings | None = None,
) -> JudgeResult:
    """The verified lines and role for one company. Raises the model errors; the caller decides."""
    cfg = settings or get_settings()
    # Imported here: brain.llm pulls in the SDK (httpx), which module import must not do.
    from northvaine.brain.llm import complete_json

    with_role = cfg.radar_fit_judge_role
    with_brands = with_role and cfg.radar_fit_judge_brands  # D121
    sent = pages_for_judge(pages, cfg.radar_fit_judge_chars)
    if not sent or not (spec.catalogue_lines or with_role):
        return JudgeResult()
    lines_text = "\n".join(f"{ln.name}: {', '.join(ln.terms)}" for ln in spec.catalogue_lines)
    pages_text = "\n\n".join(f"URL: {url}\n{text}" for url, text in sent)
    variables: dict[str, Any] = {
        "offer": spec.offer,
        "lines": lines_text or "none listed",
        "company_name": Untrusted(name),
        "pages": Untrusted(pages_text),
    }
    if with_role:
        variables["not_buyers"] = "; ".join(spec.not_buyers) or "not stated"
    result = await complete_json(
        tier=ModelTier.FAST,
        prompt=load_prompt("radar_line_fit", version=3 if with_brands else (2 if with_role else 1)),
        variables=variables,
        output_model=LineFitOutput,
        purpose="radar_line_fit",
        run=run,
        workspace_id=run.workspace_id,
        session=session,
        max_tokens=cfg.radar_fit_judge_max_tokens,
    )
    names = {ln.name.casefold(): ln.name for ln in spec.catalogue_lines}
    out: dict[str, VerifiedLine] = {}
    for item in result.value.lines:
        line = names.get(item.line.strip().casefold())
        if line is None or item.verdict != "yes" or line in out:
            continue
        found = _find_quote(item.quote, sent)
        if found is not None:
            out[line] = VerifiedLine(line=line, url=found[0], quote=found[1])
    verified = [out[ln.name] for ln in spec.catalogue_lines if ln.name in out]
    brands = _verified_brands(result.value.brands, sent) if with_brands else []
    role: Role = result.value.role if with_role else "unclear"
    if role in ("makes", "resells", "uses"):
        found = _find_quote(result.value.role_quote, sent)
        if found is not None:
            return JudgeResult(
                lines=verified, role=role, role_url=found[0], role_quote=found[1], brands=brands
            )
        role = "unclear"
    return JudgeResult(lines=verified, role=role, brands=brands)
