"""
Job routes - upload, list, and status endpoints.
"""

import shutil
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Job
from ..schemas import JobResponse, JobListResponse, PresetResponse
from ..services.processor import PRESETS, is_valid_preset
from ..services.worker import enqueue_job

router = APIRouter()

# Directories
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"
EXPORT_DIR.mkdir(exist_ok=True)


@router.post("", response_model=JobResponse)
async def create_job(
    file: UploadFile = File(...),
    prompt: str | None = Form(None),
    media_type: str = Form("audio"),
    auto_fix: bool = Form(False),
    auto_scrub: bool = Form(False),
    preset: str | None = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload media file and start background processing.
    Returns immediately after saving the file; processing runs in a sequential background queue.
    Poll GET /api/jobs/{id} to track progress.
    """
    # Treat an empty preset field as "no preset" - HTML forms send "" for an
    # unselected <select>, and that should mean prompt mode, not a bad request.
    preset = preset or None
    if not is_valid_preset(preset):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{preset}'. Available: {', '.join(PRESETS)}"
        )

    # Validate file type
    allowed_extensions = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aif", ".aiff", ".mp4", ".mov"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )

    # Determine media type if not provided
    if media_type == "audio" and file_ext in {".mp4", ".mov"}:
        media_type = "video"

    # Create job record
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        filename=f"{job_id}{file_ext}",
        original_filename=file.filename,
        media_type=media_type,
        prompt=prompt,
        status="pending",
        auto_fix=auto_fix,
        auto_scrub=auto_scrub,
        preset=preset
    )
    db.add(job)
    db.commit()

    # Save uploaded file
    file_path = UPLOAD_DIR / f"{job_id}{file_ext}"
    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        job.status = "failed"
        job.error_message = f"Failed to save file: {str(e)}"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    # Enqueue job for sequential processing
    enqueue_job(job_id, str(file_path))

    # Return immediately with pending status
    return _build_job_response(job, db)


@router.get("", response_model=List[JobListResponse])
def list_jobs(db: Session = Depends(get_db)):
    """List all jobs."""
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return [
        JobListResponse(
            id=job.id,
            filename=job.filename,
            original_filename=job.original_filename,
            media_type=job.media_type,
            prompt=job.prompt,
            status=job.status,
            auto_fix=job.auto_fix,
            auto_scrub=job.auto_scrub,
            preset=job.preset,
            duration_seconds=job.duration_seconds,
            created_at=job.created_at,
            violation_count=len(job.violations)
        )
        for job in jobs
    ]


@router.get("/presets", response_model=List[PresetResponse])
def list_presets():
    """List the built-in rule presets. Declared before /{job_id} so it isn't shadowed."""
    return [
        PresetResponse(id=pid, name=meta["name"], description=meta["description"])
        for pid, meta in PRESETS.items()
    ]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get job details."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _build_job_response(job, db)


@router.delete("/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    """Delete a job and its associated files."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete uploaded file
    for ext in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aif", ".aiff", ".mp4", ".mov"]:
        file_path = UPLOAD_DIR / f"{job_id}{ext}"
        if file_path.exists():
            file_path.unlink()
            break

    # Delete job (cascades to violations)
    db.delete(job)
    db.commit()

    return {"message": "Job deleted"}


def _build_job_response(job: Job, db: Session) -> JobResponse:
    """Build JobResponse with violation counts."""
    violations = job.violations
    return JobResponse(
        id=job.id,
        filename=job.filename,
        original_filename=job.original_filename,
        media_type=job.media_type,
        prompt=job.prompt,
        status=job.status,
        auto_fix=job.auto_fix,
        auto_scrub=job.auto_scrub,
        preset=job.preset,
        duration_seconds=job.duration_seconds,
        language=job.language,
        created_at=job.created_at,
        error_message=job.error_message,
        violation_count=len(violations),
        pending_count=sum(1 for v in violations if v.status == "pending"),
        accepted_count=sum(1 for v in violations if v.status == "accepted"),
        rejected_count=sum(1 for v in violations if v.status == "rejected")
    )
