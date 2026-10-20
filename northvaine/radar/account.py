"""Who the account is and how strong its buying evidence is (D94). Code only, no model.

A tender's authority is not automatically the buyer of what the client sells. It is the buyer
when the contract is for **supplies** (it purchases the goods itself). For **works** and
**services**, the material buyer is the future winner, so the authority is a demand source.
After an award, the winner of a works or services contract is the account to approach. The
winner of a supplies contract sells that kind of product: a competitor or a channel.

Evidence levels (ChatGPT CEO, COLLAB.md 9 Oct), strongest first:

| Level | Meaning |
| --- | --- |
| `explicit_purchase` | a verified quote names what the client sells, and the account buys it |
| `proven_buyer` | official trade records show it imports the client's product codes (D102) |
| `project_requirement` | the project needs it, but the material buyer still has to be traced |
| `company_fit` | the company handles the category, no dated purchase (website check, later) |
| `generic_mention` | a matching word with no supported commercial relationship |
| `no_evidence` | inference only |

Only `explicit_purchase` can earn "contact now" (or "bid now" for a supply tender).
"""

from __future__ import annotations

from typing import Literal

from northvaine.core.settings import Settings, get_settings
from northvaine.radar.models import Candidate, RadarStream

__all__ = [
    "LEVEL_ORDER",
    "AccountRole",
    "EvidenceLevel",
    "account_role",
    "contract_nature",
    "evidence_level",
    "size_rank",
]

AccountRole = Literal[
    "direct_purchaser",
    "demand_source",
    "awarded_contractor",
    "supplier",
    "importer_of_record",
    "unresolved",
]
EvidenceLevel = Literal[
    "explicit_purchase",
    "proven_buyer",
    "project_requirement",
    "company_fit",
    "generic_mention",
    "no_evidence",
]
LEVEL_ORDER: dict[str, int] = {
    "explicit_purchase": 0,
    "proven_buyer": 1,
    "project_requirement": 2,
    "company_fit": 3,
    "generic_mention": 4,
    "no_evidence": 5,
}


def _one(values: set[str]) -> str | None:
    if not values:
        return None
    return next(iter(values)) if len(values) == 1 else "mixed"


def contract_nature(
    candidate: Candidate, settings: Settings | None = None
) -> tuple[str | None, bool]:
    """(supplies | works | services | mixed | None, derived). The record's own stated nature
    wins; otherwise it is derived from the CPV division of the record's codes."""
    cfg = settings or get_settings()
    aliases = {k.casefold(): v for k, v in cfg.radar_contract_nature_aliases.items()}
    stated: set[str] = set()
    codes: list[str] = []
    for event in candidate.events:
        raw = event.slots.get("contract_nature")
        if isinstance(raw, str):
            for part in (p.strip().casefold() for p in raw.split(",")):
                if part in aliases:
                    stated.add(aliases[part])
        cpv = event.slots.get("cpv_codes")
        if isinstance(cpv, str):
            codes += [c.strip() for c in cpv.split(",") if c.strip()]
    if stated:
        return _one(stated), False
    derived: set[str] = set()
    for code in codes:
        digits = "".join(ch for ch in code if ch.isdigit())
        if len(digits) < 2:
            continue
        division = int(digits[:2])
        for low, high, nature in cfg.radar_contract_nature_by_cpv_division:
            if low <= division <= high:
                derived.add(nature)
                break
    return _one(derived), True


_SIZE_RANK = {
    "dormant": 0,
    "micro-entity": 1,
    "small": 2,
    "total-exemption-small": 2,
    "total-exemption-full": 2,
    "unaudited-abridged": 2,
    "audited-abridged": 2,
    "partial-exemption": 2,
    "medium": 3,
    "full": 3,
    "group": 3,
}


def size_rank(accounts_type: str | None) -> int:
    """Company size from the type of its last filed accounts (D116): dormant 0, micro 1, small
    or exempt 2, medium, full or group 3. Not stated or unknown counts as micro (1)."""
    return _SIZE_RANK.get((accounts_type or "").strip().lower(), 1)


def account_role(candidate: Candidate, nature: str | None) -> AccountRole:
    """The account's commercial role, from its role in official records and the nature."""
    roles = set(candidate.roles)
    if candidate.stream == RadarStream.TENDER and "buyer" in roles:
        return "direct_purchaser" if nature == "supplies" else "demand_source"
    if candidate.stream == RadarStream.AWARD and "winner" in roles:
        return "supplier" if nature == "supplies" else "awarded_contractor"
    if candidate.stream == RadarStream.TRADE and "importer" in roles:
        return "importer_of_record"
    return "unresolved"


def evidence_level(requirement: str, role: AccountRole, direct_buyer: bool | None) -> EvidenceLevel:
    """The commercial evidence level of an entry (strongest first, see the module doc)."""
    if requirement == "inferred":
        return "no_evidence"
    if role == "supplier":
        return "generic_mention"  # it sells this kind of product: a competitor or a channel
    if role == "importer_of_record":
        # official records of the client's own product codes: proof it buys, not a live order
        return "proven_buyer" if requirement == "stated" else "generic_mention"
    if role == "direct_purchaser":
        return "explicit_purchase" if requirement == "stated" else "project_requirement"
    if role in ("demand_source", "awarded_contractor"):
        return "project_requirement"
    # An announcement: a launch or plan implies a need but never states a purchase, and a
    # matched word is not a purchase (CEO review, 9 Oct). It stays a project requirement at most,
    # so it is never "contact now" on a word match alone.
    if requirement == "stated" and direct_buyer is True:
        return "project_requirement"
    return "generic_mention"
