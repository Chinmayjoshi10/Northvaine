"""Read-only endpoints over saved radar runs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from northvaine.api import store, views
from northvaine.api.feedback import Base
from northvaine.core.settings import Settings

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
    """`day` is a date, or `latest`."""
    run, _ = store.load_run(base, client, store.resolve_day(base, client, day))
    return views.brief_view(run, Settings(_env_file=None))


@router.get("/clients/{client}/runs/{day}/entries/{rank}")
def get_entry(client: str, day: str, rank: int, base: Base) -> views.Dossier:
    run, raw = store.load_run(base, client, store.resolve_day(base, client, day))
    for index, entry in enumerate(run.entries):
        if entry.rank == rank:
            bidders = raw["entries"][index].get("likely_bidders") or []
            return views.dossier(entry, bidders, Settings(_env_file=None))
    raise HTTPException(status_code=404, detail="entry not found")
