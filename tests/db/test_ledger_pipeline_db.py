"""Live ledger pipeline checks (T4.5). Marked `db`; fake LLM clients, real database."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northvaine.brain import llm as llm_module
from northvaine.brain.budget import RunContext
from northvaine.core import db
from northvaine.core.models import EvidenceDocument
from northvaine.core.settings import Settings
from northvaine.radar.concepts import seed_concept_embeddings
from northvaine.radar.ledger import process_document
from tests.radar.test_ledger_pipeline import (
    EMBED,
    FAST,
    Recorder,
    full_text_replies,
    ted_doc,
    unit,
    website_doc,
)

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _llm_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        model_fast=FAST,
        model_embed=EMBED,
        daily_budget_usd=Decimal("10"),
        total_budget_usd=Decimal("20"),
        run_budget_usd=Decimal("5"),
        max_call_cost_usd=Decimal("1"),
    )
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_module.budget_module, "get_settings", lambda: settings)


@pytest_asyncio.fixture
async def maker(migrated_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = db.create_engine(migrated_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def insert_document(s: AsyncSession, doc: EvidenceDocument) -> None:
    await s.execute(
        text(
            "INSERT INTO documents (id, url, content_hash, title, text, available_at, group_key, "
            "meta) VALUES (:id, :url, :hash, :title, :text, :available_at, :group_key, "
            "CAST(:meta AS jsonb))"
        ),
        {
            "id": doc.id,
            "url": doc.url,
            "hash": str(doc.id),
            "title": doc.title,
            "text": doc.text,
            "available_at": doc.available_at,
            "group_key": doc.group_key,
            "meta": json.dumps(doc.meta, default=str),
        },
    )


async def count(s: AsyncSession, table: str) -> int:
    return (await s.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def counts(s: AsyncSession) -> tuple[int, int]:
    return await count(s, "claims"), await count(s, "events")


async def test_ted_document_is_stored_by_code_and_is_idempotent(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    doc = ted_doc()
    async with maker() as s:
        await insert_document(s, doc)
        client = Recorder()
        with llm_module.client_override(client):
            first = await process_document(s, doc, run=RunContext())
            await s.commit()
            after_first = await counts(s)
            second = await process_document(s, doc, run=RunContext())
            await s.commit()
        assert client.log == []  # structured: no chat, no embed
        assert first.llm_calls == 0 and len(first.events) == 1
        assert after_first[0] > 0 and after_first[1] == 1
        assert await counts(s) == after_first
        assert second.events[0].fingerprint == first.events[0].fingerprint

        rejected = await count(s, "claims WHERE NOT verified")
        assert rejected == 0
        claim_ids = (await s.execute(text("SELECT claim_ids FROM events"))).scalar_one()
        assert claim_ids
        verified = (
            await s.execute(
                text("SELECT count(*) FROM verified_claims WHERE id = ANY(:ids)"),
                {"ids": claim_ids},
            )
        ).scalar_one()
        assert verified == len(claim_ids)


async def test_web_document_is_stored_with_rejections_and_is_idempotent(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    doc = website_doc()
    async with maker() as s:
        await insert_document(s, doc)
        await s.commit()
        client = Recorder([*full_text_replies(), *full_text_replies()])
        client.vectors = [unit(3), unit(3)]
        with llm_module.client_override(client):
            first = await process_document(s, doc, run=RunContext())
            await s.commit()
            after_first = await counts(s)
            await process_document(s, doc, run=RunContext())
            await s.commit()
        assert first.llm_calls == 3 and len(first.events) == 1
        assert after_first[1] == 1
        assert await counts(s) == after_first

        statuses = (await s.execute(text("SELECT status FROM claims ORDER BY status"))).all()
        assert [r[0] for r in statuses] == ["quote_not_found", "verified", "verified"]
        event = (
            await s.execute(text("SELECT description, slots, concept_id, available_at FROM events"))
        ).one()
        assert "invented" not in event.description and "ghost" not in event.slots
        assert event.slots["subject_key"] == "harbourside works"
        assert event.available_at == doc.available_at
        concept = (
            await s.execute(
                text("SELECT label, status, level FROM event_concepts WHERE id = :id"),
                {"id": event.concept_id},
            )
        ).one()
        assert tuple(concept) == ("new_plant", "proposed", 1)
        assert await count(s, "event_concepts WHERE label = 'new_plant'") == 1


async def test_a_lead_writes_nothing(maker: async_sessionmaker[AsyncSession]) -> None:
    doc = EvidenceDocument(
        id=website_doc().id,
        source_name="tavily",
        url="https://x.example/lead",
        text="just a snippet",
        meta={"text_kind": "snippet"},
    )
    async with maker() as s:
        await insert_document(s, doc)
        await s.commit()
        client: Any = Recorder()
        with llm_module.client_override(client):
            result = await process_document(s, doc, run=RunContext())
        assert result.llm_calls == 0 and client.log == []
        assert await counts(s) == (0, 0)


async def test_seed_concept_embeddings_is_idempotent(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        client = Recorder()
        client.vectors = [unit(i) for i in range(12)]
        with llm_module.client_override(client):
            written = await seed_concept_embeddings(s, run=RunContext())
            await s.commit()
            again = await seed_concept_embeddings(s, run=RunContext())
        assert written == 12 and again == 0
        assert [k for k, _ in client.log] == ["embed"] * 12
        left = await count(s, "event_concepts WHERE level = 0 AND embedding IS NULL")
        assert left == 0
