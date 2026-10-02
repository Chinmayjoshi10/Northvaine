.PHONY: dev test golden migrate nightly setup db-setup db-reset lint

# ── Setup ───────────────────────────────────────────────────────────
setup:
	py -3.11 -m venv .venv
	.venv\Scripts\pip install -e ".[dev]"
	@echo "✓ Virtual environment created. Activate with: .venv\Scripts\activate"

# ── Database ────────────────────────────────────────────────────────
db-setup:
	@echo "Creating Postgres user and database..."
	psql -U postgres -c "CREATE USER northvaine WITH PASSWORD 'northvaine';" 2>NUL || echo "User may already exist"
	psql -U postgres -c "CREATE DATABASE northvaine OWNER northvaine;" 2>NUL || echo "Database may already exist"
	psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE northvaine TO northvaine;"
	@echo "✓ Database ready"

db-reset:
	psql -U postgres -c "DROP DATABASE IF EXISTS northvaine;"
	psql -U postgres -c "CREATE DATABASE northvaine OWNER northvaine;"
	alembic upgrade head
	@echo "✓ Database reset"

migrate:
	alembic upgrade head

# ── Development ─────────────────────────────────────────────────────
dev:
	uvicorn northvaine.api.main:app --reload --port 8000

# ── Testing ─────────────────────────────────────────────────────────
test:
	pytest tests/ -x --ignore=tests/golden -m "not live"

golden:
	pytest tests/golden/ -v --tb=short

# ── Linting ─────────────────────────────────────────────────────────
lint:
	ruff check northvaine/ tests/
	ruff format --check northvaine/ tests/

# ── Jobs ────────────────────────────────────────────────────────────
nightly:
	python -m northvaine.jobs.nightly
