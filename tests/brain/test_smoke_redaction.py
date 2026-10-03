"""The smoke script's redaction helper, offline against synthetic payloads (T2.5a).

Fixtures go to a public repository. Three places a credential hides are covered here: a header,
a URL, and a nested body field - plus the fail-closed rule for a key shape we do not recognise.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "scripts" / "smoke_llm.py"

KEY = "-".join(["nvapi", "SYNTHETIC", "0123456789abcdef"])
DB = "postgresql://user:hunter2@db.example.com/northvaine"


@pytest.fixture(scope="module")
def smoke():
    spec = importlib.util.spec_from_file_location("smoke_llm_under_test", SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_key_in_a_header_is_removed(smoke) -> None:
    out = smoke.redact({"headers": {"Authorization": f"Bearer {KEY}"}}, (KEY,))
    assert KEY not in str(out)
    assert out["headers"]["Authorization"] == smoke.REDACTED


def test_a_key_in_a_url_is_removed(smoke) -> None:
    payload = {"url": f"https://api.example.com/v1/models?api_key={KEY}"}
    out = smoke.redact(payload, (KEY,))
    assert KEY not in str(out)


def test_a_key_in_a_nested_body_field_is_removed(smoke) -> None:
    payload = {"body": {"auth": {"credentials": {"value": KEY}}, "keep": "visible"}}
    out = smoke.redact(payload, (KEY,))
    assert KEY not in str(out)
    assert out["body"]["keep"] == "visible"


def test_a_database_url_is_removed(smoke) -> None:
    out = smoke.redact({"note": f"connected to {DB}"}, (KEY, DB))
    assert "hunter2" not in str(out)


def test_an_unknown_key_shape_is_still_caught(smoke) -> None:
    """Fail closed: a credential format we were never told about must not survive."""
    stranger = "sk-" + "z" * 40
    out = smoke.redact({"body": {"token_value": stranger}}, ())  # not in known secrets
    assert stranger not in str(out)


def test_credential_named_keys_are_redacted_even_without_a_known_secret(smoke) -> None:
    out = smoke.redact({"account_id": "acct_12345", "api_key": "whatever"}, ())
    assert out["account_id"] == smoke.REDACTED
    assert out["api_key"] == smoke.REDACTED


def test_ordinary_content_survives(smoke) -> None:
    """Redaction that eats the payload would make the fixtures useless."""
    payload = {
        "model": "nvidia/Nemotron-3_5-Lightning",
        "messages": [{"role": "user", "content": "Bonjour tout le monde"}],
        "usage": {"prompt_tokens": 22, "completion_tokens": 14},
    }
    out = smoke.redact(payload, (KEY,))
    assert out == payload


def test_lists_and_scalars_are_walked(smoke) -> None:
    out = smoke.redact({"items": [{"api_key": KEY}, "plain", 7, None]}, (KEY,))
    assert out["items"][0]["api_key"] == smoke.REDACTED
    assert out["items"][1:] == ["plain", 7, None]


def test_the_fixtures_directory_holds_only_the_readme() -> None:
    """T2.5a commits no recorded fixture: the orchestrator records, T2.5b replays."""
    present = sorted(p.name for p in (ROOT / "tests" / "fixtures" / "llm").glob("*"))
    assert present == ["README.md"], present


def test_the_smoke_script_imports_no_http_client_or_llm_sdk() -> None:
    """CLAUDE.md #8: everything, including the free listing, goes through brain/llm.py."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from check_invariants import LLM_SDKS, NETWORK_LIBS, imported_modules
    finally:
        sys.path.pop(0)

    modules = imported_modules(SMOKE)
    assert not (modules & LLM_SDKS), modules & LLM_SDKS
    assert not (modules & NETWORK_LIBS), modules & NETWORK_LIBS
