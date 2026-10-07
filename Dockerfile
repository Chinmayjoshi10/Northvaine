# Northvaine API image. No secrets are baked in: every setting arrives as an environment
# variable at run time (see .env.example for the names and docs/DEPLOY.md).
#
# Build:  docker build -t northvaine .
# Run:    docker run --rm -p 8000:8000 --env-file .env northvaine
#
# The app module is northvaine.api.main:app (northvaine/api/main.py). The nightly job uses
# the same image with a different command (see docs/DEPLOY.md).

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
# Recordings, so the offline radar run works inside the image.
COPY tests/fixtures ./tests/fixtures
RUN uv sync --frozen --no-dev

# Non-root user.
RUN useradd --create-home --uid 10001 northvaine \
    && chown -R northvaine:northvaine /app
USER northvaine

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8000
EXPOSE 8000

# /health is served by northvaine/api/main.py
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=4)" || exit 1

CMD ["sh", "-c", "exec uvicorn northvaine.api.main:app --host 0.0.0.0 --port ${PORT}"]
