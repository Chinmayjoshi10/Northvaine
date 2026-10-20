"""D116: distributors as a channel. Gate verdict by channel, the accounts-type size signal,
ranking of possible distributors, onboarding. Invented companies; no network."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from northvaine.brain import llm
from northvaine.brain.budget import RunContext
from northvaine.brain.replay import LEGACY_SETTINGS
from northvaine.radar.account import size_rank
from northvaine.radar.brief import apply_fit_order
from northvaine.radar.gate import gate_candidate
from northvaine.radar.models import ClientSpec, RegisterFacts
from northvaine.radar.onboarding import OnboardingAnswers, build_client_spec
from northvaine.radar.register import register_check
from northvaine.sensors.companies_house import parse_record, render_register_text
from tests.radar import test_gate as g
from tests.radar.test_fit_d108 import named
from tests.radar.test_gate import _env  # noqa: F401  (autouse: model and budget environment)
from tests.radar.test_register_edition import NOW, PROFILES, SETTINGS, register, spec
from tests.radar.test_trade_stream import importer


async def gate_with(channel: str, verdict: str) -> Any:
    client = g.FakeClient(g.reply(verdict=verdict, direct_buyer=None))
    chosen = ClientSpec(
        id="c", offer="an offer to serve plants", markets=["FR"], sensors={}, channel=channel
    )
    with llm.client_override(client):
        return await gate_candidate(g.make_candidate(), chosen, run=RunContext())


async def test_direct_channel_still_rejects_a_reseller() -> None:
    decision = await gate_with("direct", "reseller")
    assert not decision.passed and decision.rejected_as == "reseller" and not decision.partner


@pytest.mark.parametrize("channel", ["distributors", "both"])
async def test_distributor_channels_pass_a_reseller_as_possible_distributor(channel: str) -> None:
    decision = await gate_with(channel, "reseller")
    assert decision.passed and decision.rejected_as is None and decision.partner
    assert decision.cited_refs == ["C1"]


@pytest.mark.parametrize("channel", ["direct", "distributors", "both"])
async def test_competitor_is_always_rejected(channel: str) -> None:
    decision = await gate_with(channel, "competitor")
    assert not decision.passed and decision.rejected_as == "competitor"


@pytest.mark.parametrize("verdict", ["publisher", "not_a_buyer", "not_an_organisation"])
async def test_other_rejections_unchanged_for_distributor_channel(verdict: str) -> None:
    assert not (await gate_with("both", verdict)).passed


async def test_end_buyer_still_passes_when_channel_is_distributors() -> None:
    decision = await gate_with("distributors", "buyer")
    assert decision.passed and not decision.partner


def test_old_spec_without_channel_loads_as_direct() -> None:
    old = {"id": "c", "offer": "o", "markets": ["GB"], "sensors": {}}
    assert ClientSpec.model_validate(old).channel == "direct"


# --- size signal --------------------------------------------------------------------------


def test_accounts_type_parsed_without_figures() -> None:
    profile = {
        "company_number": "00000009",
        "company_name": "EXAMPLE STOCKISTS LIMITED",
        "company_status": "active",
        "accounts": {
            "last_accounts": {"type": "small", "made_up_to": "2025-12-31", "net_assets": 123456},
            "next_due": "2027-09-30",
        },
    }
    record = parse_record(profile, None)
    assert record.accounts_type == "small"
    text = render_register_text(record)
    assert "Accounts type: small" in text
    assert "123456" not in text and "2025-12-31" not in text and "2027" not in text
    assert "123456" not in record.model_dump_json()


def test_missing_accounts_give_no_type_and_no_line() -> None:
    record = parse_record({"company_number": "1", "company_name": "X LTD"}, None)
    assert record.accounts_type is None and "Accounts type" not in render_register_text(record)


def test_size_rank_order() -> None:
    order = ["dormant", "micro-entity", "small", "medium"]
    ranks = [size_rank(t) for t in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == 4
    assert size_rank("group") == size_rank("full") == size_rank("medium")
    assert size_rank("total-exemption-full") == size_rank("small")
    assert size_rank("micro-entity") < size_rank("total-exemption-full")
    assert size_rank("dormant") < size_rank(None) <= size_rank("micro-entity")


async def run_register(settings: Any) -> Any:
    profiles = {k: dict(v) for k, v in PROFILES.items()}
    profiles["00000001"]["accounts"] = {"last_accounts": {"type": "micro-entity"}}
    async with httpx.AsyncClient(transport=register(profiles)) as http:
        kept, _, _ = await register_check(
            [importer("New Imports Ltd", new=True)],
            spec(),
            http=http,
            as_of=NOW,
            settings=settings,
        )
    return kept[0]


async def test_accounts_type_becomes_a_verified_register_claim() -> None:
    kept = await run_register(SETTINGS)
    assert (
        kept.company_register is not None and kept.company_register.accounts_type == "micro-entity"
    )
    claim = next(c for c in kept.claims if c.source_quote == "Accounts type: micro-entity")
    assert claim.verified_by == "code" and claim.source_name == "companies_house"


async def test_legacy_setting_skips_the_accounts_claim() -> None:
    assert LEGACY_SETTINGS["radar_register_accounts_type"] is False
    kept = await run_register(SETTINGS.model_copy(update={"radar_register_accounts_type": False}))
    assert kept.company_register is not None and kept.company_register.accounts_type is None
    assert not any("Accounts type" in c.source_quote for c in kept.claims)


# --- ranking ------------------------------------------------------------------------------


def partner(key: str, rank: int, accounts_type: str | None, is_partner: bool = True) -> Any:
    e = named(key, {"codes": "1"}, rank=rank)
    facts = RegisterFacts(number=key, status="active", accounts_type=accounts_type)
    c = e.candidate.model_copy(update={"company_register": facts})
    gate = e.gate.model_copy(update={"partner": is_partner})
    return e.model_copy(update={"candidate": c, "gate": gate, "evidence_level": "generic_mention"})


def test_larger_possible_distributor_ranks_first_on_a_tie() -> None:
    entries = [partner("a", 1, "micro-entity"), partner("b", 2, "full"), partner("c", 3, "small")]
    out = apply_fit_order(entries, 180, False)
    assert [e.candidate.key for e in out] == ["b", "c", "a"]
    assert "Possible distributor: sells your kind of product; size: full" in out[0].rank_reasons


def test_non_partners_keep_their_order_and_get_no_reason() -> None:
    entries = [partner("a", 1, "micro-entity", False), partner("b", 2, "full", False)]
    out = apply_fit_order(entries, 180, False)
    assert [e.candidate.key for e in out] == ["a", "b"]
    assert not any(r.startswith("Possible distributor") for e in out for r in e.rank_reasons)


# --- onboarding ---------------------------------------------------------------------------

ANSWERS: dict[str, Any] = dict(
    company="Example Works",
    website="example.test",
    offer="Maker of cast iron garden benches and park bins for councils and retailers.",
    offer_terms=["garden benches"],
    markets=["GB"],
    buyer_roles=["councils"],
)


def test_new_onboarding_defaults_to_both_and_sets_the_spec() -> None:
    answers = OnboardingAnswers(**ANSWERS)
    assert answers.channel == "both"
    built = build_client_spec(answers, client_id="x", today=date(2026, 10, 16))
    assert built.channel == "both"


def test_onboarding_channel_choice_reaches_the_spec() -> None:
    answers = OnboardingAnswers(**ANSWERS, channel="direct")
    built = build_client_spec(answers, client_id="x", today=date(2026, 10, 16))
    assert built.channel == "direct"
