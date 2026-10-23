"""Northvaine FastAPI application."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from northvaine.api import accounts, feedback, onboarding, runs
from northvaine.core.settings import get_settings

_DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]  # Vite dev server

app = FastAPI(
    title="Northvaine",
    description="AI sales assistant for B2B businesses",
    version="0.1.0",
)



def add_cors(target: FastAPI, extra_origins: list[str]) -> None:
    """Dev server plus the configured origins (settings.cors_origins); GET and POST, no cookies."""
    target.add_middleware(
        CORSMiddleware,
        allow_origins=[*_DEV_ORIGINS, *extra_origins],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


add_cors(app, get_settings().cors_origins)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


app.include_router(runs.router)
app.include_router(feedback.router)
app.include_router(accounts.router)
app.include_router(onboarding.router)

# One-service deploy: serve the built frontend when it exists (npm --prefix frontend run build).
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
