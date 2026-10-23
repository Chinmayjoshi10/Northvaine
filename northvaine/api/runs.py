"""Read-only endpoints over saved radar runs."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from northvaine.api import store, views
from northvaine.api.feedback import Base
from northvaine.api.leadview import supply_phrase
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.graph import GraphView, run_graph
from northvaine.radar.models import REPO_ROOT, ClientSpec, RadarRun, load_client_spec

router = APIRouter(prefix="/api", tags=["runs"])


class ClientSummary(BaseModel):
    client_id: str
    offer: str | None
    latest: str | None
    runs: list[str]
    accounts: int
    tenders: int


@router.get("/clients")
def list_clients(base: Base) -> list[ClientSummary]:
    out = []
    for client in store.client_ids(base):
        days = store.run_days(base, client)
        offer, accounts, tenders = None, 0, 0
        if days:
            run, _ = store.load_run(base, client, days[0])
            view = views.brief_view(run, Settings(_env_file=None))
            offer, accounts, tenders = view.offer, len(view.accounts), len(view.tenders)
        out.append(
            ClientSummary(
                client_id=client,
                offer=offer,
                latest=days[0] if days else None,
                runs=days,
                accounts=accounts,
                tenders=tenders,
            )
        )
    return out


@router.get("/clients/{client}/runs/{day}")
def get_run(client: str, day: str, base: Base) -> views.BriefView:
    """`day` is a date, or `latest`. Rows say whether the previous run briefed them too."""
    resolved = store.resolve_day(base, client, day)
    run, _ = store.load_run(base, client, resolved)
    earlier = [d for d in store.run_days(base, client) if d < resolved]
    previous = store.load_run(base, client, max(earlier))[0] if earlier else None
    settings = Settings(_env_file=None)
    history: list[RadarRun] = []
    for d in earlier[: settings.radar_watch_runs]:  # run_days is newest first
        try:
            history.append(store.load_run(base, client, d)[0])
        except (HTTPException, ValueError):  # unreadable or unfit for this build: skipped
            continue
    return views.brief_view(run, settings, previous, history, _find_spec(client))


@router.get("/clients/{client}/runs/{day}/entries/{rank}")
def get_entry(client: str, day: str, rank: int, base: Base) -> views.Dossier:
    run, raw = store.load_run(base, client, store.resolve_day(base, client, day))
    for index, entry in enumerate(run.entries):
        if entry.rank == rank:
            bidders = raw["entries"][index].get("likely_bidders") or []
            supply = supply_phrase(_find_spec(client), run.offer)
            return views.dossier(entry, bidders, Settings(_env_file=None), supply)
    raise HTTPException(status_code=404, detail="entry not found")


@router.get("/clients/{client}/runs/{day}/graph")
def get_graph(client: str, day: str, base: Base) -> GraphView:
    """The web of one run: companies, events and the lines between them, each with its quotes."""
    run, _ = store.load_run(base, client, store.resolve_day(base, client, day))
    return run_graph(run, Settings(_env_file=None))


class Searches(BaseModel):
    source: str
    count: int


class BusinessView(BaseModel):
    """Your business: what the radar was told about the client, read-only (D105). Customer
    names stay out of the page; only their number is shown."""

    client_id: str
    name: str | None
    offer: str
    markets: list[str]
    offer_terms: list[str]
    related_terms: list[str]
    buyer_roles: list[str]
    not_buyers: list[str]
    product_codes: list[str]
    existing_customers: int
    searches: list[Searches]


def _spec_dirs() -> list[Path]:
    settings = get_settings()
    dirs = [Path(settings.onboarding_clients_dir), Path(settings.radar_clients_dir)]
    return [d if d.is_absolute() else REPO_ROOT / d for d in dirs]


def _find_spec(client: str) -> ClientSpec | None:
    """The client's saved spec when there is one (for the line to open with); else None."""
    store.check_client(client)
    for folder in _spec_dirs():
        try:
            if (folder / f"{client}.json").is_file():
                return load_client_spec(client, folder)
        except ValueError:
            continue
    return None


@router.get("/clients/{client}/business")
def get_business(client: str) -> BusinessView:
    store.check_client(client)
    for folder in _spec_dirs():
        if (folder / f"{client}.json").is_file():
            spec = load_client_spec(client, folder)
            break
    else:
        raise HTTPException(status_code=404, detail="no business profile for this client")
    return BusinessView(
        client_id=spec.id,
        name=spec.name,
        offer=spec.offer,
        markets=list(spec.markets),
        offer_terms=spec.offer_terms,
        related_terms=spec.related_terms,
        buyer_roles=spec.buyer_roles,
        not_buyers=spec.not_buyers,
        product_codes=spec.product_codes,
        existing_customers=len(spec.existing_customers),
        searches=[Searches(source=k, count=len(v)) for k, v in sorted(spec.sensors.items())],
    )
