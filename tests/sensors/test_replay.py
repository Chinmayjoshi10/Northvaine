from datetime import UTC, datetime

import httpx
import pytest

from northvaine.sensors.replay import (
    RecordedExchange,
    RecordingTransport,
    ReplayMismatch,
    load_exchanges,
    replay_transport,
    save_exchanges,
)

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
URL = "https://api.example.test/search"


def ex(**kw) -> RecordedExchange:
    base = dict(method="POST", url=URL, status=200, recorded_at=NOW, body_json={"ok": 1})
    base.update(kw)
    return RecordedExchange(**base)


def client(exchanges, **kw) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=replay_transport(exchanges, **kw))


def test_round_trip(tmp_path):
    items = [
        ex(request_json={"a": 1}, headers={"content-type": "application/json"}),
        ex(status=429, body_json=None, body_text="<html>slow down</html>"),
    ]
    path = tmp_path / "x.json"
    save_exchanges(path, items)
    assert load_exchanges(path) == items


def test_recorded_at_must_be_tz_aware():
    with pytest.raises(ValueError):
        ex(recorded_at=datetime(2026, 1, 1))


async def test_match_ignores_key_order_and_whitespace():
    c = client([ex(request_json={"a": 1, "b": 2})])
    r = await c.post(URL, content=b'{ "b": 2,\n "a": 1 }')
    assert r.json() == {"ok": 1}


async def test_unmatched_raises_naming_request():
    c = client([ex(request_json={"a": 1})])
    with pytest.raises(ReplayMismatch, match=r"POST https://api\.example\.test/search"):
        await c.post(URL, json={"a": 2})
    with pytest.raises(ReplayMismatch, match="GET"):
        await c.get("https://other.test/")


async def test_match_body_false_matches_method_and_url_only():
    c = client([ex(request_json={"a": 1})], match_body=False)
    assert (await c.post(URL, json={"zzz": 9})).status_code == 200
    c2 = client([ex(request_json={"a": 1})], match_body=False)
    with pytest.raises(ReplayMismatch):
        await c2.get(URL)


async def test_html_429_replayed_with_status_and_content_type():
    e = ex(
        method="GET",
        status=429,
        body_json=None,
        body_text="<html>429</html>",
        headers={"content-type": "text/html", "retry-after": "5"},
    )
    r = await client([e]).get(URL)
    assert r.status_code == 429
    assert r.headers["content-type"] == "text/html"
    assert r.text == "<html>429</html>"


async def test_repeated_requests_served_in_order_then_exhausted():
    c = client([ex(body_json={"page": 1}), ex(body_json={"page": 2})], match_body=False)
    assert (await c.post(URL)).json() == {"page": 1}
    assert (await c.post(URL)).json() == {"page": 2}
    with pytest.raises(ReplayMismatch):
        await c.post(URL)


async def test_recording_transport_keeps_allowlisted_headers_only():
    def inner(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"hello": "w"}, headers={"retry-after": "1", "set-cookie": "s=1"}
        )

    rec = RecordingTransport(httpx.MockTransport(inner))
    async with httpx.AsyncClient(transport=rec) as c:
        r = await c.post(URL, json={"q": 1}, headers={"Authorization": "Bearer secret"})
    assert r.json() == {"hello": "w"}
    (got,) = rec.exchanges
    assert got.request_json == {"q": 1}
    assert got.body_json == {"hello": "w"}
    assert set(got.headers) == {"content-type", "retry-after"}
    assert "secret" not in got.model_dump_json()
    assert got.recorded_at.tzinfo is not None
