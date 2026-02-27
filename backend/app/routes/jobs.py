"""
Job routes - upload, list, and status endpoints.
"""

import shutil
import threading
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from pydub import AudioSegment

from ..database import get_db, SessionLocal
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
    Upload audio file and start background processing.
    Returns immediately after saving the file; processing runs in a background thread.
    Poll GET /api/jobs/{id} to track progress (transcribing → analyzing → completed).
    """
    # Validate file type
    allowed_extensions = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aif", ".aiff"}
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
        status="pending"
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

    # Spawn background thread for processing
    thread = threading.Thread(
        target=_process_job_background,
        args=(job_id, str(file_path)),
        daemon=True
    )
    thread.start()

    # Return immediately with pending status
    return _build_job_response(job, db)


def _process_job_background(job_id: str, file_path: str):
    """Run transcription and compliance analysis in a background thread."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        file_path_obj = Path(file_path)
        file_ext = file_path_obj.suffix.lower()
        file_path_to_use = file_path

        # Step 0: Convert AIFF to MP3 if needed
        if file_ext in [".aif", ".aiff"]:
            job.status = "converting"
            db.commit()
            
            try:
                mp3_path = file_path_obj.with_suffix(".mp3")
                audio = AudioSegment.from_file(file_path, format="aiff")
                audio.export(mp3_path, format="mp3")
                file_path_to_use = str(mp3_path)
                
                # Optionally delete original AIFF to save space
                file_path_obj.unlink()
            except Exception as e:
                raise Exception(f"AIFF to MP3 conversion failed: {str(e)}")

        # Step 1: Transcribing
        job.status = "transcribing"
        db.commit()

        processor = get_processor()
        transcript = processor.transcribe(file_path_to_use)

        job.duration_seconds = transcript.duration
        job.language = transcript.language

        # Step 2: Analyzing
        job.status = "analyzing"
        db.commit()

        analysis = processor.analyze(transcript)

        # Step 3: Save results
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

        job.status = "completed"
        db.commit()

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        db.commit()
    finally:
        db.close()


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
    for ext in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aif", ".aiff"]:
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
