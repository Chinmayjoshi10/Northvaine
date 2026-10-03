"""brain/prompts/: the prompt loader, `<name>.v<N>.md` versioning (DECISIONS D8).

Prompts are files named `<name>.v<N>.md` with front matter, living in this directory.
`load_prompt(name)` takes the highest version; `Prompt.version_label` is what
`llm_calls.prompt_version` stores (`"<name>.v<N>"`), so a prompt change is attributable to the
results it produced (SPEC §12). T2.2 fills in the bodies, ships the loader's front-matter parsing
and the fencing of untrusted variables (DECISIONS D9); nothing here reads a file or makes a
network call at import time.
"""

from __future__ import annotations

from dataclasses import dataclass

from northvaine.brain.fencing import Untrusted


@dataclass(frozen=True)
class Prompt:
    """One loaded `<name>.v<N>.md` prompt: its name, version, template text and untrusted vars."""

    name: str
    version: int
    template: str
    untrusted_vars: frozenset[str]

    @property
    def version_label(self) -> str:
        """`"<name>.v<N>"`, stored in `llm_calls.prompt_version`."""
        raise NotImplementedError

    def render(self, **variables: str | Untrusted[str]) -> str:
        """Interpolate `variables` into `template`.

        Every name in `untrusted_vars` must be passed as `Untrusted[str]` — anything else is a
        type error (DECISIONS D9) — and is passed through `fence()` before interpolation.
        """
        raise NotImplementedError


def load_prompt(name: str) -> Prompt:
    """Load the highest-versioned `<name>.v<N>.md` file in this directory."""
    raise NotImplementedError
