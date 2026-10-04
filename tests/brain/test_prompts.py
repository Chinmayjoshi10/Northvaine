"""The prompt loader: `<name>.v<N>.md` versioning and strict, fencing render (D8, D9, T2.2)."""

from __future__ import annotations

import re

import pytest

from northvaine.brain.fencing import PREAMBLE, Untrusted
from northvaine.brain.prompts import PROMPT_DIR, Prompt, PromptError, load_prompt

SNIPPET = "Bonjour tout le monde"


def make(template: str, *, untrusted: tuple[str, ...] = ()) -> Prompt:
    return Prompt(
        name="t",
        version=1,
        template=template,
        untrusted_vars=frozenset(untrusted),
        tier="fast",
        description="d",
    )


def test_version_label_is_exactly_name_dot_v_number() -> None:
    assert make("x").version_label == "t.v1"
    assert load_prompt("smoke_ping").version_label == "smoke_ping.v1"


def test_load_prompt_takes_the_highest_version(tmp_path: object) -> None:
    versions = sorted(
        int(p.name.split(".v")[1].split(".md")[0]) for p in PROMPT_DIR.glob("smoke_ping.v*.md")
    )
    assert load_prompt("smoke_ping").version == max(versions)


def test_load_prompt_can_pin_a_version() -> None:
    assert load_prompt("smoke_ping", version=1).version == 1
    with pytest.raises(PromptError, match="no version 99"):
        load_prompt("smoke_ping", version=99)


def test_unknown_prompt_raises() -> None:
    with pytest.raises(PromptError, match="no prompt named"):
        load_prompt("there_is_no_such_prompt")


def test_render_refuses_a_missing_variable() -> None:
    with pytest.raises(PromptError, match="missing variables"):
        make("{a} and {b}").render(a="x")


def test_render_refuses_an_unexpected_variable() -> None:
    with pytest.raises(PromptError, match="unexpected variables"):
        make("{a}").render(a="x", b="y")


def test_render_refuses_a_plain_string_in_an_untrusted_slot() -> None:
    with pytest.raises(PromptError, match="declared untrusted"):
        make("{page}", untrusted=("page",)).render(page="raw text")


def test_render_refuses_untrusted_in_a_trusted_slot() -> None:
    with pytest.raises(PromptError, match="not declared untrusted"):
        make("{name}").render(name=Untrusted("x"))


def test_render_actually_fences_untrusted_values() -> None:
    """A type check that then interpolates raw text does not satisfy T2.2."""
    out = make("Before {page} After", untrusted=("page",)).render(page=Untrusted("SECRET BODY"))
    assert PREAMBLE in out
    # The delimiters wrap that variable's text only - not the whole prompt.
    begin = re.search(r"-----BEGIN PAGE DATA ([0-9a-f]+)-----", out)
    assert begin, out
    end = f"-----END PAGE DATA {begin.group(1)}-----"
    assert out.index("Before") < begin.start() < out.index("SECRET BODY")
    assert out.index("SECRET BODY") < out.index(end) < out.index("After")


def test_trusted_values_are_interpolated_verbatim() -> None:
    assert make("Hello {name}").render(name="world") == "Hello world"


def test_front_matter_must_agree_with_the_filename(tmp_path: object) -> None:
    text = (PROMPT_DIR / "smoke_ping.v1.md").read_text(encoding="utf-8")
    assert "name: smoke_ping" in text and "version: 1" in text


def test_the_shipped_prompt_loads_renders_and_declares_untrusted() -> None:
    prompt = load_prompt("smoke_ping")
    assert prompt.tier == "fast"
    assert "snippet" in prompt.untrusted_vars
    out = prompt.render(snippet=Untrusted(SNIPPET))
    assert SNIPPET in out and PREAMBLE in out


def test_every_shipped_prompt_loads_and_fences_untrusted_input() -> None:
    """Every prompt that ships must load, name a tier and declare its untrusted inputs."""
    names = sorted({p.name.split(".v")[0] for p in PROMPT_DIR.glob("*.v*.md")})
    assert "smoke_ping" in names
    for name in names:
        prompt = load_prompt(name)
        assert prompt.tier in {"fast", "mid", "deep"}, name
        assert prompt.untrusted_vars, f"{name} declares no untrusted inputs"


def test_loading_needs_no_settings_database_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DATABASE_URL", "NEBIUS_API_KEY", "DAILY_BUDGET_USD", "TOTAL_BUDGET_USD"):
        monkeypatch.delenv(key, raising=False)
    assert load_prompt("smoke_ping").render(snippet=Untrusted("x"))
