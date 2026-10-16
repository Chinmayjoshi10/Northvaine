"""Subscription requests and the free-radar limit (D104). No payments: a person follows up.

- `POST /api/contact`: a "subscribe" or "talk to us" request, appended to `_requests.jsonl` in the
  reports folder. A hidden field (`website_url`) that people never see catches simple bots: when it
  is filled the request is accepted and dropped.
- `POST /api/trial`: claims the one free radar for an email. A second claim for the same email is
  refused (409) unless the email is listed in `_subscribers.txt` (one per line, kept by hand once a
  customer has subscribed). Claims are appended to `_trials.jsonl`.

All three files live in the reports folder, which is never committed. Emails are stored only to
reply and to enforce the limit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator

from northvaine.api import store
from northvaine.core.models import NorthvaineModel

router = APIRouter(prefix="/api", tags=["accounts"])

REQUESTS = "_requests.jsonl"
TRIALS = "_trials.jsonl"
SUBSCRIBERS = "_subscribers.txt"
_EMAIL = r"^[^@\s]{1,64}@[^@\s]{1,253}\.[A-Za-z]{2,24}$"

Plan = Literal["free", "pro", "agency"]


def reports() -> Path:
    return store.reports_dir()


Base = Annotated[Path, Depends(reports)]


def _email(value: str) -> str:
    return value.strip().lower()


class ContactIn(NorthvaineModel):
    kind: Literal["subscribe", "contact"] = "contact"
    plan: Plan | None = None
    name: str = Field(min_length=1, max_length=120)
    company: str = Field(min_length=1, max_length=200)
    email: str = Field(pattern=_EMAIL, max_length=320)
    website: str = Field(default="", max_length=300)
    message: str = Field(default="", max_length=2000)
    website_url: str = Field(default="", max_length=300)  # hidden field: bots fill it

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return _email(value)


class TrialIn(NorthvaineModel):
    email: str = Field(pattern=_EMAIL, max_length=320)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return _email(value)


class Received(NorthvaineModel):
    received: bool = True


def _append(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _subscribers(base: Path) -> set[str]:
    path = base / SUBSCRIBERS
    if not path.is_file():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {_email(x) for x in lines if x.strip() and not x.lstrip().startswith("#")}


def _trial_used(base: Path, email: str) -> bool:
    path = base / TRIALS
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            if json.loads(line).get("email") == email:
                return True
        except ValueError:
            continue
    return False


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@router.post("/contact", status_code=201)
def post_contact(body: ContactIn, base: Base) -> Received:
    if body.website_url:
        return Received()  # a bot filled the hidden field: accepted, not stored
    record = body.model_dump(exclude={"website_url"})
    record["received_at"] = _now()
    _append(base / REQUESTS, record)
    return Received()


@router.post("/trial", status_code=201)
def claim_trial(body: TrialIn, base: Base) -> dict[str, str]:
    """Claims the free radar for this email; 409 when it was already used and not subscribed."""
    if body.email in _subscribers(base):
        return {"status": "subscriber"}
    if _trial_used(base, body.email):
        raise HTTPException(
            status_code=409,
            detail="The free radar for this email has been used. Talk to us to subscribe.",
        )
    _append(base / TRIALS, {"email": body.email, "claimed_at": _now()})
    return {"status": "free"}
