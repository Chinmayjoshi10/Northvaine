# pytest-asyncio and pydantic-settings

Date checked: 2026-10-02. Researcher notes; facts come from official docs and PyPI unless marked.

## Summary

- **pytest-asyncio**: latest is **1.4.0** (2026-05-26), Python >=3.10, pytest >=8.4.0. The old
  `event_loop` fixture was removed in 1.0.0. Loop sharing is now done with `loop_scope=` on
  `@pytest_asyncio.fixture` and `@pytest.mark.asyncio`, or with the ini defaults
  `asyncio_default_fixture_loop_scope` and `asyncio_default_test_loop_scope`.
- To share one async DB engine across tests, the engine fixture **and the tests that use it**
  must run in the same event loop. Recommended setup: set both loop scopes to `session` in config.
  The fallback is `NullPool`, or a per-test engine.
- **pydantic-settings**: latest is **2.15.0** (2026-08-07), Python >=3.10, pydantic >=2.7.0,
  python-dotenv >=0.21.0. `extra` defaults to `forbid`, and that also applies to `.env` entries.
  Use `extra='ignore'` if the `.env` file holds keys the model doesn't declare.
  `case_sensitive` has no effect on real env vars on Windows.

## Facts

| # | Fact | Source | Confidence |
|---|---|---|---|
| 1 | pytest-asyncio latest = 1.4.0, released 2026-05-26; requires Python >=3.10 | https://pypi.org/project/pytest-asyncio/ | confirmed |
| 2 | 1.4.0: minimum pytest raised to 8.4.0; overriding the `event_loop_policy` fixture is deprecated in favour of the new `pytest_asyncio_loop_factories` hook; the warning text for an unset `asyncio_default_fixture_loop_scope` was improved | https://raw.githubusercontent.com/pytest-dev/pytest-asyncio/main/docs/reference/changelog.rst | confirmed |
| 3 | 1.0.0 (2025-05-26) removed the deprecated `event_loop` fixture. Scoped loops are created once. `loop_scope` no longer needs a Collector at that level | same changelog | confirmed |
| 4 | 1.1.0: tasks are cancelled when the `loop_scope` ends | same changelog | confirmed |
| 5 | 1.3.0: Python 3.9 support dropped; pytest 9 compatible | same changelog | confirmed |
| 6 | `asyncio_mode` defaults to **strict** when unset | https://pytest-asyncio.readthedocs.io/en/latest/reference/configuration.html | confirmed |
| 7 | **strict**: only runs tests that have the `asyncio` marker, and only handles async fixtures decorated with `@pytest_asyncio.fixture` (lets several async libraries coexist) | https://pytest-asyncio.readthedocs.io/en/latest/concepts.html | confirmed |
| 8 | **auto**: adds the `asyncio` marker to every async test and takes ownership of all async fixtures, whether they use `@pytest.fixture` or `@pytest_asyncio.fixture`. Meant for asyncio-only projects | concepts page (above) | confirmed |
| 9 | `asyncio_default_fixture_loop_scope`: default event-loop scope of async fixtures. When unset it falls back to the *fixture's own scope*, and future versions will default to `function`. Values: function, class, module, package, session. Leaving it unset gives a deprecation warning | configuration page (above); changelog #1298 | confirmed (exact warning class inferred: PytestDeprecationWarning) |
| 10 | `asyncio_default_test_loop_scope`: default loop scope of async tests; defaults to `function` when unset; same allowed values | configuration page (above) | confirmed |
| 11 | Loop scope (which loop) is separate from fixture caching scope (`scope=`). The loop scope is set with `@pytest_asyncio.fixture(loop_scope=...)` and `@pytest.mark.asyncio(loop_scope=...)` | https://raw.githubusercontent.com/pytest-dev/pytest-asyncio/main/docs/how-to-guides/change_fixture_loop_example.py | confirmed |
| 12 | Neighbouring tests should use the same loop scope (recommended by docs) | concepts page | confirmed |
| 13 | SQLAlchemy: don't share an `AsyncEngine` with the default pool across event loops. Doing so can raise `RuntimeError: ... got Future attached to a different loop`. Either call `await engine.dispose()` before using it in another loop, or use `poolclass=NullPool` | https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html ("Using multiple asyncio event loops") | confirmed |
| 14 | pydantic-settings latest = 2.15.0, released 2026-08-07; Python >=3.10; requires pydantic>=2.7.0, python-dotenv>=0.21.0, typing-inspection>=0.4.0 | https://pypi.org/pypi/pydantic-settings/json | confirmed |
| 15 | `SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')` loads a dotenv file. A tuple of files is allowed, and later files override earlier ones. Override per instance with `Settings(_env_file=...)` | https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ | confirmed |
| 16 | Real environment variables always take priority over values from the dotenv file | same page | confirmed |
| 17 | Default `extra='forbid'` applies to dotenv: a `.env` entry with no matching field raises `ValidationError`. Use `extra='ignore'` to tolerate it (pydantic 1.x behaviour). With `env_prefix` set, an unprefixed dotenv entry that matches a field name is silently skipped | same page | confirmed |
| 18 | `env_ignore_empty=True`: empty env vars are ignored and the field default is used. The default (False) parses empty strings | same page | confirmed |
| 19 | Env names are case-insensitive by default; `case_sensitive=True` enables exact matching | same page | confirmed |
| 20 | **Windows**: env var names exposed via `os` are case-insensitive and upper-cased, so `case_sensitive` has no effect for real env vars on Windows. Dotenv files keep their case, so case-sensitive matching still works for `.env` on Windows | same page | confirmed |
| 21 | `env_prefix='my_prefix_'` applies to env vars, dotenv, and secrets | same page | confirmed |
| 22 | Overall source priority (highest first): CLI (if enabled) > init kwargs > env vars > dotenv > secrets dir > field defaults. Customise with `settings_customise_sources` | same page (fact 16 confirmed; full order from prior knowledge of the docs) | inferred |
| 23 | `SecretStr`: `repr` shows `SecretStr('**********')` (`SecretStr('')` when empty); `print(model)` shows `password=SecretStr('**********')`; `model_dump()` keeps the masked `SecretStr` object; `model_dump_json()` writes `"**********"`; `.get_secret_value()` returns the real string | https://pydantic.dev/docs/validation/latest/api/pydantic/types/ | confirmed |
| 24 | To reveal a secret in JSON, use `@field_serializer('field', when_used='json')` that returns `v.get_secret_value()` | same page | confirmed |
| 25 | `str(SecretStr('x'))` returns `'**********'` | pydantic types page (behaviour); not quoted verbatim | inferred |

## Examples (from docs)

pytest-asyncio, module-scoped loop shared by fixture and test (verbatim from the docs example):

```python
import asyncio

import pytest

import pytest_asyncio


@pytest_asyncio.fixture(loop_scope="module")
async def current_loop():
    return asyncio.get_running_loop()


@pytest.mark.asyncio(loop_scope="module")
async def test_runs_in_module_loop(current_loop):
    assert current_loop is asyncio.get_running_loop()
```

Config for one session-wide loop (option names from the configuration reference; shown in
pyproject form as in the "change default test loop" how-to):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
```

Sharing one async engine with no "attached to a different loop" error. This pattern is put
together from facts 9-13 and is not copied from one doc page:

```python
# conftest.py  (auto mode; both loop scopes = session in config)
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    await eng.dispose()
```

Rules:
- The fixture's `loop_scope` must be the same as, or wider than, the loop scope of every
  test that uses it. Simplest: both config defaults = `session`.
- If some tests have to stay function-loop, give them their own engine, or build the shared
  engine with `poolclass=NullPool` (SQLAlchemy docs):

```python
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

engine = create_async_engine(
    "postgresql+asyncpg://user:pass@host/dbname",
    poolclass=NullPool,
)
```

pydantic-settings:

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )
    api_key: SecretStr
```

SecretStr (verbatim from docs):

```python
from pydantic import BaseModel, SecretStr

class User(BaseModel):
    username: str
    password: SecretStr

user = User(username='scolvin', password='password1')
print(user)
#> username='scolvin' password=SecretStr('**********')
print(user.password.get_secret_value())
#> password1
```

## Limits / gotchas

- In auto mode, pytest-asyncio owns *every* async fixture. Don't mix it with anyio/trio plugins
  that also want to own async fixtures (use strict mode if you need both).
- Leaving `asyncio_default_fixture_loop_scope` unset produces a warning, and its default
  will change to `function`. Always set it explicitly.
- Tasks still running when a loop scope ends get cancelled (1.1.0+). Background tasks started
  in fixtures must be awaited or cleaned up in teardown.
- Don't override the `event_loop_policy` fixture (deprecated in 1.4.0). Use the
  `pytest_asyncio_loop_factories` hook to get a custom loop (e.g. uvloop).
- On Windows, `case_sensitive=True` won't tell `API_KEY` and `api_key` apart in real env vars.
  Don't rely on case to separate settings.
- With `extra='forbid'` (default), any unknown key in `.env` stops startup. Shared `.env`
  files (e.g. the frontend's vars) need `extra='ignore'`.
- Tests: a `.env` on disk leaks into the test run. In tests, pass `_env_file=None` or build
  `Settings(...)` with explicit kwargs. Env vars still override, so use `monkeypatch.setenv`/`delenv`.
- `model_dump()` doesn't reveal secrets, but `get_secret_value()` does. Never log its result.

## Open questions

- The exact warning class and text for an unset `asyncio_default_fixture_loop_scope` in 1.4.0
  are not quoted here. Run this to confirm:
  `uv run pytest -W error::pytest.PytestDeprecationWarning -q` with the option unset.
- The full source priority order (fact 22) is inferred. To confirm, read the "Field value
  priority" section at https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/
- Installed versions in this repo: run `uv pip show pytest-asyncio pydantic-settings`.
