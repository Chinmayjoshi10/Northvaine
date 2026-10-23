"""Hosting scripts: demo spec, GitHub secrets, Hugging Face Space. No network, fake secrets."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"nv_{name}", REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SPEC = {
    "id": "private_client",
    "name": "Secretco Ltd",
    "offer": "natural stone slabs",
    "existing_customers": ["Somebody Ltd"],
    "sensors": {"tavily": [{"query": "stone importers"}]},
}


def test_make_demo_spec_refuses_forbidden_word_and_names_the_path(tmp_path, capsys):
    module = _load("make_demo_spec")
    source = tmp_path / "src.json"
    spec = {**SPEC, "offer": "slabs from Acmequarry"}
    source.write_text(json.dumps(spec), encoding="utf-8")
    out = tmp_path / "out.json"
    code = module.main(["--source", str(source), "--out", str(out), "--forbid", "ACMEQUARRY"])
    assert code == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "$.offer" in err
    assert "Acmequarry" not in err


def test_make_demo_spec_finds_words_in_nested_lists(tmp_path, capsys):
    module = _load("make_demo_spec")
    source = tmp_path / "src.json"
    spec = {**SPEC, "sensors": {"tavily": [{"query": "acmequarry buyers"}]}}
    source.write_text(json.dumps(spec), encoding="utf-8")
    code = module.main(
        ["--source", str(source), "--out", str(tmp_path / "o.json"), "--forbid", "acmequarry"]
    )
    assert code == 1
    assert "$.sensors.tavily[0].query" in capsys.readouterr().err


def test_make_demo_spec_clean_writes_demo_fields(tmp_path):
    module = _load("make_demo_spec")
    source = tmp_path / "src.json"
    source.write_text(json.dumps(SPEC), encoding="utf-8")
    out = tmp_path / "nested" / "demo.json"
    assert module.main(["--source", str(source), "--out", str(out), "--forbid", "nomatch"]) == 0
    demo = json.loads(out.read_text(encoding="utf-8"))
    assert demo["id"] == "stone_exporter_demo"
    assert demo["name"] == "An Indian natural-stone exporter"
    assert demo["existing_customers"] == []
    assert demo["offer"] == SPEC["offer"]


def test_gh_secrets_temp_file_has_only_listed_names_and_is_deleted(tmp_path, capsys, monkeypatch):
    module = _load("gh_secrets")
    env = tmp_path / ".env"
    env.write_text(
        "NEBIUS_API_KEY=fakevalue-one\n"
        "DATABASE_URL=postgresql://prod-db\n"
        "DEMO_DATABASE_URL=postgresql://demo-db\n"
        "UNRELATED_KEY=do-not-copy\n"
        "HF_TOKEN='fakevalue-three'\n"
        "MODEL_FAST=some/model # comment\n"
        "broken line without equals\n",
        encoding="utf-8",
    )
    seen: dict[str, Any] = {}

    def fake_run(cmd, **kwargs):
        path = Path(cmd[cmd.index("--env-file") + 1])
        seen["cmd"] = cmd
        seen["path"] = path
        seen["text"] = path.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.main(["--repo", "o/r"], env_path=env) == 0
    names = {line.split("=", 1)[0] for line in seen["text"].splitlines()}
    assert names == {"DATABASE_URL", "NEBIUS_API_KEY", "HF_TOKEN", "MODEL_FAST"}
    assert "DATABASE_URL=postgresql://demo-db\n" in seen["text"]  # never production
    assert "prod-db" not in seen["text"]
    assert "MODEL_FAST=some/model\n" in seen["text"]
    assert not seen["path"].exists()
    assert seen["cmd"][-2:] == ["--repo", "o/r"]
    out = capsys.readouterr().out
    assert "set: NEBIUS_API_KEY" in out
    for value in ("fakevalue-one", "fakevalue-three", "some/model", "do-not-copy", "demo-db"):
        assert value not in out


def test_gh_secrets_deletes_temp_file_even_when_gh_fails(tmp_path, monkeypatch):
    module = _load("gh_secrets")
    env = tmp_path / ".env"
    env.write_text("NEBIUS_API_KEY=abc\nDEMO_DATABASE_URL=postgresql://demo\n", encoding="utf-8")
    seen: dict[str, Path] = {}

    def fake_run(cmd, **kwargs):
        seen["path"] = Path(cmd[cmd.index("--env-file") + 1])
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.main(["--repo", "o/r"], env_path=env) == 1
    assert not seen["path"].exists()


def test_gh_secrets_without_gh_prints_install_hint(tmp_path, capsys, monkeypatch):
    module = _load("gh_secrets")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    assert module.main(["--repo", "o/r"], env_path=tmp_path / ".env") == 1
    assert "install" in capsys.readouterr().out.lower()


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def record(**kwargs: Any) -> None:
            self.calls.append((name, kwargs))

        return record


def test_hf_secrets_pass_values_but_never_print_them(capsys):
    module = _load("hf_space")
    env = {
        "NEBIUS_API_KEY": "fakevalue-one",
        "TAVILY_API_KEY": "fakevalue-two",
        "DAILY_BUDGET_USD": "5",
    }
    api = FakeApi()
    assert module.main(["secrets", "--space", "u/n"], api=api, env=env) == 0
    sent = {kw["key"]: kw["value"] for name, kw in api.calls if name == "add_space_secret"}
    assert sent == {"NEBIUS_API_KEY": "fakevalue-one", "TAVILY_API_KEY": "fakevalue-two"}
    variables = {kw["key"]: kw["value"] for name, kw in api.calls if name == "add_space_variable"}
    assert variables == {"DAILY_BUDGET_USD": "2"}
    out = capsys.readouterr().out
    assert "set: NEBIUS_API_KEY" in out
    assert "fakevalue-one" not in out and "fakevalue-two" not in out


def test_hf_daily_budget_keeps_a_lower_value():
    module = _load("hf_space")
    assert module.daily_budget({"DAILY_BUDGET_USD": "0.5"}) == "0.5"
    assert module.daily_budget({"DAILY_BUDGET_USD": "junk"}) == "2"
    assert module.daily_budget({}) == "2"


def test_hf_init_creates_docker_space_and_fills_owner():
    module = _load("hf_space")
    api = FakeApi()
    assert module.main(["init", "--space", "u/n", "--owner", "MyOrg"], api=api, env={}) == 0
    create = next(kw for name, kw in api.calls if name == "create_repo")
    assert create["space_sdk"] == "docker" and create["repo_type"] == "space"
    uploads = {
        kw["path_in_repo"]: kw["path_or_fileobj"] for n, kw in api.calls if n == "upload_file"
    }
    assert b"FROM ghcr.io/myorg/northvaine:latest" in uploads["Dockerfile"]
    assert b"sdk: docker" in uploads["README.md"]


def test_hf_restart_is_a_factory_reboot():
    module = _load("hf_space")
    api = FakeApi()
    assert module.main(["restart", "--space", "u/n"], api=api, env={}) == 0
    assert api.calls == [("restart_space", {"repo_id": "u/n", "factory_reboot": True})]


def test_hf_requires_token_without_api(monkeypatch):
    module = _load("hf_space")
    with pytest.raises(SystemExit):
        module.main(["restart", "--space", "u/n"], env={})


def test_gh_secrets_refuses_without_a_demo_database(tmp_path, capsys, monkeypatch):
    module = _load("gh_secrets")
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://prod-db\nNEBIUS_API_KEY=abc\n", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("gh must not run"))
    assert module.main(["--repo", "o/r"], env_path=env) == 1
    assert "prod-db" not in capsys.readouterr().out


def test_hf_load_env_puts_the_demo_database_in_place_of_production(tmp_path):
    module = _load("hf_space")
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://prod\nDEMO_DATABASE_URL=postgresql://demo\n", "utf-8")
    assert module.load_env(env)["DATABASE_URL"] == "postgresql://demo"
