"""Onboarding API, "Build my radar" (D105).

Flow: start (email + website; claims the one free radar, D104) -> optional catalogue upload ->
propose (website + catalogue -> checked answers) -> the person confirms the answers -> the radar
runs once and its edition opens. Each step is a small request; slow work runs in the background
and the page polls `GET /api/onboarding/{id}`.

State is a JSON file per session in the reports folder (never committed), also saved in the
durable store so a restart of the free server loses nothing (D144). Website and catalogue text are
kept in separate files and never returned. The radar itself runs in its own process, one at a
time, started and watched by `api/supervisor.py`; this module only queues it.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from northvaine.api import accounts, durable, store
from northvaine.brain.budget import RunContext
from northvaine.core.models import NorthvaineModel
from northvaine.core.settings import get_settings
from northvaine.radar.models import REPO_ROOT
from northvaine.radar.onboarding import (
    OnboardingAnswers,
    Proposal,
    build_client_spec,
    check_codes_suggest,
    clean_text,
    client_id_for,
    intermediary_roles,
    propose,
    read_catalogue,
)
from northvaine.sensors.http import new_client

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

MAX_CATALOGUE_BYTES = 25 * 1024 * 1024
# D130: the run started from onboarding is a quick one, so a visitor is not left waiting half an
# hour. Applied to this run's settings only; the nightly run keeps the full profile.
QUICK_PROFILE: dict[str, int | bool] = {
    "radar_max_gate_candidates": 40,
    "radar_skeptic_top": 15,
    "radar_review_top": 5,
    "radar_fit_max_accounts": 10,  # D140: read more sites, so makers of the product show as such
    "radar_investigate_top": 1,
    # D140: a first radar reads the client's markets widely: project and partner searches in every
    # market, plus news of the client's own triggers
    "radar_intent_per_market": 2,
    "radar_market_news_per_market": 2,
    # D140: a first radar has no history, so a signal up to 6 months old is still news to the
    # client; and distributors are searched in every market, import records or not
    "radar_intent_days": 180,
    "radar_partner_all_markets": True,
    # D142: the free server has 512 MB; fewer parallel steps and smaller pages keep a first radar
    # well inside it
    "radar_gate_concurrency": 4,
    "radar_fit_concurrency": 3,
    "fetch_max_bytes": 2_000_000,
    # D143: pages are read by the model four at a time, not one after another (was 30+ minutes)
    "radar_ledger_concurrency": 4,
}
# D142: a first radar reads the client's first markets only (the nightly run reads them all)
QUICK_MAX_MARKETS = 6
# D144: what a typical first radar takes on the free server, for the queue estimate
TYPICAL_RUN_MINUTES = 12
_TASKS: set[asyncio.Task[None]] = set()

Stage = Literal["reading", "ready", "proposing", "proposed", "queued", "running", "done", "failed"]


def reports() -> Path:
    return store.reports_dir()


def clients_dir() -> Path:
    clients = Path(get_settings().onboarding_clients_dir)
    return clients if clients.is_absolute() else REPO_ROOT / clients


Base = Annotated[Path, Depends(reports)]


class StartIn(NorthvaineModel):
    email: str = Field(pattern=accounts._EMAIL, max_length=320)
    company: str = Field(min_length=1, max_length=200)
    website: str = Field(min_length=3, max_length=300)


class Catalogue(NorthvaineModel):
    pages: int
    readable: bool


class RoleOption(NorthvaineModel):
    key: str
    label: str


def _role_options() -> list[RoleOption]:
    return [RoleOption(key=r.key, label=r.label) for r in intermediary_roles()]


class Session(NorthvaineModel):
    id: str
    company: str
    website: str
    stage: Stage
    progress: str | None = None  # D130: the stage a running radar is in
    site_read: bool = False
    catalogue: Catalogue | None = None
    proposal: Proposal | None = None
    client_id: str | None = None
    error: str | None = None
    notes: list[str] = Field(default_factory=list)
    not_buyer_roles: list[RoleOption] = Field(default_factory=_role_options)
    created_at: str
    # D144: the run queue and its supervision
    queued_at: str | None = None
    as_of: str | None = None  # the run's moment, fixed once, so a resumed run repeats itself
    started_at: str | None = None
    heartbeat_at: str | None = None
    attempts: int = 0  # runs that stopped with an error
    resumes: int = 0  # runs cut short by a server restart
    last_error: str | None = None
    queue_position: int | None = None  # filled when read: 1 = next
    wait_minutes: int | None = None  # filled when read: a rough estimate


def _dir(base: Path) -> Path:
    path = base / "_onboarding"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load(base: Path, sid: str) -> Session:
    if not sid.isalnum() or len(sid) > 40:
        raise HTTPException(status_code=404, detail="not found")
    path = _dir(base) / f"{sid}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return Session.model_validate_json(path.read_text(encoding="utf-8"))


def _save(base: Path, session: Session) -> Session:
    text = session.model_dump_json(exclude={"queue_position", "wait_minutes"})
    (_dir(base) / f"{session.id}.json").write_text(text, encoding="utf-8")
    durable.save_later("onboarding", session.id, text)
    return session


def _update(base: Path, sid: str, **changes: Any) -> Session:
    return _save(base, _load(base, sid).model_copy(update=changes))


def _save_text(base: Path, name: str, text: str) -> None:
    (_dir(base) / f"{name}.txt").write_text(text, encoding="utf-8")
    durable.save_later("onboarding_text", name, text)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sessions(base: Path) -> list[Session]:
    """Every session on file (small: one file per visitor)."""
    found = []
    for path in _dir(base).glob("*.json"):
        try:
            found.append(Session.model_validate_json(path.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return found


def queue(base: Path) -> list[Session]:
    """Sessions waiting for or holding the run slot, in the order they were queued."""
    waiting = [s for s in sessions(base) if s.stage in ("queued", "running")]
    return sorted(waiting, key=lambda s: (s.stage != "running", s.queued_at or s.created_at))


def _spawn(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _homepage(website: str) -> tuple[str, str]:
    url = website if "//" in website else f"https://{website}"
    host = (urlsplit(url).hostname or "").lower()
    return f"https://{host}", host.removeprefix("www.")


async def _read_site(base: Path, sid: str, website: str) -> None:
    """The homepage plus up to four pages of the same site found by search, via Tavily."""
    from northvaine.sensors.base import SensorQuery
    from northvaine.sensors.tavily import TavilySensor

    settings = get_settings()
    home, domain = _homepage(website)
    try:
        async with new_client(60.0) as client:
            sensor = TavilySensor(client=client, settings=settings)
            found = await sensor.search(
                SensorQuery(text="products services about us", domains=[domain], max_results=5)
            )
            urls = [home] + [
                d.url
                for d in found.documents
                if (urlsplit(d.url).hostname or "").lower().removeprefix("www.") == domain
            ]
            pages = await sensor.extract(list(dict.fromkeys(urls))[:5])
        text = "\n\n".join(
            f"Page: {url}\n{clean_text(body, settings, 6000)}" for url, body in pages
        )
        _save_text(base, f"{sid}.site", text[:15_000])
        _update(base, sid, stage="ready", site_read=bool(text.strip()))
    except Exception as exc:  # the person can still continue from their own answers
        _update(
            base,
            sid,
            stage="ready",
            site_read=False,
            notes=[f"website not read: {type(exc).__name__}"],
        )


async def _propose(base: Path, sid: str) -> None:
    from northvaine.sensors.hmrc import hs6_descriptions

    for _ in range(120):  # wait for the website read (at most about two minutes)
        if _load(base, sid).stage != "reading":
            break
        await asyncio.sleep(1)
    _update(base, sid, stage="proposing")
    folder = _dir(base)
    site = (
        (folder / f"{sid}.site.txt").read_text(encoding="utf-8")
        if (folder / f"{sid}.site.txt").is_file()
        else ""
    )
    cat_path = folder / f"{sid}.catalogue.txt"
    catalogue = cat_path.read_text(encoding="utf-8") if cat_path.is_file() else ""
    try:
        proposal = await propose(
            site or "(the website could not be read)", catalogue, run=RunContext()
        )
        async with new_client(30.0) as client:
            known = await hs6_descriptions(proposal.hs_codes, client=client)
        unknown = [c for c in proposal.hs_codes if c not in known]
        in_tariff = {c: known[c] for c in proposal.hs_codes if c in known}
        kept, mismatch, better = await check_codes_suggest(
            proposal.offer, proposal.offer_terms, in_tariff, run=RunContext()
        )
        if better:  # D141: a code suggested in place of a dropped one, checked like the rest
            async with new_client(30.0) as client:
                found = await hs6_descriptions(better, client=client)
            again, _, _ = await check_codes_suggest(
                proposal.offer, proposal.offer_terms, found, run=RunContext()
            )
            for code in again:
                kept.append(code)
                in_tariff[code] = found[code]
                mismatch.append(f"customs code {code} added in its place: {found[code]}")
        proposal = proposal.model_copy(
            update={
                "hs_codes": kept,
                "hs_descriptions": {c: in_tariff[c] for c in kept},
                "dropped": [
                    *proposal.dropped,
                    *(f"customs code {c} is not in the UK tariff" for c in unknown),
                    *mismatch,
                ],
            }
        )
        _update(base, sid, stage="proposed", proposal=proposal)
    except Exception as exc:
        _update(
            base,
            sid,
            stage="failed",
            error=f"Could not prepare the answers ({type(exc).__name__}).",
        )


def recover(base: Path) -> list[str]:
    """After a restart: steps that ran inside the old web process start again (D144). Radar runs
    are picked up by the supervisor."""
    resumed = []
    for session in sessions(base):
        if session.stage == "reading":
            _spawn(_read_site(base, session.id, session.website))
            resumed.append(session.id)
        elif session.stage == "proposing":
            _spawn(_propose(base, session.id))
            resumed.append(session.id)
    return resumed


def _finished_ok(base: Path, sid: str | None) -> bool:
    if not sid:
        return True  # a claim from before sessions were recorded counts as used
    try:
        return _load(base, sid).stage == "done"
    except HTTPException:
        return False


@router.post("", status_code=201)
async def start(body: StartIn, base: Base) -> Session:
    email = accounts._email(body.email)
    if email not in accounts._subscribers(base):
        claimed = accounts.trial_sessions(base, email)
        # D144: the free radar is used once it has finished; a run that never finished (or was
        # never started) can be tried again
        if any(_finished_ok(base, sid) for sid in claimed):
            raise HTTPException(
                status_code=409,
                detail="The free radar for this email has been used. Talk to us to subscribe.",
            )
    session = Session(
        id=secrets.token_hex(12),
        company=body.company.strip(),
        website=body.website.strip(),
        stage="reading",
        created_at=_now(),
    )
    _save(base, session)
    if email not in accounts._subscribers(base):
        accounts.record_trial(base, email, session.id)
    _spawn(_read_site(base, session.id, session.website))
    return session


@router.get("/{sid}")
async def status(sid: str, base: Base) -> Session:
    session = _load(base, sid)
    if session.stage in ("queued", "running"):
        ids = [s.id for s in queue(base)]
        position = ids.index(sid) + 1 if sid in ids else 1
        waiting = position - 1 if session.stage == "queued" else 0
        session = session.model_copy(
            update={
                "queue_position": position,
                "wait_minutes": waiting * TYPICAL_RUN_MINUTES + TYPICAL_RUN_MINUTES,
            }
        )
    return session


@router.post("/{sid}/catalogue")
async def upload_catalogue(sid: str, request: Request, base: Base) -> Catalogue:
    _load(base, sid)
    if request.headers.get("content-type", "").split(";")[0] != "application/pdf":
        raise HTTPException(status_code=415, detail="Upload the catalogue as a PDF.")
    data = await request.body()
    if len(data) > MAX_CATALOGUE_BYTES:
        raise HTTPException(status_code=413, detail="The catalogue is over 25 MB.")
    try:
        read = await asyncio.to_thread(read_catalogue, data)
    except Exception:
        raise HTTPException(
            status_code=422, detail="That file could not be read as a PDF."
        ) from None
    _save_text(base, f"{sid}.catalogue", read.text)
    catalogue = Catalogue(pages=read.pages, readable=read.readable)
    _update(base, sid, catalogue=catalogue)
    return catalogue


@router.post("/{sid}/propose")
async def start_proposal(sid: str, base: Base) -> Session:
    session = _load(base, sid)
    if session.stage in ("proposing", "queued", "running", "done"):
        return session
    session = _update(base, sid, stage="proposing" if session.stage != "reading" else "reading")
    _spawn(_propose(base, sid))
    return session


@router.post("/{sid}/answers")
async def confirm(sid: str, answers: OnboardingAnswers, base: Base) -> Session:
    session = _load(base, sid)
    if session.stage in ("queued", "running", "done"):
        return session
    clients = clients_dir()
    clients.mkdir(parents=True, exist_ok=True)
    client_id = client_id_for(answers.website)
    spec = build_client_spec(answers, client_id=client_id, today=datetime.now(UTC).date())
    text = json.dumps(spec.model_dump(mode="json"), indent=2, ensure_ascii=False)
    (clients / f"{client_id}.json").write_text(text, encoding="utf-8")
    durable.save_later("client", client_id, text)
    now = _now()
    session = _update(
        base,
        sid,
        stage="queued",
        client_id=client_id,
        queued_at=now,
        as_of=datetime.now(UTC).isoformat(),
        error=None,
    )
    from northvaine.api import supervisor

    supervisor.wake()
    return await status(sid, base)
