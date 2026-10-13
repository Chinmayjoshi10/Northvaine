"""What each answer taught (D100): the learning loop from the saved files, no database.

The app saves every answer as a feedback record (`api/feedback.py`). Here each record becomes
the same `Label` the database path builds (`radar.strategy`): its rating from `labels.rating_of`,
and what found the lead (searches, sources, country) from the saved run (`persist.provenance`).

`learn_from_files` fits those labels into a `Strategy` that a live run uses to choose its
searches (`run_radar(strategy=...)`), and explains each answer in one plain sentence: what it
changed, measured by fitting the beliefs without it and with it. Nothing is said to change
unless the numbers moved, and nothing changes a run before `learning_min_labels` answers.

Only the latest answer per lead counts: a changed mind replaces the earlier answer.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

from northvaine.core.models import FeedbackRating, LabelSource, NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.labels import rating_of
from northvaine.radar.learning import (
    Label,
    Posteriors,
    fit_posteriors,
    pause_suggestions,
    query_keys_by_ref,
)
from northvaine.radar.models import RadarRun
from northvaine.radar.persist import provenance
from northvaine.radar.strategy import Strategy

__all__ = ["Learning", "Lesson", "learn_from_files"]

_MOVE = 0.005  # a smaller move in a belief is not reported as a change


class Lesson(NorthvaineModel):
    """One answer and what it taught, in words."""

    as_of: str
    rank: int
    company: str
    said: str
    teaches: str | None  # the rating, or None when the answer teaches nothing yet
    change: str  # one sentence: what changed, or why nothing did
    received_at: str


class Learning(NorthvaineModel):
    answers: int
    labels: float
    needed: float  # labels before a strategy changes a run
    active: bool
    lessons: list[Lesson]  # newest first
    strategy: Strategy | None


def _said(record: Mapping[str, Any]) -> str:
    note = str(record.get("note") or "").strip()
    chip = record.get("failure_chip")
    if note and chip and chip not in note:
        return f"{note} · {chip}"
    return note or str(chip or "an answer")


def _latest(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    by_lead: dict[tuple[str, int], Mapping[str, Any]] = {}
    for r in sorted(records, key=lambda r: str(r.get("received_at", ""))):
        by_lead[(str(r.get("as_of")), int(r.get("rank", 0)))] = r
    return sorted(by_lead.values(), key=lambda r: str(r.get("received_at", "")))


def _query_texts(run: RadarRun) -> dict[str, str]:
    by_ref = query_keys_by_ref(run.queries)
    out: dict[str, str] = {}
    for sensor, listed in run.queries.items():
        for index, query in enumerate(listed, start=1):
            if query.text:
                out[by_ref[f"{sensor}:{index}"]] = query.text
    return out


def _sensor(key: str) -> str:
    """A sensor's name as people write it: short names are acronyms ("TED")."""
    name = key.split(":", 1)[0]
    return name.upper() if len(name) <= 4 else name.capitalize()


def _fit(labels: list[Label], mapping: dict[str, str], strength: float) -> Posteriors:
    return fit_posteriors(labels, strength=strength, query_source=mapping)


def _change(
    label: Label, before: Posteriors, after: Posteriors, texts: Mapping[str, str]
) -> str | None:
    """The largest move this one label made, worded; None when nothing moved."""
    if label.rating is FeedbackRating.WRONG_FACTS:
        moves = [(s, before.reliability.get(s), after.reliability.get(s)) for s in label.sources]
        moved = [(s, b.mean if b else 0.9, a.mean) for s, b, a in moves if a is not None]
        if not moved:
            return None
        src, was, now = max(moved, key=lambda m: abs(m[2] - m[1]))
        if abs(now - was) < _MOVE:
            return None
        return f"I now trust {src} less: {was:.0%} → {now:.0%} of its facts expected to hold."
    for kind, keys in (("query", label.queries), ("source", label.sources)):
        moved = []
        for k in keys:
            new = after.yields.get(kind, {}).get(k)
            if new is None:
                continue
            old = before.yields.get(kind, {}).get(k)
            was = old.mean if old else before.mean(kind, k)
            moved.append((k, was, new.mean))
        moved = [m for m in moved if abs(m[2] - m[1]) >= _MOVE]
        if not moved:
            continue
        key, was, now = max(moved, key=lambda m: abs(m[2] - m[1]))
        if kind == "query" and key in texts:
            what = f"the search “{texts[key]}”"
        elif kind == "query":  # a code-only search has no words; name where it searches
            what = f"the {_sensor(key)} search that found it"
        else:
            what = f"leads from {key}"
        way = "up" if now > was else "down"
        return f"I moved {what} {way}: {was:.0%} → {now:.0%} chance of a good lead."
    return None


def learn_from_files(
    records: Sequence[Mapping[str, Any]],
    runs: Mapping[str, RadarRun],
    *,
    settings: Settings | None = None,
    seed: int = 0,
) -> Learning:
    """Labels, a strategy and one lesson per answer, from a client's feedback records and the
    saved runs they answer (keyed by run date)."""
    cfg = settings or get_settings()
    labels: list[Label] = []
    lessons: list[Lesson] = []
    texts: dict[str, str] = {}
    mapping: dict[str, str] = {}
    answered = _latest(records)
    for record in answered:
        run = runs.get(str(record.get("as_of")))
        entry = (
            next((e for e in run.entries if e.rank == int(record.get("rank", 0))), None)
            if run
            else None
        )
        rated = rating_of(record)
        base = {
            "as_of": str(record.get("as_of")),
            "rank": int(record.get("rank", 0)),
            "company": str(record.get("company", "")),
            "said": _said(record),
            "received_at": str(record.get("received_at", "")),
        }
        if run is None or entry is None:
            lessons.append(
                Lesson(**base, teaches=None, change="That edition is no longer on file.")
            )
            continue
        if rated is None:
            lessons.append(
                Lesson(**base, teaches=None, change="Noted. It does not teach a rating yet.")
            )
            continue
        rating = rated[0]
        if rating is FeedbackRating.LATER:
            lessons.append(
                Lesson(
                    **base,
                    teaches=rating.value,
                    change="Noted as timing: it does not change which searches run.",
                )
            )
            labels.append(_label(rating, entry, run))
            continue
        texts.update(_query_texts(run))
        label = _label(rating, entry, run)
        mapping.update({k: k.split(":", 1)[0] for k in label.queries})
        before = _fit(labels, mapping, cfg.learning_prior_strength)
        labels.append(label)
        after = _fit(labels, mapping, cfg.learning_prior_strength)
        lessons.append(
            Lesson(
                **base,
                teaches=rating.value,
                change=_change(label, before, after, texts)
                or "Noted. The run record does not say which search found it.",
            )
        )

    weight = sum(lab.weight for lab in labels if lab.rating is not FeedbackRating.LATER)
    post = _fit(labels, mapping, cfg.learning_prior_strength)
    strategy = None
    if labels:
        paused = pause_suggestions(
            post,
            query_source=mapping,
            min_labels=cfg.learning_pause_min_labels,
            threshold=cfg.learning_pause_threshold,
            rng=random.Random(seed),
        )
        strategy = Strategy(
            version=0,  # from files; database versions start at 1
            labels=weight,
            pooled=(post.pooled.a, post.pooled.b),
            yields={
                kind: {k: (b.a, b.b) for k, b in keys.items()} for kind, keys in post.yields.items()
            },
            paused=paused,
        )
    return Learning(
        answers=len(answered),
        labels=weight,
        needed=cfg.learning_min_labels,
        active=weight >= cfg.learning_min_labels,
        lessons=list(reversed(lessons)),
        strategy=strategy,
    )


def _label(rating: FeedbackRating, entry: Any, run: RadarRun) -> Label:
    prov = provenance(entry.candidate, run)
    return Label(
        rating=rating,
        weight=1.0,
        source=LabelSource.OWNER,
        queries=tuple(prov["query_keys"]),
        sources=tuple(prov["sources"]),
        country=entry.candidate.country,
    )
