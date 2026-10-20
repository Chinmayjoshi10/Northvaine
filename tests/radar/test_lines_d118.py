"""D118: catalogue lines and distinctive words."""

from __future__ import annotations

from typing import Any

from northvaine.core.settings import Settings
from northvaine.radar import fit as fit_module
from northvaine.radar.brief import apply_fit_order, match_lines
from northvaine.radar.fit import company_fit, fit_sentences
from northvaine.radar.models import CatalogueLine, FitEvidence, RankedEntry
from tests.radar.test_fit import NOW, SPEC, FakeFetcher, FakeSensor, entry
from tests.radar.test_fit_d108 import named

CFG = Settings(_env_file=None)
LINES = [
    CatalogueLine(name="Premium", terms=["marble"], codes=["hs:6802"]),
    CatalogueLine(name="Basic", terms=["gravel"], codes=["hs:2517"]),
]
RECORD = "The official import record states commodity {} (an article)."


def _fit(term: str) -> FitEvidence:
    return FitEvidence(
        url="u", quote=f"We supply {term} to builders.", term=term, level="stated", fingerprint="f"
    )


def _entry(
    key: str, rank: int, *, code: str | None = None, term: str | None = None, distinct: bool = False
) -> RankedEntry:
    e = named(key, {"months_active": 3} if code else None, rank=rank,
              description=RECORD.format(code) if code else "d")  # fmt: skip
    return e.model_copy(
        update={
            "evidence_level": "project_requirement",
            "fit_level": "stated" if term else None,
            "company_fit": [_fit(term)] if term else [],
            "fit_distinctive": distinct,
        }
    )


def test_lines_match_by_import_code_prefix_and_by_fit_term() -> None:
    assert match_lines(_entry("a", 1, code="68022100"), LINES) == ["Premium"]
    assert match_lines(_entry("b", 1, term="gravel"), LINES) == ["Basic"]
    both = _entry("c", 1, code="25171000", term="marble")
    assert match_lines(both, LINES) == ["Premium", "Basic"]  # the client's order
    assert match_lines(_entry("d", 1, code="99999999"), LINES) == []


def test_best_line_ranks_first_and_reason_is_added() -> None:
    entries = [
        _entry("none", 1),
        _entry("basic", 2, term="gravel"),
        _entry("prem", 3, term="marble"),
    ]
    out = apply_fit_order(entries, 180, False, lines=LINES)
    assert [e.candidate.key for e in out] == ["prem", "basic", "none"]
    assert out[0].matched_lines == ["Premium"]
    assert "Matches your catalogue line: Premium" in out[0].rank_reasons


def test_empty_lines_leave_the_order_alone() -> None:
    entries = [_entry("x", 1), _entry("y", 2, term="marble"), _entry("z", 3, term="gravel")]
    out = apply_fit_order(entries, 180, False)
    assert [e.candidate.key for e in out] == ["y", "z", "x"]  # fit order only
    assert all(e.matched_lines == [] for e in out)


def test_stated_distinctive_ranks_above_stated_common() -> None:
    entries = [
        _entry("common", 1, term="granite"),
        _entry("distinct", 2, term="marble", distinct=True),
    ]
    out = apply_fit_order(entries, 180, False)
    assert [e.candidate.key for e in out] == ["distinct", "common"]


def test_quote_preference_keeps_distinctive_terms_first() -> None:
    text = (
        "We deliver granite to every town in the region. "
        "Our granite is cut to size by our own team. "
        "We also supply marble for kitchens and halls."
    )
    plain = fit_sentences(text, {"granite", "marble"}, set(), limit=2)
    assert [t for _, t, _ in plain] == ["granite", "granite"]
    chosen = fit_sentences(text, {"granite", "marble"}, set(), limit=2, prefer={"marble"})
    assert [t for _, t, _ in chosen] == ["marble", "granite"]


def _site(n: int, sentence: str) -> dict[str, str]:
    return {f"https://www.firm{n}.com/": sentence}


async def test_distinctive_and_common_are_decided_per_run(monkeypatch: Any) -> None:
    common = "We deliver granite to every town in the region."
    rare = "We also supply marble for kitchens and halls."
    names = ["Alpha", "Bravo", "Cargo", "Delta"]
    sites = [f"https://www.{n.lower()}.com/" for n in names]
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: FakeSensor([[u] for u in sites]))
    pages = {
        sites[0]: f"{common} {rare}",
        sites[1]: common,
        sites[2]: common,
        sites[3]: common,
    }
    entries = []
    for i, n in enumerate(names):
        e = entry("awarded_contractor")
        c = e.candidate.model_copy(update={"key": f"k{i}", "name": f"{n} Ltd"})
        entries.append(e.model_copy(update={"candidate": c, "rank": i + 1}))
    spec = SPEC.model_copy(update={"offer_terms": ["granite", "marble"]})
    cfg = Settings(_env_file=None, radar_fit_quotes=1)
    out, _ = await company_fit(
        entries, spec, http=None, fetcher=FakeFetcher(pages), as_of=NOW, settings=cfg
    )
    by_key = {e.candidate.key: e for e in out}
    # granite is named by every company (common); marble by one of four (distinctive)
    assert by_key["k0"].fit_distinctive is True
    assert by_key["k0"].company_fit[0].term == "marble"  # kept before the earlier granite quote
    assert all(by_key[k].fit_distinctive is False for k in ("k1", "k2", "k3"))

    legacy = cfg.model_copy(update={"radar_fit_distinctive": False})
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: FakeSensor([[u] for u in sites]))
    old, _ = await company_fit(
        entries, spec, http=None, fetcher=FakeFetcher(pages), as_of=NOW, settings=legacy
    )
    assert old[0].company_fit[0].term == "granite"  # page order, as before
    assert all(e.fit_distinctive is False for e in old)
