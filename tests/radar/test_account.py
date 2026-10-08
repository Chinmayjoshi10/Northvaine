"""Account role, contract nature and commercial evidence levels (D94). Code only."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from northvaine.core.settings import Settings
from northvaine.radar.account import account_role, contract_nature, evidence_level
from northvaine.radar.models import Candidate, CandidateEvent, RadarStream

SETTINGS = Settings(_env_file=None)


def candidate(stream: RadarStream, roles: list[str], **slots: Any) -> Candidate:
    return Candidate(
        key="k",
        name="Acme",
        country="FR",
        aliases=[],
        roles=roles,
        stream=stream,
        streams=[stream],
        events=[
            CandidateEvent(
                event_type="tender_published",
                description="d",
                occurred_on=date(2026, 10, 1),
                available_at=None,
                claim_refs=[],
                slots=slots,
                fingerprint="f",
            )
        ],
        claims=[],
        window_start=None,
        window_end=None,
        window_estimated=False,
        window_note="",
    )


@pytest.mark.parametrize(
    ("slots", "expected"),
    [
        ({"contract_nature": "supplies"}, ("supplies", False)),
        ({"contract_nature": "goods"}, ("supplies", False)),  # OCDS wording
        ({"contract_nature": "CW"}, ("works", False)),  # World Bank code
        ({"contract_nature": "supplies, works"}, ("mixed", False)),
        ({"cpv_codes": "45233250"}, ("works", True)),  # derived from the CPV division
        ({"cpv_codes": "33191000"}, ("supplies", True)),
        ({"cpv_codes": "79000000"}, ("services", True)),
        ({"contract_nature": "services", "cpv_codes": "45233250"}, ("services", False)),
        ({}, (None, True)),
    ],
)
def test_the_stated_nature_wins_and_cpv_only_derives(
    slots: dict[str, str], expected: tuple[str | None, bool]
) -> None:
    assert contract_nature(candidate(RadarStream.TENDER, ["buyer"], **slots), SETTINGS) == expected


def test_a_works_authority_is_never_the_material_buyer() -> None:
    c = candidate(RadarStream.TENDER, ["buyer"])
    assert account_role(c, "works") == "demand_source"
    assert account_role(c, "services") == "demand_source"
    assert account_role(c, None) == "demand_source"
    assert account_role(c, "supplies") == "direct_purchaser"


def test_an_award_winner_is_an_account_unless_it_supplies_the_goods() -> None:
    c = candidate(RadarStream.AWARD, ["winner"])
    assert account_role(c, "works") == "awarded_contractor"
    assert account_role(c, "supplies") == "supplier"
    assert account_role(candidate(RadarStream.ANNOUNCEMENT, ["investor"]), None) == "unresolved"


@pytest.mark.parametrize(
    ("requirement", "role", "direct", "level"),
    [
        ("stated", "direct_purchaser", None, "explicit_purchase"),
        ("related", "direct_purchaser", None, "project_requirement"),
        ("stated", "demand_source", True, "project_requirement"),
        ("stated", "awarded_contractor", True, "project_requirement"),
        ("stated", "supplier", True, "generic_mention"),
        ("stated", "unresolved", True, "explicit_purchase"),
        ("stated", "unresolved", None, "generic_mention"),
        ("related", "unresolved", True, "generic_mention"),
        ("inferred", "direct_purchaser", True, "no_evidence"),
    ],
)
def test_evidence_levels(requirement: str, role: Any, direct: bool | None, level: str) -> None:
    assert evidence_level(requirement, role, direct) == level
