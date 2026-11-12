"""D144: a run resumed after a restart gets its saved answers back at once and for free; nothing
secret is saved; failures are not saved. And saved records come back to disk at start.
No network, no database (the durable store is replaced by a dict)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from northvaine.api import durable
from northvaine.jobs.resume import ResumeCache
from northvaine.sensors import caching as resume


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    saved: dict[tuple[str, str], str] = {}

    async def items(kind: str, prefix: str = "") -> list[tuple[str, str]]:
        return sorted((k, v) for (kd, k), v in saved.items() if kd == kind and k.startswith(prefix))

    monkeypatch.setattr(
        durable, "save_later", lambda kind, key, text: saved.__setitem__((kind, key), text)
    )
    monkeypatch.setattr(durable, "items", items)
    return saved


async def test_http_answers_replay_without_the_network(store: dict[tuple[str, str], str]) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "broken" in str(request.url):
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"results": [1, 2]}, headers={"x-secret": "no"})

    cache = ResumeCache("s1")
    from northvaine.sensors import caching as resume

    first = httpx.AsyncClient(
        transport=resume.CachingTransport(httpx.MockTransport(handler), cache)
    )
    body = {"query": "benches", "api_key": "tvly-SECRET"}
    r = await first.post("https://api.example.test/search", json=body)
    assert r.json() == {"results": [1, 2]}
    await first.get("https://api.example.test/broken")
    assert len(calls) == 2
    # only the good answer is saved, and no request (with its key) is kept
    assert (
        len(store) == 1
        and "tvly-SECRET" not in json.dumps(list(store.values()))
        and "x-secret" not in json.dumps(list(store.values()))
    )

    again = await ResumeCache.load("s1")
    second = httpx.AsyncClient(
        transport=resume.CachingTransport(httpx.MockTransport(handler), again)
    )
    r = await second.post("https://api.example.test/search", json=body)
    assert r.json() == {"results": [1, 2]} and len(calls) == 2  # served from the save
    await second.get("https://api.example.test/broken")
    assert len(calls) == 3  # a failure is asked again
    assert again.hits == 1 and again.misses == 1


async def test_model_replies_replay_with_zero_tokens(store: dict[tuple[str, str], str]) -> None:
    asked: list[dict[str, Any]] = []

    class Completions:
        async def create(self, **body: Any) -> Any:
            asked.append(body)
            return SimpleNamespace(
                model="m",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"ok": 1}'), finish_reason="stop"
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=900, completion_tokens=100, total_tokens=1000),
            )

    inner = SimpleNamespace(chat=SimpleNamespace(completions=Completions()), embeddings=None)
    from northvaine.jobs.resume import CachingLlmClient

    body = {"model": "m", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 50}
    first = await CachingLlmClient(inner, ResumeCache("s1")).chat.completions.create(**body)
    assert first.usage.total_tokens == 1000 and len(asked) == 1
    replay = CachingLlmClient(inner, await ResumeCache.load("s1"))
    second = await replay.chat.completions.create(**body)
    assert len(asked) == 1  # not asked again
    assert second.choices[0].message.content == '{"ok": 1}'
    assert second.usage.prompt_tokens == 0 and second.usage.completion_tokens == 0  # no cost


async def test_page_fetch_errors_are_not_saved(store: dict[tuple[str, str], str]) -> None:
    from northvaine.jobs.resume import CachingPageFetcher
    from northvaine.radar.discover import UpgradedPage

    fetched: list[str] = []

    class Inner:
        async def fetch(self, url: str) -> UpgradedPage:
            fetched.append(url)
            refused = "error" if "down" in url else None
            return UpgradedPage(
                lead_url=url,
                final_url=url,
                status=None if refused else 200,
                fetched_at=None,
                title=None,
                refused=refused,
                text=None if refused else "Benches",
            )

    cache = ResumeCache("s1")
    fetcher = CachingPageFetcher(Inner(), cache)
    await fetcher.fetch("https://a.example.test/")
    await fetcher.fetch("https://down.example.test/")
    again = CachingPageFetcher(Inner(), await ResumeCache.load("s1"))
    page = await again.fetch("https://a.example.test/")
    await again.fetch("https://down.example.test/")
    assert page.text == "Benches"
    assert fetched == [
        "https://a.example.test/",
        "https://down.example.test/",
        "https://down.example.test/",
    ]


async def test_hydrate_restores_records_without_overwriting_the_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "demo_reports" / "radar"
    clients = tmp_path / "clients"
    baked = reports / "demo" / "2026-10-28" / "run.json"
    baked.parent.mkdir(parents=True)
    baked.write_text("BAKED", encoding="utf-8")
    feedback = reports.parent / "feedback" / "acme.jsonl"
    feedback.parent.mkdir(parents=True)
    feedback.write_text('{"a": 1}\n', encoding="utf-8")
    rows = {
        "onboarding": [("s1", '{"id": "s1"}')],
        "onboarding_text": [("s1.site", "site text")],
        "client": [("acme", "{}"), ("../escape", "{}")],
        "report": [("acme/2026-11-06/run.json", "{}"), ("demo/2026-10-28/run.json", "NEW")],
        "trial": [("x@y.test|s1", '{"email": "x@y.test", "session": "s1"}')],
        "request": [],
        "feedback": [("acme/1", '{"a": 1}'), ("acme/2", '{"b": 2}')],
    }

    async def items(kind: str, prefix: str = "") -> list[tuple[str, str]]:
        return rows.get(kind, [])

    monkeypatch.setattr(durable, "enabled", lambda: True)
    monkeypatch.setattr(durable, "items", items)
    counts = await durable.hydrate(reports, clients)
    assert (reports / "_onboarding" / "s1.json").read_text() == '{"id": "s1"}'
    assert (reports / "_onboarding" / "s1.site.txt").read_text() == "site text"
    assert (clients / "acme.json").is_file() and not (tmp_path / "escape.json").exists()
    assert (reports / "acme" / "2026-11-06" / "run.json").is_file()
    assert baked.read_text() == "BAKED"  # the image's own file is kept
    assert "x@y.test" in (reports / "_trials.jsonl").read_text()
    assert feedback.read_text().splitlines() == ['{"a": 1}', '{"b": 2}']  # merged, no duplicate
    assert counts["report"] == 2


async def test_compressed_answers_reach_the_sensor_readable(
    store: dict[tuple[str, str], str],
) -> None:
    """A gzip answer (official trade data comes compressed) is read once and passed on plain,
    both live and when replayed (the bug behind 'sensor hmrc: DecodingError' on staging)."""
    import gzip

    payload = json.dumps({"value": [{"Hs6Code": "391732"}]}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip", "content-type": "application/json"},
            content=gzip.compress(payload),
        )

    live = httpx.AsyncClient(
        transport=resume.CachingTransport(httpx.MockTransport(handler), ResumeCache("s1"))
    )
    assert (await live.get("https://api.example.test/Commodity")).json()["value"][0][
        "Hs6Code"
    ] == "391732"
    again = httpx.AsyncClient(
        transport=resume.CachingTransport(
            httpx.MockTransport(handler), await ResumeCache.load("s1")
        )
    )
    assert (await again.get("https://api.example.test/Commodity")).json()["value"][0][
        "Hs6Code"
    ] == "391732"
