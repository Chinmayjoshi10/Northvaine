"""T4.5: concept assignment, clustering and seed embeddings. Injected vectors, no network."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from northvaine.brain import llm as llm_module
from northvaine.brain.budget import RunContext
from northvaine.core.models import (
    ClusterCandidate,
    ConceptStatus,
    EventConceptRow,
    EventDraft,
)
from northvaine.core.settings import Settings
from northvaine.radar.concepts import (
    assign_cluster,
    assign_concept,
    cosine,
    seed_concept_embeddings,
)

SETTINGS = Settings(_env_file=None)


def concept(
    label: str,
    *,
    parent: UUID | None = None,
    embedding: list[float] | None = None,
    status: ConceptStatus = ConceptStatus.ACTIVE,
) -> EventConceptRow:
    return EventConceptRow(
        id=uuid4(),
        parent_id=parent,
        level=0 if parent is None else 1,
        label=label,
        description=f"description of {label}",
        embedding=embedding,
        status=status,
        merged_into=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def draft(event_type: str = "facility_opened", **kw: Any) -> EventDraft:
    return EventDraft(event_type=event_type, claim_indices=[0], **kw)


# --- cosine ----------------------------------------------------------------------------------


def test_cosine_basics() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)
    assert cosine([0, 0], [1, 1]) == 0.0
    with pytest.raises(ValueError):
        cosine([1], [1, 2])


# --- assign_concept --------------------------------------------------------------------------


def test_no_embedding_returns_the_level_zero_parent() -> None:
    parent = concept("facility_opened")
    got = assign_concept(draft(concept_label="new_yard"), None, [parent], settings=SETTINGS)
    assert (got.concept_id, got.level, got.label, got.is_new) == (parent.id, 0, parent.label, False)


def test_unknown_type_is_refused() -> None:
    with pytest.raises(ValueError):
        assign_concept(draft("nope"), [1.0, 0.0], [concept("facility_opened")], settings=SETTINGS)


def test_nearest_child_above_threshold_is_picked() -> None:
    parent = concept("facility_opened")
    near = concept("new_plant", parent=parent.id, embedding=[1.0, 0.1])
    far = concept("new_yard", parent=parent.id, embedding=[0.0, 1.0])
    proposed = concept(
        "new_depot", parent=parent.id, embedding=[1.0, 0.3], status=ConceptStatus.PROPOSED
    )
    got = assign_concept(
        draft(concept_label="something_else"),
        [1.0, 0.05],
        [parent, far, proposed, near],
        settings=SETTINGS,
    )
    assert got.concept_id == near.id and got.level == 1 and not got.is_new
    assert got.parent_id == parent.id


def test_a_proposed_child_can_match() -> None:
    parent = concept("facility_opened")
    proposed = concept(
        "new_depot", parent=parent.id, embedding=[1.0, 0.0], status=ConceptStatus.PROPOSED
    )
    got = assign_concept(draft(), [1.0, 0.0], [parent, proposed], settings=SETTINGS)
    assert got.concept_id == proposed.id and got.status == "proposed"


def test_below_threshold_proposes_a_new_child_named_by_the_extractor() -> None:
    parent = concept("facility_opened")
    far = concept("new_yard", parent=parent.id, embedding=[0.0, 1.0])
    got = assign_concept(
        draft(concept_label="solar_farm", concept_hint="A solar generation site"),
        [1.0, 0.0],
        [parent, far],
        settings=SETTINGS,
    )
    assert got.is_new and got.concept_id is None
    assert (got.label, got.level, got.parent_id, got.status) == (
        "solar_farm",
        1,
        parent.id,
        "proposed",
    )
    assert got.description == "A solar generation site"
    assert got.embedding == [1.0, 0.0]


def test_new_child_without_hint_gets_a_generic_description() -> None:
    parent = concept("facility_opened")
    got = assign_concept(draft(concept_label="solar_farm"), [1.0], [parent], settings=SETTINGS)
    assert got.is_new and "solar farm" in got.description and "facility opened" in got.description


def test_no_label_and_no_match_returns_the_parent() -> None:
    parent = concept("facility_opened")
    got = assign_concept(draft(), [1.0, 0.0], [parent], settings=SETTINGS)
    assert got.concept_id == parent.id and got.level == 0 and not got.is_new


def test_a_label_that_is_not_snake_case_is_ignored() -> None:
    parent = concept("facility_opened")
    got = assign_concept(draft(concept_label="Not Snake"), [1.0], [parent], settings=SETTINGS)
    assert got.concept_id == parent.id


def test_an_existing_child_with_the_same_label_is_reused() -> None:
    parent = concept("facility_opened")
    child = concept("solar_farm", parent=parent.id, embedding=[0.0, 1.0])
    got = assign_concept(
        draft(concept_label="solar_farm"), [1.0, 0.0], [parent, child], settings=SETTINGS
    )
    assert got.concept_id == child.id and not got.is_new


# --- assign_cluster --------------------------------------------------------------------------


def cand(
    cluster: UUID | None = None,
    *,
    event_type: str = "tender_published",
    on: date | None = date(2026, 6, 1),
    subject: str | None = None,
    group: str | None = None,
    embedding: list[float] | None = None,
) -> ClusterCandidate:
    return ClusterCandidate(
        event_id=uuid4(),
        cluster_id=cluster or uuid4(),
        event_type=event_type,
        occurred_on=on,
        subject_key=subject,
        group_key=group,
        embedding=embedding,
    )


def test_embedding_cluster_needs_type_subject_window_and_cosine() -> None:
    other = cand(subject="stadt a", embedding=[1.0, 0.0])
    new = cand(subject="Stadt A", on=date(2026, 6, 20), embedding=[1.0, 0.1])
    assert assign_cluster(new, [other], settings=SETTINGS) == other.cluster_id


@pytest.mark.parametrize(
    "mutation",
    [
        {"event_type": "contract_awarded"},
        {"subject": "someone else"},
        {"on": date(2026, 9, 1)},  # outside 30 days
        {"on": None},
        {"embedding": [0.0, 1.0]},  # cosine too low
    ],
)
def test_embedding_cluster_rejects_each_mismatch(mutation: dict[str, Any]) -> None:
    other = cand(subject="stadt a", embedding=[1.0, 0.0])
    fields: dict[str, Any] = {
        "subject": "stadt a",
        "on": date(2026, 6, 10),
        "embedding": [1.0, 0.0],
    }
    fields.update(mutation)
    assert assign_cluster(cand(**fields), [other], settings=SETTINGS) != other.cluster_id


def test_embedding_cluster_matches_on_group_key() -> None:
    other = cand(group="proc-1", embedding=[1.0, 0.0])
    new = cand(group="PROC-1", on=date(2026, 6, 5), embedding=[1.0, 0.0])
    assert assign_cluster(new, [other], settings=SETTINGS) == other.cluster_id


def test_two_undated_events_match_only_with_the_same_group_key() -> None:
    a = cand(on=None, subject="x", embedding=[1.0, 0.0])
    assert assign_cluster(cand(on=None, subject="x", embedding=[1.0, 0.0]), [a]) != a.cluster_id
    b = cand(on=None, group="g", embedding=[1.0, 0.0])
    assert assign_cluster(cand(on=None, group="g", embedding=[1.0, 0.0]), [b]) == b.cluster_id


def test_without_embeddings_two_ted_versions_of_one_procedure_share_a_cluster() -> None:
    first = cand(group="proc-100", on=date(2026, 6, 1))
    second = cand(group="proc-100", on=date(2026, 8, 30))  # beyond the window, same group
    assert assign_cluster(second, [first], settings=SETTINGS) == first.cluster_id


def test_without_embeddings_subject_and_window_match() -> None:
    first = cand(subject="stadt a", on=date(2026, 6, 1))
    near = cand(subject="Stadt A", on=date(2026, 6, 15))
    far = cand(subject="stadt a", on=date(2026, 12, 1))
    other_type = cand(event_type="contract_awarded", subject="stadt a")
    assert assign_cluster(near, [first], settings=SETTINGS) == first.cluster_id
    assert assign_cluster(far, [first], settings=SETTINGS) != first.cluster_id
    assert assign_cluster(near, [other_type], settings=SETTINGS) != other_type.cluster_id


def test_one_sided_embedding_falls_back_to_deterministic_rules() -> None:
    first = cand(group="g", embedding=None)
    new = cand(group="g", embedding=[1.0, 0.0])
    assert assign_cluster(new, [first], settings=SETTINGS) == first.cluster_id


def test_no_candidates_gives_a_fresh_cluster() -> None:
    assert isinstance(assign_cluster(cand(group="g"), [], settings=SETTINGS), UUID)
    a, b = cand(group="g"), cand(group="g")
    assert assign_cluster(a, [], settings=SETTINGS) != assign_cluster(b, [], settings=SETTINGS)


def test_the_best_cosine_wins() -> None:
    weak = cand(subject="s", embedding=[1.0, 0.45])
    strong = cand(subject="s", embedding=[1.0, 0.05])
    got = assign_cluster(cand(subject="s", embedding=[1.0, 0.0]), [weak, strong], settings=SETTINGS)
    assert got == strong.cluster_id


# --- seed_concept_embeddings -----------------------------------------------------------------


class FakeEmbeddings:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def create(self, **body: Any) -> Any:
        self.requests.append(body)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.5] * llm_module.EMBED_DIM_EXPECTED)],
            usage=SimpleNamespace(prompt_tokens=8, total_tokens=8),
        )


async def test_seed_embeds_only_level_zero_without_embedding_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from northvaine.core import ledger as store

    settings = Settings(
        _env_file=None,
        model_embed="Qwen/Qwen3-Embedding-8B",
        daily_budget_usd=Decimal("10"),
        total_budget_usd=Decimal("20"),
        run_budget_usd=Decimal("5"),
        max_call_cost_usd=Decimal("1"),
    )
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_module.budget_module, "get_settings", lambda: settings)

    a, b = concept("facility_opened"), concept("tender_published")
    done = concept("product_launch", embedding=[1.0])
    rows = {c.id: c for c in (a, b, done)}

    async def load_concepts(session: Any, *, statuses: Any = ("active", "proposed")) -> Any:
        assert tuple(statuses) == ("active",)
        return list(rows.values())

    async def set_concept_embedding(session: Any, concept_id: UUID, embedding: Any) -> None:
        rows[concept_id] = rows[concept_id].model_copy(update={"embedding": list(embedding)})

    monkeypatch.setattr(store, "load_concepts", load_concepts)
    monkeypatch.setattr(store, "set_concept_embedding", set_concept_embedding)

    client = SimpleNamespace(embeddings=FakeEmbeddings())
    with llm_module.client_override(client):
        assert await seed_concept_embeddings(None, run=RunContext()) == 2
        assert len(client.embeddings.requests) == 2
        assert await seed_concept_embeddings(None, run=RunContext()) == 0
        assert len(client.embeddings.requests) == 2
    assert rows[a.id].embedding is not None and rows[done.id].embedding == [1.0]
