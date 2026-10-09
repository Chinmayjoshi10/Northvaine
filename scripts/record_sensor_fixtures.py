"""Record live TED and Tavily responses as redacted sensor fixtures (T3.1, D42).

The only M3 code that talks to live APIs. It never runs in the gate and never from pytest.
Requests are built by the frozen `ted.build_request` / `tavily.build_search_request`, so
recorded bodies and sensor bodies cannot drift. Redaction comes first: allow-listed TED fields,
stripped `links`, no auth header or key literal, no contact-like keys, and a refusal to write
any file in which an email address or phone number survives.

Run it with:  uv run python scripts/tasks.py record-sensors -- --yes
Attribution for TED data: Source: TED, Publications Office of the European Union, ted.europa.eu
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a plain script: make `northvaine` importable
    sys.path.insert(0, str(ROOT))

from northvaine.core.settings import Settings, get_settings  # noqa: E402
from northvaine.sensors.base import SensorQuery  # noqa: E402
from northvaine.sensors.replay import (  # noqa: E402
    RecordedExchange,
    RecordingTransport,
    save_exchanges,
)
from northvaine.sensors.tavily import build_search_request  # noqa: E402
from northvaine.sensors.ted import build_request  # noqa: E402

CLIENTS_DIR = ROOT / "tests" / "fixtures" / "clients"
OUT_DIR = ROOT / "tests" / "fixtures" / "sensors"
REDACTED = "[REDACTED]"
DROP_KEY_RE = re.compile(r"email|tel|phone|fax|person|contact", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
PHONE_RES = (
    re.compile(r"(?<![\w+])\+\d{1,3}[\s.\-()]*\d[\d\s.\-()]{6,}\d"),
    re.compile(r"(?<![\w.])\(\d{2,5}\)[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}(?!\d)"),
    re.compile(r"(?<![\w.\-])0\d{1,4}[\s.\-/]\d{3,4}[\s.\-/]?\d{2,4}(?![\w\-])"),
)
BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")
SECRET_HEADERS = {"authorization", "proxy-authorization", "x-api-key"}
ATTRIBUTION = "Source: TED, Publications Office of the European Union, ted.europa.eu"

Sleep = Callable[[float], Awaitable[None]]
InnerFactory = Callable[[], httpx.AsyncBaseTransport]


class ClientSpec(BaseModel):
    id: str
    offer: str
    markets: list[str]
    sensors: dict[str, list[dict[str, Any]]]


@dataclass
class PlannedCall:
    sensor: str  # "ted" or "tavily"
    client: str
    n: int  # call number per (sensor, client), from 1
    url: str
    body: dict[str, Any]


def load_clients(folder: Path = CLIENTS_DIR) -> list[ClientSpec]:
    return [
        ClientSpec.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(folder.glob("*.json"))
    ]


def plan_calls(
    clients: list[ClientSpec], settings: Settings, *, only: str | None = None
) -> list[PlannedCall]:
    """Every request every client needs, built by the frozen request builders."""
    calls: list[PlannedCall] = []
    for spec in clients:
        if only and spec.id != only:
            continue
        for i, raw in enumerate(spec.sensors.get("ted", []), start=1):
            body = build_request(SensorQuery.model_validate(raw), settings=settings)
            calls.append(PlannedCall("ted", spec.id, i, settings.ted_api_url, body))
        for i, raw in enumerate(spec.sensors.get("tavily", []), start=1):
            body, _notes = build_search_request(SensorQuery.model_validate(raw), settings=settings)
            url = settings.tavily_api_url.rstrip("/") + "/search"
            calls.append(PlannedCall("tavily", spec.id, i, url, body))
    return calls


# --- redaction ----------------------------------------------------------------------------


def _scrub_text(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return BEARER_RE.sub("Bearer " + REDACTED, text)


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return _scrub_text(value, secrets)
    if isinstance(value, list):
        return [_scrub(v, secrets) for v in value]
    if isinstance(value, dict):
        return {
            _scrub_text(str(k), secrets): _scrub(v, secrets)
            for k, v in value.items()
            if not DROP_KEY_RE.search(str(k)) and str(k).lower() != "request_id"
        }
    return value


def withhold_ted_persons(
    ex: RecordedExchange, settings: Settings | None = None
) -> RecordedExchange:
    """Natural-person names in TED notices are withheld with the sensor's own function before a
    fixture is written, as the radar recorder does (D76): no personal name enters the repo."""
    from northvaine.sensors.ted import withhold_natural_persons

    body = ex.body_json
    if not isinstance(body, dict) or not isinstance(body.get("notices"), list):
        return ex
    cfg = settings or get_settings()
    notices = [
        withhold_natural_persons(n, cfg) if isinstance(n, dict) else n for n in body["notices"]
    ]
    return ex.model_copy(update={"body_json": {**body, "notices": notices}})


def redact_exchange(
    ex: RecordedExchange, *, secrets: tuple[str, ...] | list[str]
) -> RecordedExchange:
    """A copy with keys, auth headers and contact-like keys removed, request_id dropped."""
    keys = tuple(secrets)
    headers = {
        _scrub_text(k, keys): _scrub_text(v, keys)
        for k, v in ex.headers.items()
        if k.lower() not in SECRET_HEADERS
    }
    return ex.model_copy(
        update={
            "url": _scrub_text(ex.url, keys),
            "request_json": _scrub(ex.request_json, keys),
            "headers": headers,
            "body_json": _scrub(ex.body_json, keys),
            "body_text": None if ex.body_text is None else _scrub_text(ex.body_text, keys),
        }
    )


def find_pii(obj: Any, path: str = "$") -> list[str]:
    """Paths of strings (or keys) in which an email address or phone number survives."""
    found: list[str] = []
    if isinstance(obj, str):
        if EMAIL_RE.search(obj) or any(r.search(obj) for r in PHONE_RES):
            found.append(path)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(find_pii(item, f"{path}[{i}]"))
    elif isinstance(obj, dict):
        for key, item in obj.items():
            found.extend(find_pii(str(key), f"{path}.<key {key!r}>"))
            found.extend(find_pii(item, f"{path}.{key}"))
    return found


def trim_exchange(ex: RecordedExchange, sensor: str, max_items: int) -> RecordedExchange:
    """Keep at most `max_items` notices/results; strip `links` from every TED notice."""
    body = ex.body_json
    if not isinstance(body, dict):
        return ex
    body = dict(body)
    field = "notices" if sensor == "ted" else "results"
    items = body.get(field)
    if isinstance(items, list):
        items = items[:max_items]
        if sensor == "ted":
            items = [
                {k: v for k, v in n.items() if k != "links"} if isinstance(n, dict) else n
                for n in items
            ]
        body[field] = items
    return ex.model_copy(update={"body_json": body})


# --- recording ----------------------------------------------------------------------------


def _secrets_of(settings: Settings) -> tuple[str, ...]:
    key = settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else ""
    return (key,) if key else ()


async def record(
    calls: list[PlannedCall],
    settings: Settings,
    *,
    out_dir: Path,
    max_items: int,
    inner_factory: InnerFactory | None = None,
    sleep: Sleep = asyncio.sleep,
) -> int:
    """Send the planned calls and write redacted fixtures. Returns the exit code."""
    code = 0
    secrets = _secrets_of(settings)
    ted_calls = [c for c in calls if c.sensor == "ted"]
    tavily_calls = [c for c in calls if c.sensor == "tavily"]
    if tavily_calls and not secrets:
        print(
            "Tavily part skipped: TAVILY_API_KEY is not set (add it to .env or the environment).",
            file=sys.stderr,
        )
        tavily_calls = []
        code = 2
    if len(tavily_calls) > settings.tavily_max_calls_per_run:
        print(
            f"Tavily capped at {settings.tavily_max_calls_per_run} calls "
            f"(tavily_max_calls_per_run); {len(tavily_calls) - settings.tavily_max_calls_per_run} "
            "planned calls not sent."
        )
        tavily_calls = tavily_calls[: settings.tavily_max_calls_per_run]
    factory = inner_factory or httpx.AsyncHTTPTransport
    recorder = RecordingTransport(factory())
    written = 0
    try:
        async with httpx.AsyncClient(transport=recorder, timeout=60.0) as client:
            for i, call in enumerate(ted_calls):
                if i > 0:
                    await sleep(settings.ted_min_interval_seconds)
                before = len(recorder.exchanges)
                response = await client.post(call.url, json=call.body)
                if response.status_code == 429:
                    del recorder.exchanges[before:]
                    print(
                        "TED answered 429 (rate limited): stopping TED recording now, no retry.",
                        file=sys.stderr,
                    )
                    code = code or 3
                    break
                outcome = _finish(recorder, before, call, secrets, out_dir, max_items)
                written += outcome == 0
                code = code or outcome
            headers = {"Authorization": f"Bearer {secrets[0]}"} if secrets else {}
            for call in tavily_calls:
                before = len(recorder.exchanges)
                await client.post(call.url, json=call.body, headers=headers)
                outcome = _finish(recorder, before, call, secrets, out_dir, max_items)
                written += outcome == 0
                code = code or outcome
    finally:
        await recorder.aclose()
    print(f"wrote {written} fixture file(s) under {out_dir}")
    if ted_calls:
        print(f"TED attribution (already in tests/fixtures/sensors/README.md): {ATTRIBUTION}")
    print("Review every new fixture by eye before committing (sole traders, names in titles).")
    return code


def _finish(
    recorder: RecordingTransport,
    before: int,
    call: PlannedCall,
    secrets: tuple[str, ...],
    out_dir: Path,
    max_items: int,
) -> int:
    clean = [
        withhold_ted_persons(
            redact_exchange(trim_exchange(ex, call.sensor, max_items), secrets=secrets)
        )
        if call.sensor == "ted"
        else redact_exchange(trim_exchange(ex, call.sensor, max_items), secrets=secrets)
        for ex in recorder.exchanges[before:]
    ]
    target = out_dir / call.sensor / f"{call.client}_{call.n}.json"
    dumped = [e.model_dump(mode="json") for e in clean]
    pii = find_pii(dumped)
    if pii:
        print(
            f"REFUSED to write {target.name}: email/phone pattern survives at {', '.join(pii[:5])}",
            file=sys.stderr,
        )
        return 1
    if any(e.status >= 400 for e in clean):
        print(f"not written {target.name}: HTTP {clean[0].status}", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    save_exchanges(target, clean)
    print(f"wrote {call.sensor}/{target.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="record_sensor_fixtures.py",
        description="Record redacted TED and Tavily fixtures from the live APIs.",
    )
    parser.add_argument("--yes", action="store_true", help="actually call the live APIs")
    parser.add_argument(
        "--max-items", type=int, default=10, help="keep at most N notices/results per response"
    )
    parser.add_argument("--client", help="record only this client id")
    parser.add_argument("--print-plan", action="store_true", help="list planned calls, send none")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    clients_dir: Path = CLIENTS_DIR,
    out_dir: Path = OUT_DIR,
    settings: Settings | None = None,
    inner_factory: InnerFactory | None = None,
    sleep: Sleep = asyncio.sleep,
) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or get_settings()
    if args.max_items < 1:
        print("--max-items must be at least 1", file=sys.stderr)
        return 2
    calls = plan_calls(load_clients(clients_dir), settings, only=args.client)
    if args.print_plan or not args.yes:
        for c in calls:
            print(f"{c.sensor:7} {c.client}_{c.n}: {json.dumps(c.body, ensure_ascii=False)[:160]}")
        if not args.print_plan:
            print("\nNothing sent. Re-run with --yes to call the live APIs.", file=sys.stderr)
            return 1
        return 0
    return asyncio.run(
        record(
            calls,
            settings,
            out_dir=out_dir,
            max_items=args.max_items,
            inner_factory=inner_factory,
            sleep=sleep,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
