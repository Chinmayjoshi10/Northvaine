"""Shared Pydantic models and enums (T1.0 contract types; T1.6 adds row models below).

The T1.0 types here are frozen for milestone 1.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NorthvaineModel(BaseModel):
    """Base for every project model: unknown fields are an error."""

    model_config = ConfigDict(extra="forbid")


class JobStatus(StrEnum):
    """Lifecycle of a row in the `jobs` table."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class NewJob(NorthvaineModel):
    """A job to enqueue. Defaults are filled by the queue or the database."""

    kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    run_after: datetime | None = None  # None = now (DB default)
    max_attempts: int | None = Field(default=None, ge=1)  # None = settings.job_max_attempts
    workspace_id: UUID | None = None


class Job(NorthvaineModel):
    """A `jobs` row exactly as stored in schema v2 (also serves as JobRow)."""

    id: int
    kind: str
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    run_after: datetime
    locked_at: datetime | None
    locked_by: str | None
    error: str | None
    workspace_id: UUID | None
    created_at: datetime
    finished_at: datetime | None


class EventType(StrEnum):
    """The generic event types of SPEC §1. Never industry-specific."""

    FACILITY_OPENED = "facility_opened"
    """A new site, plant, yard, branch or warehouse opened or announced."""
    CONTRACT_AWARDED = "contract_awarded"
    """A contract or tender award was made to the company."""
    TENDER_PUBLISHED = "tender_published"
    """The company published a tender or request for proposals."""
    HIRING_SURGE = "hiring_surge"
    """A marked rise in open roles at the company."""
    LEADERSHIP_CHANGE = "leadership_change"
    """A senior leader joined, left or changed role."""
    PRODUCT_LAUNCH = "product_launch"
    """The company launched or announced a product or service."""
    MARKET_ENTRY = "market_entry"
    """The company entered a new region or segment."""
    TRADE_MEASURE = "trade_measure"
    """A tariff, quota, duty or other trade rule changed."""
    WEBSITE_CHANGE = "website_change"
    """A material change to the company website."""
    REORDER_DUE = "reorder_due"
    """A past customer is due to reorder based on its history."""
    QUOTE_STALE = "quote_stale"
    """A quote was sent and has had no reply for too long."""
    INBOUND_QUESTION = "inbound_question"
    """A buyer or buyer agent asked a question through the Gateway."""
