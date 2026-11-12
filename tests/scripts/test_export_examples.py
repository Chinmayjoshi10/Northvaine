"""export_examples makes finished runs safe to publish. No network, no database."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "nv_examples", REPO / "scripts" / "export_examples.py"
)
assert spec and spec.loader
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)


def test_person_text_is_recognised() -> None:
    for text in (
        "Bruer Kershner, CEOFounded the firm in 2002",
        "It was founded in 2014 by James and Rebecca Lorimer",
        "Our managing director said the order was signed",
    ):
        assert ex.PERSON_RE.search(text), text
    for text in (
        "Global Food Trading changed owner on 2026-10-05.",
        "Brothers Office Furniture Ltd",
        "A wide range of rice cookers",
        "The official import record states importer: ACME LTD",
    ):
        assert not ex.PERSON_RE.search(text), text


def test_scrub_drops_personal_items_at_any_depth() -> None:
    entry = {
        "claims": [
            {"ref": "C1", "statement": "Imported goods in 2026-08"},
            {"ref": "C2", "statement": "The CEO said they will expand"},
        ],
        "open_questions": ["Does it buy from abroad?", "Ask the managing director"],
    }
    out = ex.scrub(entry)
    assert [c["ref"] for c in out["claims"]] == ["C1"]
    assert out["open_questions"] == ["Does it buy from abroad?"]


def test_anonymise_rewords_reasons_but_never_quotes_or_links() -> None:
    run = {
        "gate": {"reason": "A buyer of what Acme Corp sells."},
        "claims": [{"source_quote": "Acme Corp spares", "url": "https://acme.example/p"}],
    }
    out = ex.anonymise(run, ["acme corp", "acme"])
    assert out["gate"]["reason"] == "A buyer of what this client sells."
    assert out["claims"][0] == run["claims"][0]  # evidence stays exact (and is then dropped)


def test_check_published_finds_contacts_brands_and_people_but_not_dates() -> None:
    clean = {"log": [{"at": "2026-11-05T21:15:51.832715Z", "text": "Imports recorded"}]}
    assert ex.check_published({"a.json": clean}, ["acme"]) == []
    for bad in (
        {"text": "write to sales@example.com"},
        {"text": "call 0161 496 0000 today"},
        {"text": "Acme made this"},
        {"text": "the CEO decided"},
    ):
        assert ex.check_published({"a.json": bad}, ["acme"]), bad


def test_published_examples_are_still_safe() -> None:
    """The files committed under frontend/public/examples pass the same check, every time."""
    folder = REPO / "frontend" / "public" / "examples"
    config = json.loads(ex.CONFIG.read_text(encoding="utf-8"))["examples"]
    words = sorted({w.casefold() for c in config for w in c["forbid"]})
    files = {
        str(p.relative_to(folder)): json.loads(p.read_text(encoding="utf-8"))
        for p in folder.rglob("*.json")
    }
    assert "index.json" in files
    assert ex.check_published(files, words) == []
    index = files["index.json"]
    assert {c["slug"] for c in config} == {
        c["client"].removeprefix(ex.CLIENT_PREFIX) for c in index
    }
