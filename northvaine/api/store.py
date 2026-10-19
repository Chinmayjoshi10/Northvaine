"""Read run records and append feedback on disk. No database.

Runs live at `<reports>/<client>/<YYYY-MM-DD>/run.json` (written by scripts/radar.py). Feedback is
append-only JSON lines at `<reports root>/feedback/<client>.jsonl`, next to the radar folder.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from northvaine.core.settings import Settings
from northvaine.radar.lessons import Learning, learn_from_files
from northvaine.radar.models import REPO_ROOT, LikelyBidder, RadarRun

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def reports_dir() -> Path:
    """The radar reports folder (settings.radar_reports_dir). Tests override this dependency."""
    configured = Path(Settings(_env_file=None).radar_reports_dir)
    return configured if configured.is_absolute() else REPO_ROOT / configured


def check_client(client: str) -> str:
    if not _ID.match(client) or ".." in client:
        raise HTTPException(status_code=404, detail="unknown client")
    return client


def check_day(day: str) -> str:
    if not _DAY.match(day):
        raise HTTPException(status_code=404, detail="unknown run")
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown run") from None
    return day


def run_days(base: Path, client: str) -> list[str]:
    """Run dates for a client, newest first."""
    folder = base / check_client(client)
    if not folder.is_dir():
        return []
    days = [p.name for p in folder.iterdir() if _DAY.match(p.name) and (p / "run.json").is_file()]
    return sorted(days, reverse=True)


def client_ids(base: Path) -> list[str]:
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and _ID.match(p.name))


def resolve_day(base: Path, client: str, day: str) -> str:
    """`latest` becomes the newest run date; anything else must be a real date."""
    if day == "latest":
        days = run_days(base, client)
        if not days:
            raise HTTPException(status_code=404, detail="no run for this client")
        return days[0]
    return check_day(day)


def load_run(base: Path, client: str, day: str) -> tuple[RadarRun, dict]:
    """(validated run, raw json). The raw dict is kept so fields newer than this build's model
    (for example `likely_bidders`) still reach the page."""
    path = base / check_client(client) / check_day(day) / "run.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="run not found")
    raw = json.loads(path.read_text(encoding="utf-8"))
    cleaned = json.loads(json.dumps(raw))
    for entry in cleaned.get("entries", []):
        entry["likely_bidders"] = [
            b for b in entry.get("likely_bidders") or [] if _valid_bidder(b)
        ]  # an older build wrote bidders without the verified quote: those are dropped
    return RadarRun.model_validate(cleaned), raw


def _valid_bidder(item: object) -> bool:
    try:
        LikelyBidder.model_validate(item)
    except ValidationError:
        return False
    return True


def feedback_path(base: Path, client: str) -> Path:
    return base.parent / "feedback" / f"{check_client(client)}.jsonl"


def append_feedback(base: Path, client: str, line: str) -> None:
    path = feedback_path(base, client)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def read_feedback(base: Path, client: str) -> list[dict]:
    path = feedback_path(base, client)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def approved_leads(base: Path, client: str) -> list[str]:
    """Company names the client marked "Approach them" (`accepted_for_contact`), judged by the
    latest answer for each company (D109)."""
    latest: dict[str, tuple[str, bool]] = {}
    for row in read_feedback(base, client):
        name = str(row.get("company") or "").strip()
        answer = row.get("accepted_for_contact")
        if name and isinstance(answer, bool):
            latest[name.casefold()] = (name, answer)
    return [name for name, accepted in latest.values() if accepted]


def client_learning(base: Path, client: str, settings: Settings | None = None) -> Learning:
    """What a client's saved answers taught (D100), from the feedback file and the runs it
    answers. A run that is no longer on file is skipped, never guessed."""
    records = read_feedback(base, client)
    runs: dict[str, RadarRun] = {}
    for day in sorted({str(r.get("as_of")) for r in records}):
        try:
            runs[day] = load_run(base, client, day)[0]
        except HTTPException:
            continue
    return learn_from_files(records, runs, settings=settings)
