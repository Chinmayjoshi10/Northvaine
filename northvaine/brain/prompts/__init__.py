"""brain/prompts/: the prompt loader, `<name>.v<N>.md` versioning (DECISIONS D8).

Prompts are files named `<name>.v<N>.md` with front matter, living in this directory.
`load_prompt(name)` takes the highest version; `Prompt.version_label` is what
`llm_calls.prompt_version` stores (`"<name>.v<N>"`), so a prompt change is attributable to the
results it produced (SPEC §12).

Untrusted variables (DECISIONS D9, CLAUDE.md #7): the front-matter `untrusted:` list is the
contract between a prompt author and `render()`. Every name in it must be passed as an
`Untrusted` value, and `render()` fences each one before interpolation. **A prompt that forgets
to list a variable is a review finding, not a runtime error** - that is exactly where the
remaining human judgement sits, so prompt diffs deserve a careful read.

Nothing here reads a file or opens a connection at import time; files are read per call, and the
directory is resolved through the package so an installed wheel works the same as a checkout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from northvaine.brain.fencing import Untrusted, fence

PROMPT_DIR = Path(__file__).resolve().parent
FILENAME = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d+)\.md$")
PLACEHOLDER = re.compile(r"\{(?P<name>[a-z0-9_]+)\}")
FRONT_MATTER = re.compile(r"\A---\n(?P<meta>.*?)\n---\n(?P<body>.*)\Z", re.S)


class PromptError(ValueError):
    """A prompt file is missing, malformed, or disagrees with its own filename."""


@dataclass(frozen=True)
class Prompt:
    """One loaded `<name>.v<N>.md` prompt: its name, version, template text and untrusted vars."""

    name: str
    version: int
    template: str
    untrusted_vars: frozenset[str]
    tier: str = "fast"
    description: str = ""

    @property
    def version_label(self) -> str:
        """`"<name>.v<N>"`, stored in `llm_calls.prompt_version`."""
        return f"{self.name}.v{self.version}"

    @property
    def variables(self) -> frozenset[str]:
        """Every `{placeholder}` the template interpolates."""
        return frozenset(m.group("name") for m in PLACEHOLDER.finditer(self.template))

    def render(self, **variables: str | Untrusted[str]) -> str:
        """Interpolate `variables` into `template`.

        Strict in three ways, each a test in tests/brain/test_prompts.py: a missing variable
        raises, an unexpected variable raises, and a variable declared `untrusted` raises unless
        its value is an `Untrusted` instance (DECISIONS D9). Untrusted values are passed through
        `fence()` before interpolation - a type check that then interpolated raw text would not
        satisfy CLAUDE.md #7.
        """
        expected = self.variables
        given = frozenset(variables)
        if missing := expected - given:
            raise PromptError(f"{self.version_label}: missing variables {sorted(missing)}")
        if unexpected := given - expected:
            raise PromptError(f"{self.version_label}: unexpected variables {sorted(unexpected)}")

        rendered: dict[str, str] = {}
        for key, value in variables.items():
            if key in self.untrusted_vars:
                if not isinstance(value, Untrusted):
                    raise PromptError(
                        f"{self.version_label}: {key!r} is declared untrusted, so it must be "
                        f"passed as Untrusted[str], not {type(value).__name__} (CLAUDE.md #7)."
                    )
                rendered[key] = fence(value, label=key)
            elif isinstance(value, Untrusted):
                raise PromptError(
                    f"{self.version_label}: {key!r} is not declared untrusted in the front "
                    "matter, so it must not be passed as Untrusted. Add it to `untrusted:`."
                )
            else:
                rendered[key] = value

        return self.template.format(**rendered)


def _parse_front_matter(text: str, path: Path) -> tuple[dict[str, str], list[str], str]:
    match = FRONT_MATTER.match(text)
    if not match:
        raise PromptError(f"{path.name}: missing `---` front matter")

    scalars: dict[str, str] = {}
    untrusted: list[str] = []
    key: str | None = None
    for raw in match.group("meta").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and line.lstrip().startswith("- "):
            if key != "untrusted":
                raise PromptError(f"{path.name}: list item under non-list key {key!r}")
            untrusted.append(line.lstrip()[2:].strip())
            continue
        if ":" not in line:
            raise PromptError(f"{path.name}: cannot parse front-matter line {line!r}")
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value:
            scalars[key] = value
    return scalars, untrusted, match.group("body")


def _load_file(path: Path) -> Prompt:
    name_match = FILENAME.match(path.name)
    if not name_match:
        raise PromptError(f"{path.name}: prompt files must be named <name>.v<N>.md")

    scalars, untrusted, body = _parse_front_matter(path.read_text(encoding="utf-8"), path)
    for required in ("name", "version", "description", "tier"):
        if required not in scalars:
            raise PromptError(f"{path.name}: front matter is missing {required!r}")

    if scalars["name"] != name_match.group("name"):
        raise PromptError(
            f"{path.name}: front-matter name {scalars['name']!r} disagrees with the filename"
        )
    if scalars["version"] != name_match.group("version"):
        raise PromptError(
            f"{path.name}: front-matter version {scalars['version']!r} disagrees with the filename"
        )

    prompt = Prompt(
        name=scalars["name"],
        version=int(scalars["version"]),
        template=body,
        untrusted_vars=frozenset(untrusted),
        tier=scalars["tier"],
        description=scalars["description"],
    )
    if unknown := prompt.untrusted_vars - prompt.variables:
        raise PromptError(
            f"{path.name}: `untrusted:` names {sorted(unknown)}, which the template never uses"
        )
    return prompt


def load_prompt(name: str, *, version: int | None = None) -> Prompt:
    """Load `<name>.v<N>.md`: the highest version, or the one pinned by `version`."""
    found: dict[int, Path] = {}
    for path in PROMPT_DIR.glob(f"{name}.v*.md"):
        match = FILENAME.match(path.name)
        if match and match.group("name") == name:
            found[int(match.group("version"))] = path
    if not found:
        raise PromptError(f"no prompt named {name!r} in {PROMPT_DIR}")

    if version is None:
        version = max(found)
    elif version not in found:
        raise PromptError(f"{name}: no version {version} (have {sorted(found)})")
    return _load_file(found[version])
