"""
Job routes - upload, list, and status endpoints.
"""

import shutil
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Job, Violation
from ..schemas import JobResponse, JobListResponse
from ..services.processor import get_processor

router = APIRouter()

# Upload directory
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("", response_model=JobResponse)
async def create_job(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload audio file and start processing.
    Processing is synchronous for MVP (single-user local use).
    """
    # Validate file type
    allowed_extensions = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )

    # Create job record
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        filename=file.filename,
        status="processing"
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

    # Process audio (synchronous for MVP)
    try:
        processor = get_processor()
        transcript, analysis = processor.process_audio(str(file_path))

        # Update job with results
        job.duration_seconds = transcript.duration
        job.language = transcript.language
        job.status = "completed"

        # Create violation records
        for v in analysis.violations:
            violation = Violation(
                id=str(uuid.uuid4()),
                job_id=job_id,
                text=v.text,
                start_time=v.start_time,
                end_time=v.end_time,
                rule_violated=v.rule_violated,
                severity=v.severity,
                reasoning=v.reasoning,
                status="pending"
            )
            db.add(violation)

        db.commit()

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

    # Return response with violation counts
    return _build_job_response(job, db)


@router.get("", response_model=List[JobListResponse])
def list_jobs(db: Session = Depends(get_db)):
    """List all jobs."""
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return [
        JobListResponse(
            id=job.id,
            filename=job.filename,
            status=job.status,
            duration_seconds=job.duration_seconds,
            created_at=job.created_at,
            violation_count=len(job.violations)
        )
        for job in jobs
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
    for ext in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"]:
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
        status=job.status,
        duration_seconds=job.duration_seconds,
        language=job.language,
        created_at=job.created_at,
        error_message=job.error_message,
        violation_count=len(violations),
        pending_count=sum(1 for v in violations if v.status == "pending"),
        accepted_count=sum(1 for v in violations if v.status == "accepted"),
        rejected_count=sum(1 for v in violations if v.status == "rejected")
    )
