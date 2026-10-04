"""Identify the company (T5.2, D58-D60): one candidate per company, from verified claims only.

Code only: never imports `northvaine.brain.llm` (checked by scripts/check_invariants.py).
"""

from __future__ import annotations

from datetime import date

from northvaine.core.models import EvidenceDocument, LedgerResult
from northvaine.core.settings import Settings
from northvaine.radar.models import Candidate, CandidateEvent, RadarStream, RejectedEntry

__all__ = ["build_candidates", "company_key", "stream_for", "window_for"]


def company_key(name: str, country: str | None, settings: Settings | None = None) -> str:
    """Match key (D58): NFKC, casefold, punctuation stripped, legal-form tokens removed
    (`settings.radar_legal_forms`), joined with the ISO2 country."""
    raise NotImplementedError("T5.2")


def stream_for(source_name: str, event_type: str, settings: Settings | None = None) -> RadarStream:
    """Stream of one event (D60): `radar_stream_by_event` first, else announcement."""
    raise NotImplementedError("T5.2")


def window_for(
    stream: RadarStream, events: list[CandidateEvent], settings: Settings | None = None
) -> tuple[date | None, date | None, bool, str]:
    """(window_start, window_end, estimated, note) per D60 and D27."""
    raise NotImplementedError("T5.2")


def build_candidates(
    results: list[tuple[EvidenceDocument, LedgerResult]], *, settings: Settings | None = None
) -> tuple[list[Candidate], list[RejectedEntry]]:
    """One candidate per company key; rejected holds UNIDENTIFIED events only (rule #3, D62)."""
    raise NotImplementedError("T5.2")
