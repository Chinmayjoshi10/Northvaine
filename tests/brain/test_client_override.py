"""`llm.client_override`: the hook the recorder and the replay client use (T4.0)."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from northvaine.brain import errors, llm
from northvaine.core.settings import ConfigError


@pytest.fixture(autouse=True)
def _no_api_key(clean_settings: None) -> None:
    """No NEBIUS_API_KEY and no `.env`: only an override can make `get_client()` succeed."""


def test_without_an_override_a_missing_key_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="NEBIUS_API_KEY"):
        llm.get_client()


def test_override_is_returned_without_any_api_key() -> None:
    sentinel = object()
    with llm.client_override(sentinel):
        assert llm.get_client() is sentinel


def test_override_is_restored_after_the_block() -> None:
    with llm.client_override(object()):
        pass
    with pytest.raises(ConfigError):
        llm.get_client()


def test_override_is_restored_after_an_exception() -> None:
    with pytest.raises(RuntimeError, match="boom"), llm.client_override(object()):
        raise RuntimeError("boom")
    with pytest.raises(ConfigError):
        llm.get_client()


def test_overrides_nest_and_unwind_in_order() -> None:
    outer, inner = object(), object()
    with llm.client_override(outer):
        with llm.client_override(inner):
            assert llm.get_client() is inner
        assert llm.get_client() is outer


async def test_override_is_isolated_between_concurrent_tasks() -> None:
    first, second = object(), object()
    seen: dict[str, object] = {}

    async def worker(name: str, client: object, delay: float) -> None:
        with llm.client_override(client):
            await asyncio.sleep(delay)
            seen[name] = llm.get_client()

    async def outsider() -> None:
        await asyncio.sleep(0.01)
        with pytest.raises(ConfigError):
            llm.get_client()

    await asyncio.gather(worker("a", first, 0.03), worker("b", second, 0.01), outsider())
    assert seen == {"a": first, "b": second}


def test_monkeypatching_get_client_still_works_inside_the_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The M2 tests replace `llm.get_client`; `_complete` and `embed` look it up by name."""
    sentinel = object()
    monkeypatch.setattr(llm, "get_client", lambda: sentinel)
    assert llm.get_client() is sentinel
    source = inspect.getsource(llm._complete) + inspect.getsource(llm.embed)
    assert "get_client()" in source


def test_client_override_signature() -> None:
    params = list(inspect.signature(llm.client_override).parameters.values())
    assert [p.name for p in params] == ["client"]
    assert not inspect.iscoroutinefunction(llm.client_override)


def test_replay_mismatch_is_an_assertion_error_not_an_llm_error() -> None:
    assert issubclass(errors.LlmReplayMismatch, AssertionError)
    assert not issubclass(errors.LlmReplayMismatch, errors.LlmError)
    assert "LlmReplayMismatch" in errors.__all__
