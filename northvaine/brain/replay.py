"""Recorded-replay LLM client for offline tests and the recorder (T4.1, D53).

`ReplayClient` and `RecordingClient` duck-type the SDK objects (`chat.completions.create`,
`embeddings.create`) and are installed with `llm.client_override`; this module must not import
the SDK (check_invariants: SDK only in llm.py).

A request is matched by `exchange_key`: sha256 of the canonical JSON of the request body after
fence nonces are replaced by a fixed token. So a changed prompt, variable, `max_tokens` or model id
is a different key, and the recording must be redone (never hand-edited).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import Field

from northvaine.brain.errors import LlmReplayMismatch
from northvaine.core import settings as settings_module
from northvaine.core.models import NorthvaineModel

__all__ = [
    "NONCE_TOKEN",
    "REPLAY_BUDGET_USD",
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

NONCE_TOKEN = "<NONCE>"
NONCE_RE = re.compile(r"(-----(?:BEGIN|END) [^\n]*? DATA )[0-9a-f]{32}(-----)")
VECTOR_DECIMALS = 6
# Every cap is set far above any recording's cost so a replay never trips the budget guard.
REPLAY_BUDGET_USD = "1000"
BUDGET_VARIABLES = ("DAILY_BUDGET_USD", "TOTAL_BUDGET_USD", "RUN_BUDGET_USD", "MAX_CALL_COST_USD")
TIER_VARIABLES = {
    "fast": "MODEL_FAST",
    "mid": "MODEL_MID",
    "deep": "MODEL_DEEP",
    "embed": "MODEL_EMBED",
}
FRONT_MATTER_RE = re.compile(r"\A---\s*\n(?P<head>.*?)\n---", re.DOTALL)


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


# --- keys ---------------------------------------------------------------------------------


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return NONCE_RE.sub(lambda m: m.group(1) + NONCE_TOKEN + m.group(2), value)
    if isinstance(value, list | tuple):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    return value


def normalize_body(body: dict[str, Any]) -> dict[str, Any]:
    """The request body with per-call fence nonces replaced by a fixed token."""
    return dict(_normalize(body))


def exchange_key(kind: str, body: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of the normalized body."""
    canonical = json.dumps(
        {"kind": kind, "body": normalize_body(body)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _prompt_version(body: dict[str, Any]) -> str | None:
    """`<name>.v<N>` when the first message starts with prompt front matter, else None."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict):
        return None
    content = messages[0].get("content")
    if not isinstance(content, str):
        return None
    match = FRONT_MATTER_RE.match(content)
    if not match:
        return None
    fields = dict(
        (k.strip(), v.strip())
        for k, _, v in (line.partition(":") for line in match.group("head").splitlines())
    )
    name, version = fields.get("name", ""), fields.get("version", "")
    return f"{name}.v{version}" if name and version else None


# --- files --------------------------------------------------------------------------------


def _round_vectors(value: Any) -> Any:
    """Round every float list under an `embedding` key to 6 decimals."""
    if isinstance(value, dict):
        return {
            k: (
                [round(float(x), VECTOR_DECIMALS) for x in v]
                if k == "embedding" and isinstance(v, list)
                else _round_vectors(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_round_vectors(v) for v in value]
    return value


def load_recording(path: str | Path) -> LlmRecording:
    """Read a recording file."""
    return LlmRecording.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_recording(path: str | Path, recording: LlmRecording) -> None:
    """Write a recording file (stable key order, vectors rounded to 6 decimals)."""
    data = _round_vectors(recording.model_dump(mode="json"))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# --- replay -------------------------------------------------------------------------------


def _namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_namespace(v) for v in value]
    return value


class _ReplayEndpoint:
    def __init__(self, client: ReplayClient, kind: Literal["chat", "embed"]) -> None:
        self._client = client
        self._kind = kind

    async def create(self, **body: Any) -> Any:
        return self._client.answer(self._kind, body)


class ReplayClient:
    """Serves recorded exchanges; a request with no recording raises `LlmReplayMismatch`."""

    def __init__(self, recording: LlmRecording) -> None:
        self.recording = recording
        self._by_key = {(e.kind, e.key): e for e in recording.exchanges}
        self.chat = SimpleNamespace(completions=_ReplayEndpoint(self, "chat"))
        self.embeddings = _ReplayEndpoint(self, "embed")
        self.served: list[str] = []

    def answer(self, kind: Literal["chat", "embed"], body: dict[str, Any]) -> Any:
        key = exchange_key(kind, body)
        exchange = self._by_key.get((kind, key))
        if exchange is None:
            version = _prompt_version(body) or "unknown prompt version"
            raise LlmReplayMismatch(
                f"no recorded {kind} exchange for key {key} ({version}, "
                f"model={body.get('model')!r}, max_tokens={body.get('max_tokens')!r}). "
                "A prompt, variable, max_tokens or model change invalidates a recording: "
                "re-record it with `tasks.py record-llm`, never hand-edit."
            )
        self.served.append(key)
        return _namespace(exchange.response)


# --- recording ----------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """An SDK response (pydantic object, namespace or dict) as plain JSON data."""
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, SimpleNamespace):
        return _plain(vars(value))
    if isinstance(value, Decimal):
        return float(value)
    return value


def _response_dict(kind: str, raw: Any) -> dict[str, Any]:
    """Only the fields `llm.py` reads, so recordings stay small and free of ids."""
    data = _plain(raw)
    usage = data.get("usage") or {}
    kept_usage = {
        k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage
    }
    if kind == "chat":
        choices = [
            {
                "message": {"content": (c.get("message") or {}).get("content")},
                "finish_reason": c.get("finish_reason"),
            }
            for c in data.get("choices") or []
        ]
        return {"model": data.get("model"), "choices": choices, "usage": kept_usage}
    items = [{"embedding": d.get("embedding")} for d in data.get("data") or []]
    return {"model": data.get("model"), "data": items, "usage": kept_usage}


class _RecordingEndpoint:
    def __init__(self, client: RecordingClient, kind: Literal["chat", "embed"]) -> None:
        self._client = client
        self._kind = kind

    async def create(self, **body: Any) -> Any:
        inner = self._client.inner
        target = inner.chat.completions if self._kind == "chat" else inner.embeddings
        raw = await target.create(**body)
        self._client.keep(self._kind, body, raw)
        return raw


class RecordingClient:
    """Wraps a real client and records every exchange."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.exchanges: list[LlmExchange] = []
        self.chat = SimpleNamespace(completions=_RecordingEndpoint(self, "chat"))
        self.embeddings = _RecordingEndpoint(self, "embed")

    def keep(self, kind: Literal["chat", "embed"], body: dict[str, Any], raw: Any) -> None:
        request = normalize_body(_plain(body))
        key = exchange_key(kind, request)
        if any(e.kind == kind and e.key == key for e in self.exchanges):
            return  # the same request answers the same way on replay
        self.exchanges.append(
            LlmExchange(
                kind=kind,
                key=key,
                prompt_version=_prompt_version(request),
                request=request,
                response=_round_vectors(_response_dict(kind, raw)),
            )
        )

    def recording(self, models: dict[str, str], settings: dict[str, Any]) -> LlmRecording:
        """The recording so far."""
        return LlmRecording(
            recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
            models=dict(models),
            settings=dict(settings),
            exchanges=list(self.exchanges),
        )


# --- environment --------------------------------------------------------------------------


def _clear_settings_caches() -> None:
    """Clear `get_settings` everywhere it is bound (modules import the name directly)."""
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        if module is not None and (name == "northvaine" or name.startswith("northvaine.")):
            clear = getattr(getattr(module, "get_settings", None), "cache_clear", None)
            if callable(clear):
                clear()
    settings_module.get_settings.cache_clear()


# Settings that widened after older recordings were made (D107). A recording that does not name
# one was made with the value here, so replay pins that value and asks for what was recorded.
LEGACY_SETTINGS: dict[str, object] = {
    "hmrc_min_kept": 0,
    "radar_max_gate_candidates": 40,
    "radar_register_max_lookups": 40,
    "radar_fit_max_accounts": 5,  # D108
    "radar_seed_max_lookups": 0,  # D109: no customer lookups
    "radar_timing_max_lookups": 0,  # D111: no charge or address reads
    "radar_site_guess_max_companies": 0,  # D113: no guessed-site fetches
    "radar_register_accounts_type": False,  # D116: no accounts-type claim
    "radar_link_by_register": False,  # D115: no merge by registration number, no reorder
    "radar_fit_single_search": False,  # D108: two searches a company, rank order
    "radar_investigate_top": 0,  # D117: no investigation of the top leads
}


@contextmanager
def _pinned_environment(recording: LlmRecording) -> Iterator[None]:
    pins: dict[str, str] = {}
    for tier, model in recording.models.items():
        variable = TIER_VARIABLES.get(str(tier).lower())
        if variable and model:
            pins[variable] = str(model)
    for name in BUDGET_VARIABLES:
        pins[name] = REPLAY_BUDGET_USD
    for name, value in {**LEGACY_SETTINGS, **recording.settings}.items():
        if value is not None and name in settings_module.Settings.model_fields:
            # lists and tuples go in as JSON, the form the settings parser reads back
            pins[name.upper()] = (
                json.dumps(list(value)) if isinstance(value, list | tuple) else str(value)
            )
    previous = {name: os.environ.get(name) for name in pins}
    os.environ.update(pins)
    _clear_settings_caches()
    try:
        yield
    finally:
        for name, old in previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        _clear_settings_caches()


def replay_environment(recording: LlmRecording) -> AbstractContextManager[None]:
    """Pin `MODEL_*` and the budget caps to the recording's values (env vars plus
    `get_settings.cache_clear()`), restored on exit."""
    return _pinned_environment(recording)
