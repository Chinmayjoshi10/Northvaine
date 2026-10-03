"""Offline tests for the replay gate (T3.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from northvaine.core.documents import SaveResult, assert_available
from northvaine.core.models import DocumentRow, SourceTier
from northvaine.sensors.base import LeakageError, SensorDocument

NOW = datetime(2026, 1, 10, tzinfo=UTC)


def sensor_doc(available_at: datetime | None, url: str = "https://x.test/a") -> SensorDocument:
    return SensorDocument(
        source="s",
        tier=SourceTier.COMPANY,
        url=url,
        text="t",
        content_hash="h" * 64,
        fetched_at=NOW,
        available_at=available_at,
    )


def row(available_at: datetime | None, url: str = "https://x.test/r") -> DocumentRow:
    return DocumentRow(
        id=uuid4(),
        source_id=None,
        url=url,
        content_hash="c" * 64,
        title=None,
        text="t",
        published_on=None,
        fetched_at=NOW,
        workspace_id=None,
        available_at=available_at,
    )


def test_accepts_available_docs_of_both_types() -> None:
    assert_available([row(NOW), sensor_doc(NOW - timedelta(days=1))], NOW)


def test_empty_is_fine() -> None:
    assert_available([], NOW)


def test_future_row_raises_naming_it() -> None:
    with pytest.raises(LeakageError, match=r"x.test/r"):
        assert_available([row(NOW + timedelta(seconds=1))], NOW)


def test_null_available_at_raises() -> None:
    with pytest.raises(LeakageError, match="no available_at"):
        assert_available([sensor_doc(None)], NOW)


def test_one_bad_doc_among_good_raises() -> None:
    bad = row(NOW + timedelta(days=1), url="https://x.test/bad")
    with pytest.raises(LeakageError, match=r"x.test/bad"):
        assert_available([row(NOW), bad], NOW)


def test_save_result_fields() -> None:
    assert SaveResult(inserted=1, unchanged=2).unchanged == 2
