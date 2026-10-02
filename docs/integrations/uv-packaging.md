# uv packaging (uv 0.11)

Date checked: 2026-10-02. Researcher: factory researcher role.
Local toolchain on the founder machine: `uv 0.11.32 (2026-07-23, x86_64-pc-windows-msvc)`, system
Python 3.11.4 (also 3.10.4). Note: the live uv docs already describe uv 0.12 (they show
`uv_build>=0.12.22,<0.13`), so for this repo everything below is pinned to the **installed 0.11**
line. Facts marked "verified locally" were reproduced in a throwaway project in the session scratchpad, not in
this repo.

## Summary

- The current `pyproject.toml` backend `setuptools.backends._legacy:_Backend` is **invalid**. No
  module `setuptools.backends` exists (checked against setuptools 84.0.0), and `uv build` / `uv run`
  fail with `ModuleNotFoundError: No module named 'setuptools.backends'`. Replace it.
- All three of these work for a flat (no `src/`) `northvaine/` package. Recommended:
  **`uv_build`**, because it is uv's native backend, `uv init` defaults to it, and it builds in-process
  with no extra build env. You need `module-root = ""` for the flat layout.
  `setuptools.build_meta` and `hatchling.build` also work.
- PEP 735 `[dependency-groups]` is supported. The `dev` group is installed **by default** by
  `uv sync` and `uv run`. `[project.optional-dependencies] dev` (what the repo has now) is **not**
  installed by default. So the gate's `uv run pytest` / `uv run ruff` will not find those tools unless
  they move to `[dependency-groups] dev`.
- Pin 3.12 with `requires-python = ">=3.12,<3.13"` plus a `.python-version` containing `3.12`.
  `uv` downloads a managed CPython 3.12 automatically when only 3.11 is on the system.
- `uv.lock` is universal and cross-platform. One lock created on Windows contains Linux-only
  packages (e.g. `uvloop`) with markers, plus manylinux wheels. The same lock serves Nebius Linux.
- A missing `readme` file breaks `uv_build` and `hatchling`. `setuptools` only warns. Omitting the
  `readme` field is fine for all three. The repo currently has **no `README.md`** at the root.

## Facts

| # | Fact | Source | Confidence |
|---|---|---|---|
| 1 | uv build backend: `requires = ["uv_build>=X,<Y"]`, `build-backend = "uv_build"`. The docs recommend an upper bound. | https://docs.astral.sh/uv/concepts/build-backend/ | confirmed in docs |
| 2 | With uv 0.11.32, `uv init --lib` / `--package` writes `requires = ["uv_build>=0.11.32,<0.12.0"]`, `build-backend = "uv_build"`. | local `uv init` output | verified locally |
| 3 | `uv_build` expects `src/<name>/` by default. For a flat layout set `[tool.uv.build-backend] module-name = "northvaine"` and `module-root = ""`. | https://docs.astral.sh/uv/concepts/build-backend/ | confirmed in docs + verified locally (wheel contains `northvaine/__init__.py`) |
| 4 | `setuptools.build_meta` is the documented setuptools backend string. `setuptools.build_meta:__legacy__` is the fallback uv uses when no `[build-system]` is declared. | https://setuptools.pypa.io/en/latest/build_meta.html ; https://docs.astral.sh/uv/concepts/projects/config/ | confirmed in docs |
| 5 | `setuptools.backends._legacy:_Backend` is invalid: `import setuptools.backends` raises `ModuleNotFoundError` on setuptools 84.0.0. `uv build` fails with "Call to `setuptools.backends._legacy:_Backend.build_sdist` failed", and `uv run` fails the same way, because it builds the project. | local test | verified locally (definitely invalid for current setuptools; no setuptools release with that module is known) |
| 6 | `hatchling.build` (requires `["hatchling"]`) auto-detects flat `northvaine/` when it matches the project name. | local `uv build` | verified locally |
| 7 | `setuptools.build_meta` with `[tool.setuptools.packages.find] include = ["northvaine*"]` builds sdist + wheel. | local `uv build` | verified locally |
| 8 | uv uses PEP 735 `[dependency-groups]`. The `dev` group is special-cased with `--dev`, `--only-dev` and `--no-dev`. "By default, uv includes the `dev` dependency group in the environment (e.g., during `uv run` or `uv sync`)." You can change this with `tool.uv.default-groups`. | https://docs.astral.sh/uv/concepts/projects/dependencies/ | confirmed in docs + verified locally (`uv run` imported dev-group pkg; `uv sync --no-dev` uninstalled it) |
| 9 | Extras in `[project.optional-dependencies]` are not installed by `uv run` / `uv sync` unless you pass `--extra <name>` or `--all-extras`. | local test (`import six` failed without `--extra`, succeeded with it) | verified locally |
| 10 | uv reads `.python-version` from the working dir and its parents. `uv python pin 3.12` writes it. uv also respects `requires-python` and uses the first compatible interpreter. | https://docs.astral.sh/uv/concepts/python-versions/ | confirmed in docs |
| 11 | `python-downloads` defaults to `automatic`. `python-preference` defaults to `managed`, but an installed system Python is still preferred over downloading. | https://docs.astral.sh/uv/concepts/python-versions/ | confirmed in docs |
| 12 | On this machine (system 3.11 only), `uv python pin 3.12` downloaded `cpython-3.12.13-windows-x86_64-none`. `uv run` then created a 3.12.13 venv. The lock records `requires-python = "==3.12.*"` for `>=3.12,<3.13`. | local test | verified locally |
| 13 | "uv's lockfile (`uv.lock`) is created with a universal resolution and is portable across platforms." `tool.uv.environments` narrows the platforms; `tool.uv.required-environments` forces wheels to exist for given platforms. | https://docs.astral.sh/uv/concepts/resolution/ | confirmed in docs |
| 14 | A lock made on Windows for `uvicorn[standard]` contains `uvloop` with marker `sys_platform != 'win32'` (Linux-only), plus `manylinux` x86_64/aarch64 wheels. | local `uv lock` | verified locally |
| 15 | With `readme = "README.md"` and no file: `uv_build` fails (`failed to open file ... README.md`), `hatchling` fails (`OSError: Readme file does not exist: README.md`), and `setuptools.build_meta` succeeds with `SetuptoolsWarning: File ... README.md cannot be found`. | local `uv build` | verified locally |
| 16 | `readme` is optional in PEP 621 `[project]`. Omitting it builds cleanly with all three backends. | local `uv build` (projects without `readme`) | verified locally |
| 17 | If `[build-system]` is defined, uv builds and installs the project into the env. `tool.uv.package = false` turns this off. | https://docs.astral.sh/uv/concepts/projects/config/ | confirmed in docs |

## Examples

Recommended `pyproject.toml` fragment for this repo (flat `northvaine/`, Python 3.12). It is shown as
data for the contracts ticket that owns `pyproject.toml`; the researcher does not edit that file.

```toml
[project]
name = "northvaine"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
# readme omitted until a README.md exists (or add the file and restore: readme = "README.md")
dependencies = [ ... ]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
]

[build-system]
requires = ["uv_build>=0.11.32,<0.12.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "northvaine"
module-root = ""
```

The `[tool.setuptools.packages.find]` table goes away with `uv_build`. Also bump
`[tool.ruff] target-version = "py312"` and `[tool.mypy] python_version = "3.12"` to match.

Alternative (setuptools, valid):

```toml
[build-system]
requires = ["setuptools>=75.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["northvaine*"]
```

Python pin (repo root):

```
$ uv python pin 3.12        # writes .python-version containing "3.12"; downloads 3.12 if needed
$ uv python install 3.12    # optional explicit install
$ uv sync                   # creates .venv on 3.12, installs project + dev group
$ uv run python -c "import sys; print(sys.version)"   # 3.12.x
```

Docs on the dev group (quoted): "By default, uv includes the `dev` dependency group in the
environment (e.g., during `uv run` or `uv sync`)." For a production install on Nebius, use
`uv sync --frozen --no-dev`.

Limiting the lock to the two platforms we deploy on (optional):

```toml
[tool.uv]
environments = ["sys_platform == 'win32'", "sys_platform == 'linux'"]
```

## Limits and caveats

- `uv_build` upper bound `<0.12.0` ties the build to the 0.11 line. If the founder upgrades uv to
  0.12, bump the bound to `>=0.12,<0.13`. An older `uv_build` still builds, but uv only uses its
  in-process fast path when the version range matches the running uv.
- `uv_build` supports pure-Python packages only. That is fine for Northvaine.
- Pinning `requires-python` to `<3.13` makes the lock 3.12-only. A wider range (`>=3.12`) also works.
  `.python-version` then picks 3.12 locally.
- Managed Python downloads need network on first run. `UV_PYTHON_DOWNLOADS=never` disables them.
- Linux deploy: wheels in the lock must exist for the Nebius CPU arch (x86_64 vs aarch64). Use
  `required-environments` if a dep risks having no wheel there.

## Open questions

- Nebius deploy target arch (x86_64 or aarch64) and glibc version. Not confirmed. The founder can
  run `uname -m; ldd --version` on the VM.
- Whether to add a root `README.md` (needed if `readme` is kept with `uv_build`).
- The uv version to standardise on for the team/CI (0.11.32 locally; docs are already on 0.12).
  Check with `uv --version` on each machine.
