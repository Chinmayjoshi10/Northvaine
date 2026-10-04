"""Recorded-replay LLM client for offline tests and the recorder (T4.1, D53).

`ReplayClient` and `RecordingClient` duck-type the SDK objects (`chat.completions.create`,
`embeddings.create`) and are installed with `llm.client_override`; this module must not import
the SDK (check_invariants: SDK only in llm.py).
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from northvaine.core.models import NorthvaineModel

__all__ = [
    "LlmExchange",
    "LlmRecording",
    "RecordingClient",
    "ReplayClient",
    "exchange_key",
    "load_recording",
    "normalize_body",
    "replay_environment",
    "save_recording",
]


class LlmExchange(NorthvaineModel):
    kind: Literal["chat", "embed"]
    key: str
    prompt_version: str | None = None
    request: dict[str, Any]
    response: dict[str, Any]


class LlmRecording(NorthvaineModel):
    recorded_at: str
    models: dict[str, str]
    settings: dict[str, Any] = Field(default_factory=dict)
    exchanges: list[LlmExchange] = Field(default_factory=list)


def normalize_body(body: dict[str, Any]) -> dict[str, Any]:
    """The request body with per-call fence nonces replaced by a fixed token."""
    raise NotImplementedError("T4.1")


def exchange_key(kind: str, body: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of the normalized body."""
    raise NotImplementedError("T4.1")


def load_recording(path: str | Path) -> LlmRecording:
    """Read a recording file."""
    raise NotImplementedError("T4.1")


def save_recording(path: str | Path, recording: LlmRecording) -> None:
    """Write a recording file (stable key order, vectors rounded to 6 decimals)."""
    raise NotImplementedError("T4.1")


class ReplayClient:
    """Serves recorded exchanges; a request with no recording raises `LlmReplayMismatch`."""

    def __init__(self, recording: LlmRecording) -> None:
        raise NotImplementedError("T4.1")


class RecordingClient:
    """Wraps a real client and records every exchange."""

    def __init__(self, inner: Any) -> None:
        raise NotImplementedError("T4.1")

    def recording(self, models: dict[str, str], settings: dict[str, Any]) -> LlmRecording:
        """The recording so far."""
        raise NotImplementedError("T4.1")


def replay_environment(recording: LlmRecording) -> AbstractContextManager[None]:
    """Pin `MODEL_*` and the budget caps to the recording's values (env vars plus
    `get_settings.cache_clear()`), restored on exit."""
    raise NotImplementedError("T4.1")
