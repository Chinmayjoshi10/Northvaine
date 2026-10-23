# Northvaine API image. No secrets are baked in: every setting arrives as an environment
# variable at run time (see .env.example for the names and docs/DEPLOY.md).
#
# Build:  docker build -t northvaine .
# Run:    docker run --rm -p 8000:8000 --env-file .env northvaine
#
# The app module is northvaine.api.main:app (northvaine/api/main.py). The nightly job uses
# the same image with a different command (see docs/DEPLOY.md).

# Stage 1: build the frontend; the API serves frontend/dist when it exists.
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim

# uv from the official image, pinned to a minor version.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first (cached until pyproject.toml or uv.lock change).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code.
COPY northvaine ./northvaine
COPY migrations ./migrations
COPY alembic.ini schema.sql ./
COPY scripts ./scripts
# The public demo client spec (deploy/demo/README.md) and, when the nightly workflow supplies
# them, the baked radar reports (demo_reports/radar/<client>/<date>/run.json). The folder always
# exists in the repo (demo_reports/.keep), so a plain `docker build .` works without reports.
COPY deploy/demo ./deploy/demo
COPY demo_reports ./demo_reports
# Recordings, so the offline radar run works inside the image.
COPY tests/fixtures ./tests/fixtures
RUN uv sync --frozen --no-dev
COPY --from=frontend /frontend/dist ./frontend/dist

# Non-root user. The onboarding folder is world-writable because some hosts (Hugging Face
# Spaces) run the container under a different uid; its contents are ephemeral.
RUN useradd --create-home --uid 10001 northvaine \
    && mkdir -p /app/onboarding_clients \
    && chmod 777 /app/onboarding_clients \
    && chown -R northvaine:northvaine /app
USER northvaine

ENV PATH="/app/.venv/bin:$PATH" \
    RADAR_REPORTS_DIR=/app/demo_reports/radar \
    ONBOARDING_CLIENTS_DIR=/app/onboarding_clients \
    PORT=8000
EXPOSE 8000

# /health is served by northvaine/api/main.py
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=4)" || exit 1

CMD ["sh", "-c", "exec uvicorn northvaine.api.main:app --host 0.0.0.0 --port ${PORT}"]
