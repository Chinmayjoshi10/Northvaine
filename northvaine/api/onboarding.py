"""Onboarding API, "Build my radar" (D105).

Flow: start (email + website; claims the one free radar, D104) -> optional catalogue upload ->
propose (website + catalogue -> checked answers) -> the person confirms the answers -> the radar
runs once and its edition opens. Each step is a small request; slow work runs in the background
and the page polls `GET /api/onboarding/{id}`.

State is a JSON file per session in the reports folder (never committed). Website and catalogue
text are kept in separate files and never returned. One radar run at a time.
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

from northvaine.api import accounts, store
from northvaine.brain.budget import RunContext
from northvaine.core.models import NorthvaineModel
from northvaine.core.settings import get_settings
from northvaine.radar.brief import write_reports
from northvaine.radar.models import REPO_ROOT
from northvaine.radar.onboarding import (
    OnboardingAnswers,
    Proposal,
    build_client_spec,
    clean_text,
    client_id_for,
    intermediary_roles,
    propose,
    read_catalogue,
)
from northvaine.sensors.http import new_client

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

MAX_CATALOGUE_BYTES = 25 * 1024 * 1024
_RUN_SLOT = asyncio.Semaphore(1)
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
}
_TASKS: set[asyncio.Task[None]] = set()

Stage = Literal["reading", "ready", "proposing", "proposed", "running", "done", "failed"]


def reports() -> Path:
    return store.reports_dir()


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
    (_dir(base) / f"{session.id}.json").write_text(session.model_dump_json(), encoding="utf-8")
    return session


def _update(base: Path, sid: str, **changes: Any) -> Session:
    return _save(base, _load(base, sid).model_copy(update=changes))


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
        (_dir(base) / f"{sid}.site.txt").write_text(text[:15_000], encoding="utf-8")
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
        proposal = proposal.model_copy(
            update={
                "hs_codes": [c for c in proposal.hs_codes if c in known],
                "dropped": [
                    *proposal.dropped,
                    *(f"customs code {c} is not in the UK tariff" for c in unknown),
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


async def _run(base: Path, sid: str, client_id: str) -> None:
    from northvaine.radar.live import run_live
    from northvaine.radar.models import load_client_spec

    settings = get_settings()
    clients = Path(settings.onboarding_clients_dir)
    clients = clients if clients.is_absolute() else REPO_ROOT / clients
    quick = settings.model_copy(update=QUICK_PROFILE)

    def progress(stage: str) -> None:
        _update(base, sid, progress=stage)

    try:
        async with _RUN_SLOT:
            _update(base, sid, stage="running")
            spec = load_client_spec(client_id, clients)
            run = await run_live(spec, as_of=datetime.now(UTC), settings=quick, progress=progress)
            write_reports(run, base)
        _update(base, sid, stage="done", client_id=client_id)
    except Exception as exc:
        _update(base, sid, stage="failed", error=f"The radar run stopped ({type(exc).__name__}).")


@router.post("", status_code=201)
async def start(body: StartIn, base: Base) -> Session:
    email = accounts._email(body.email)
    if email not in accounts._subscribers(base):
        if accounts._trial_used(base, email):
            raise HTTPException(
                status_code=409,
                detail="The free radar for this email has been used. Talk to us to subscribe.",
            )
        accounts._append(base / accounts.TRIALS, {"email": email, "claimed_at": accounts._now()})
    session = Session(
        id=secrets.token_hex(12),
        company=body.company.strip(),
        website=body.website.strip(),
        stage="reading",
        created_at=accounts._now(),
    )
    _save(base, session)
    _spawn(_read_site(base, session.id, session.website))
    return session


@router.get("/{sid}")
async def status(sid: str, base: Base) -> Session:
    return _load(base, sid)


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
    (_dir(base) / f"{sid}.catalogue.txt").write_text(read.text, encoding="utf-8")
    catalogue = Catalogue(pages=read.pages, readable=read.readable)
    _update(base, sid, catalogue=catalogue)
    return catalogue


@router.post("/{sid}/propose")
async def start_proposal(sid: str, base: Base) -> Session:
    session = _load(base, sid)
    if session.stage in ("proposing", "running", "done"):
        return session
    session = _update(base, sid, stage="proposing" if session.stage != "reading" else "reading")
    _spawn(_propose(base, sid))
    return session


@router.post("/{sid}/answers")
async def confirm(sid: str, answers: OnboardingAnswers, base: Base) -> Session:
    session = _load(base, sid)
    if session.stage in ("running", "done"):
        return session
    settings = get_settings()
    clients = Path(settings.onboarding_clients_dir)
    clients = clients if clients.is_absolute() else REPO_ROOT / clients
    clients.mkdir(parents=True, exist_ok=True)
    client_id = client_id_for(answers.website)
    spec = build_client_spec(answers, client_id=client_id, today=datetime.now(UTC).date())
    (clients / f"{client_id}.json").write_text(
        json.dumps(spec.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    session = _update(base, sid, stage="running", client_id=client_id)
    _spawn(_run(base, sid, client_id))
    return session
