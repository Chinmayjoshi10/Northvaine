"""Learning loop v0, the database side (D89): labels in, a strategy version out.

`learn` reads every rating of a workspace's briefed cases, joins each one to the decision that
briefed it (which sources, queries and country found it, D87), fits the posteriors
(`radar.learning`) and writes:
- one `beliefs` row per learned key, at a new `strategy_version`, each limited by the trust
  region against the previous version;
- one `strategy_versions` row: a snapshot of all beliefs and a plain-language list of changes.

Nothing is overwritten, so going back is pointing at an earlier version (`load_strategy` with
`version`).

Simulated labels (`feedback.source = 'simulated'`) are counted only when the caller passes
`simulated=True`, and are meant for a simulated workspace; an owner's workspace never learns
from them (D79).
"""

from __future__ import annotations

import json
import random
from typing import Any
from uuid import UUID

from northvaine.core.models import FeedbackRating, LabelSource, NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.learning import (
    Beta,
    Label,
    Posteriors,
    fit_posteriors,
    pause_suggestions,
    trust_region,
)

__all__ = ["LearnResult", "Strategy", "learn", "load_strategy"]

SCHEMA_VER = "learning.v0"
_YIELD_KINDS = ("source", "country", "query")


class LearnResult(NorthvaineModel):
    version: int
    labels: int
    changes: list[str]
    paused: list[str]


class Strategy(NorthvaineModel):
    """One strategy version, ready for a run to use."""

    version: int
    labels: float
    pooled: tuple[float, float]
    yields: dict[str, dict[str, tuple[float, float]]]
    paused: list[str]

    def posteriors(self) -> Posteriors:
        return Posteriors(
            pooled=Beta(*self.pooled),
            yields={
                kind: {k: Beta(*ab) for k, ab in keys.items()} for kind, keys in self.yields.items()
            },
        )


def _text(sql: str) -> Any:
    from sqlalchemy import text

    return text(sql)


def _query_source(key: str) -> str:
    return key.split(":", 1)[0]


async def _labels(session: Any, workspace_id: UUID, sources: list[str]) -> list[Label]:
    rows = await session.execute(
        _text(
            "SELECT f.rating, f.weight, f.source, d.features FROM feedback f "
            "JOIN cases c ON c.id = f.case_id "
            "JOIN LATERAL (SELECT features FROM decisions WHERE case_id = c.id AND kind = 'brief' "
            "ORDER BY created_at DESC, id DESC LIMIT 1) d ON true "
            "WHERE c.workspace_id = :w AND f.source = ANY(CAST(:sources AS text[])) "
            "ORDER BY f.created_at, f.id"
        ),
        {"w": workspace_id, "sources": sources},
    )
    labels: list[Label] = []
    for rating, weight, source, features in rows.all():
        feats = features if isinstance(features, dict) else json.loads(features)
        labels.append(
            Label(
                rating=FeedbackRating(rating),
                weight=float(weight),
                source=LabelSource(source),
                queries=tuple(feats.get("query_keys", [])),
                sources=tuple(feats.get("sources", [])),
                country=feats.get("country"),
            )
        )
    return labels


async def load_strategy(
    session: Any, workspace_id: UUID, version: int | None = None
) -> Strategy | None:
    """The latest (or a given) strategy version of a workspace, or None before any learning."""
    found = await session.execute(
        _text(
            "SELECT version, snapshot FROM strategy_versions WHERE workspace_id = :w "
            "AND (CAST(:v AS int) IS NULL OR version = CAST(:v AS int)) "
            "ORDER BY version DESC LIMIT 1"
        ),
        {"w": workspace_id, "v": version},
    )
    row = found.first()
    if row is None:
        return None
    snap = row.snapshot if isinstance(row.snapshot, dict) else json.loads(row.snapshot)
    return Strategy(version=row.version, **snap)


async def learn(
    session: Any,
    workspace_id: UUID,
    *,
    simulated: bool = False,
    seed: int = 0,
    settings: Settings | None = None,
) -> LearnResult:
    """Fit the workspace's labels into a new strategy version and store it."""
    cfg = settings or get_settings()
    sources = [LabelSource.SIMULATED.value] if simulated else [LabelSource.OWNER.value]
    labels = await _labels(session, workspace_id, sources)
    previous = await load_strategy(session, workspace_id)
    mapping = {k: _query_source(k) for lab in labels for k in lab.queries}
    post = fit_posteriors(labels, strength=cfg.learning_prior_strength, query_source=mapping)

    before = previous.posteriors() if previous else None
    changes: list[str] = []
    yields: dict[str, dict[str, tuple[float, float]]] = {}
    for kind in _YIELD_KINDS:
        yields[kind] = {}
        for key, belief in post.yields.get(kind, {}).items():
            old = before.yields.get(kind, {}).get(key) if before else None
            kept = trust_region(belief, old, cfg.learning_trust_region)
            yields[kind][key] = (kept.a, kept.b)
            was = old.mean if old else None
            if was is None or abs(kept.mean - was) >= 0.05:
                changes.append(
                    f"{kind} {key}: good-rate {kept.mean:.2f}"
                    + (f" (was {was:.2f})" if was is not None else " (new)")
                    + f" from {post.counts.get(kind, {}).get(key, 0):.0f} label(s)"
                )
    paused = pause_suggestions(
        post,
        query_source=mapping,
        min_labels=cfg.learning_pause_min_labels,
        threshold=cfg.learning_pause_threshold,
        rng=random.Random(seed),
    )
    changes.extend(f"query {key}: paused (very probably below its source's rate)" for key in paused)
    version = (previous.version if previous else 0) + 1
    strategy = Strategy(
        version=version,
        labels=sum(lab.weight for lab in labels),
        pooled=(post.pooled.a, post.pooled.b),
        yields=yields,
        paused=paused,
    )
    snapshot = strategy.model_dump(mode="json", exclude={"version"})
    await session.execute(
        _text(
            "INSERT INTO strategy_versions (workspace_id, version, snapshot, changes) "
            "VALUES (:w, :v, CAST(:snapshot AS jsonb), CAST(:changes AS jsonb))"
        ),
        {
            "w": workspace_id,
            "v": version,
            "snapshot": json.dumps(snapshot, sort_keys=True),
            "changes": json.dumps(changes or ["no change: not enough new labels"]),
        },
    )
    insert = _text(
        "INSERT INTO beliefs (learner, workspace_id, strategy_version, kind, key, params, "
        "schema_ver, n_evidence, prior_source) VALUES ('research', :w, :v, :kind, :key, "
        "CAST(:params AS jsonb), :schema_ver, :n, :prior)"
    )
    for kind, keys in yields.items():
        for key, (a, b) in sorted(keys.items()):
            await session.execute(
                insert,
                {
                    "w": workspace_id,
                    "v": version,
                    "kind": f"{kind}_yield",
                    "key": key,
                    "params": json.dumps({"a": a, "b": b}),
                    "schema_ver": SCHEMA_VER,
                    "n": post.counts.get(kind, {}).get(key, 0.0),
                    "prior": "simulated" if simulated else "pooled",
                },
            )
    return LearnResult(version=version, labels=len(labels), changes=changes, paused=paused)
