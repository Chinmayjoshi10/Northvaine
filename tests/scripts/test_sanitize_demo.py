"""The public demo report never names the anonymised client's group, nor any contact."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "sanitize", ROOT / "scripts/sanitize_demo_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report() -> dict:
    return {
        "client_name": "An exporter",
        "entries": [
            {"rank": 1, "candidate": {"name": "Buyer One"}, "company_contact": {"email": "a@b.co"}},
            {"rank": 2, "candidate": {"name": "Acme Group Sister Ltd"}, "company_contact": None},
            {"rank": 3, "candidate": {"name": "Buyer Two"}, "company_contact": None},
        ],
        "rejected": [{"candidate": {"name": "ACME GROUP holdings"}}],
        "notes": [],
    }


def test_drops_own_group_removes_contacts_and_renumbers(tmp_path, monkeypatch, capsys):
    module = _module()
    run = tmp_path / "client" / "2026-10-23" / "run.json"
    run.parent.mkdir(parents=True)
    run.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setenv("DEMO_FORBID", "acme group")
    assert module.main([str(tmp_path)]) == 0
    out = json.loads(run.read_text(encoding="utf-8"))
    assert [e["candidate"]["name"] for e in out["entries"]] == ["Buyer One", "Buyer Two"]
    assert [e["rank"] for e in out["entries"]] == [1, 2]
    assert out["rejected"] == []
    assert all(e["company_contact"] is None for e in out["entries"])
    assert "acme" not in capsys.readouterr().out.casefold()  # the private words are never printed


def test_refuses_without_the_word_list_and_when_a_word_survives(tmp_path, monkeypatch):
    module = _module()
    run = tmp_path / "client" / "2026-10-23" / "run.json"
    run.parent.mkdir(parents=True)
    report = _report()
    report["notes"] = ["seen near Acme Group"]  # outside entries: cannot be dropped, so refuse
    run.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.delenv("DEMO_FORBID", raising=False)
    assert module.main([str(tmp_path)]) == 1
    monkeypatch.setenv("DEMO_FORBID", "acme group")
    before = run.read_text(encoding="utf-8")
    assert module.main([str(tmp_path)]) == 1
    assert run.read_text(encoding="utf-8") == before  # nothing written when unsafe


@pytest.mark.parametrize("value", ["", " ; "])
def test_empty_word_list_is_refused(tmp_path, monkeypatch, value):
    monkeypatch.setenv("DEMO_FORBID", value)
    assert _module().main([str(tmp_path)]) == 1
