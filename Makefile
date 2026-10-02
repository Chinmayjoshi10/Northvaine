# Every target delegates to scripts/tasks.py, which also runs without make:
#   uv run python scripts/tasks.py <task>
.PHONY: setup dev test golden lint migrate db-check db-test gate nightly

setup: ; uv run python scripts/tasks.py setup
dev: ; uv run python scripts/tasks.py dev
test: ; uv run python scripts/tasks.py test
golden: ; uv run python scripts/tasks.py golden
lint: ; uv run python scripts/tasks.py lint
migrate: ; uv run python scripts/tasks.py migrate
db-check: ; uv run python scripts/tasks.py db-check
db-test: ; uv run python scripts/tasks.py db-test
gate: ; uv run python scripts/tasks.py gate
nightly: ; uv run python scripts/tasks.py nightly
