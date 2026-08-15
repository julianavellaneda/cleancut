"""
FastAPI application entry point.
"""

import os

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
from .routes import jobs, violations, audio, admin
from .services.worker import start_worker

app = FastAPI(
    title="CleanCut API",
    description="Describe what to find in plain English, review it on a waveform, export a surgically edited file.",
    version="1.0.0",
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


@app.on_event("startup")
def startup_event():
    """Initialize database and start background worker on startup."""
    init_db()
    start_worker()


@app.get("/")
def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Audio Compliance API is running"}
