"""
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routes import jobs, violations, audio

app = FastAPI(
    title="Audio Compliance API",
    description="AI-powered audio compliance analysis for marketing guidelines",
    version="1.0.0",
)

# CORS configuration for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(violations.router, prefix="/api/jobs", tags=["violations"])
app.include_router(audio.router, prefix="/api/jobs", tags=["audio"])


@app.on_event("startup")
def startup_event():
    """Initialize database on startup."""
    init_db()


@app.get("/")
def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Audio Compliance API is running"}
