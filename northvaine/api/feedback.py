"""Owner feedback on one entry: validated, then appended to a JSON-lines file (never edited)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from northvaine.api import store
from northvaine.core.models import NorthvaineModel

router = APIRouter(prefix="/api", tags=["feedback"])

# Same chips as the scorecard (radar/brief.py _FAILURE_CHIPS); kept literal so the schema is static.
FailureChip = Literal[
    "wrong company",
    "not a buyer",
    "competitor/publisher let through",
    "stale/closed window",
    "wrong fact",
    "not actionable",
]
Outcome = Literal["none", "redirect", "info request", "requirement", "sample", "quote", "meeting"]


class FeedbackIn(NorthvaineModel):
    client: str = Field(min_length=1, max_length=64)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    rank: int = Field(ge=1)
    company: str = Field(max_length=300)
    # The scorecard questions.
    correct: bool | None = None
    relevant: bool | None = None
    new: bool | None = None
    actionable: bool | None = None
    failure_chip: FailureChip | None = None
    # After contact. `accepted_for_contact` is the salesperson's disposition (D95).
    accepted_for_contact: bool | None = None
    known_already: bool | None = None
    new_intelligence: bool | None = None
    contacted: bool | None = None
    outcome: Outcome | None = None
    note: str = Field(default="", max_length=2000)


class FeedbackRecord(FeedbackIn):
    received_at: datetime


def reports() -> Path:
    return store.reports_dir()


Base = Annotated[Path, Depends(reports)]


@router.post("/feedback", status_code=201)
def post_feedback(body: FeedbackIn, base: Base) -> FeedbackRecord:
    run, _ = store.load_run(base, body.client, body.as_of)
    if not any(e.rank == body.rank for e in run.entries):
        raise HTTPException(status_code=404, detail="entry not found")
    stamp = datetime.now(UTC).replace(microsecond=0)
    record = FeedbackRecord(**body.model_dump(), received_at=stamp)
    store.append_feedback(base, body.client, record.model_dump_json())
    return record


@router.get("/clients/{client}/feedback")
def get_feedback(client: str, as_of: str, base: Base) -> list[FeedbackRecord]:
    """Feedback for one run, oldest first; the page shows the latest per entry."""
    store.check_day(as_of)
    rows = store.read_feedback(base, client)
    return [FeedbackRecord.model_validate(r) for r in rows if r.get("as_of") == as_of]
