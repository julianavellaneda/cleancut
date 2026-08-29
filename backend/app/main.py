"""
FastAPI application entry point.
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import root_env_path

# Load environment variables from the project root .env before importing anything
# that depends on them (OPENAI_API_KEY, CORS_ORIGINS, DATABASE_PATH). In Docker
# there is no repo root and no .env - the container supplies these directly.
_ROOT_ENV = root_env_path(__file__)
if _ROOT_ENV:
    load_dotenv(_ROOT_ENV)

from .database import init_db
from .network import exposure_warning
from .preflight import verify_environment
from .routes import jobs, violations, audio, admin
from .services.retention import start_retention_sweeper
from .services.worker import start_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Check the environment, then bring up the database, worker, and sweeper.

    Preflight runs first and raises, so a missing OPENAI_API_KEY or ffmpeg stops
    the server at boot with an actionable message instead of surfacing minutes
    later as a mysteriously failed job.

    The retention sweeper is a no-op unless RETENTION_HOURS is set.

    A non-loopback CLEANCUT_HOST is warned about but never refused: exposing the
    port is a supported choice, and the operator who made it should be reminded
    that the media routes carry no authentication.
    """
    verify_environment()
    warning = exposure_warning()
    if warning:
        print(warning)
    init_db()
    start_worker()
    start_retention_sweeper()
    yield


app = FastAPI(
    title="CleanCut API",
    description="Describe what to find in plain English, review it on a waveform, export a surgically edited file.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration — comma-separated origins via CORS_ORIGINS env var.
_cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(violations.router, prefix="/api/jobs", tags=["violations"])
app.include_router(audio.router, prefix="/api/jobs", tags=["audio"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/")
def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "CleanCut API is running"}
