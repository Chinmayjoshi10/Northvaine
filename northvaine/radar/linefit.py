"""Which of the client's catalogue lines a company sells (D119).

Free page reading (see `fit.py`) gives each company a few product pages. The FAST model then says,
per company, which catalogue lines the pages show, with a quote. Code checks the quote against the
page text (rule 2): a "yes" without a verbatim quote is dropped to "unclear". Never fails a run.
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

__all__ = ["LineFitOutput", "LineJudgement", "VerifiedLine", "judge_lines", "pages_for_judge"]

MIN_QUOTE = 12


class LineJudgement(NorthvaineModel):
    line: str
    verdict: Literal["yes", "no", "unclear"]
    quote: str = ""


class LineFitOutput(NorthvaineModel):
    what_it_sells: str = ""
    lines: list[LineJudgement] = Field(default_factory=list)


class VerifiedLine(NorthvaineModel):
    """A "yes" whose quote code found in the page text: the page's own substring."""

    line: str
    url: str
    quote: str


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


async def judge_lines(
    name: str,
    pages: list[tuple[str, str]],
    spec: ClientSpec,
    *,
    run: RunContext,
    session: Any = None,
    settings: Settings | None = None,
) -> list[VerifiedLine]:
    """The verified lines for one company. Raises the model errors; the caller decides."""
    cfg = settings or get_settings()
    # Imported here: brain.llm pulls in the SDK (httpx), which module import must not do.
    from northvaine.brain.llm import complete_json

    sent = pages_for_judge(pages, cfg.radar_fit_judge_chars)
    if not sent or not spec.catalogue_lines:
        return []
    lines_text = "\n".join(f"{ln.name}: {', '.join(ln.terms)}" for ln in spec.catalogue_lines)
    pages_text = "\n\n".join(f"URL: {url}\n{text}" for url, text in sent)
    result = await complete_json(
        tier=ModelTier.FAST,
        prompt=load_prompt("radar_line_fit", version=1),
        variables={
            "offer": spec.offer,
            "lines": lines_text,
            "company_name": Untrusted(name),
            "pages": Untrusted(pages_text),
        },
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
        quote = _collapse(item.quote)
        if len(quote) < MIN_QUOTE:
            continue
        # whitespace-insensitive, but the kept quote is the page's own substring
        pattern = re.compile(r"\s+".join(re.escape(w) for w in quote.split()))
        for url, text in sent:
            found = pattern.search(text)
            if found is not None:
                out[line] = VerifiedLine(line=line, url=url, quote=found.group(0))
                break
    return [out[ln.name] for ln in spec.catalogue_lines if ln.name in out]
