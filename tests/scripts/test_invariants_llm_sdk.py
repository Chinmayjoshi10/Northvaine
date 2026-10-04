"""The LLM SDK invariant against the real repo (T2.0): `openai`/`anthropic` only in brain/llm.py.

`tests/scripts/test_check_invariants.py` (T1.5) already proves `check_imports` flags a synthetic
file. This file proves the same rule against the *real* tree now that `brain/llm.py` actually
imports `openai` (T2.0): the real import is allowed, and importing the SDK from any other real
`northvaine/` file would be reported.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
LLM_PY = REPO / "northvaine" / "brain" / "llm.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "nv_check_invariants_llm_sdk", REPO / "scripts" / "check_invariants.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_brain_llm_imports_an_llm_sdk() -> None:
    """Sanity check: the real skeleton actually imports one of the covered SDKs."""
    mods = _load().imported_modules(LLM_PY)
    assert mods & {"openai", "anthropic"}


def test_real_brain_llm_import_is_not_a_violation() -> None:
    module = _load()
    problems = module.check_imports([LLM_PY])
    assert problems == []


def test_real_repo_has_zero_llm_sdk_violations() -> None:
    module = _load()
    py_files = sorted(module.APP.rglob("*.py"))
    problems = module.check_imports(py_files)
    assert problems == []


def test_copy_of_llm_py_elsewhere_in_northvaine_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    other = tmp_path / "northvaine" / "radar" / "not_llm.py"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(LLM_PY.read_text(encoding="utf-8"), encoding="utf-8")
    problems = module.check_imports([other])
    assert any("imports 'openai'" in p for p in problems)
    assert all("not_llm.py" in p for p in problems)


def test_replay_module_duck_types_the_sdk_and_passes_the_import_rule() -> None:
    """T4.0: brain/replay.py is not allowed to import the SDK, and does not."""
    module = _load()
    replay = REPO / "northvaine" / "brain" / "replay.py"
    assert not module.imported_modules(replay) & {"openai", "anthropic"}
    assert module.check_imports([replay]) == []


def test_real_repo_passes_the_ledger_rules() -> None:
    module = _load()
    py_files = sorted(module.APP.rglob("*.py"))
    terms = module.load_banned_terms()
    assert module.check_claims_sql(py_files) == []
    assert module.check_claim_row_imports(py_files) == []
    assert module.check_prompt_banned_terms(module.prompt_files(), terms) == []
    assert module.prompt_files(), "the real tree has prompt templates to scan"
