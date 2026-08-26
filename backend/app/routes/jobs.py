"""
Job routes - upload, list, and status endpoints.
"""

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..limits import (
    MediaDurationUnknown,
    MediaTooLong,
    UploadTooLarge,
    enforce_duration_limit,
    max_duration_seconds,
    max_upload_bytes,
    save_within_limit,
)
from ..models import Job
from ..schemas import (
    JobResponse,
    JobListResponse,
    PresetResponse,
    TranscriptResponse,
    TranscriptSegment,
)
from ..services.processor import PRESETS, is_valid_preset
from ..services.retention import delete_job_files
from ..services import transcripts
from ..services.worker import enqueue_job

router = APIRouter()

# Directories
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"
EXPORT_DIR.mkdir(exist_ok=True)


def _discard_job(db: Session, job: Job, file_path: Path) -> None:
    """
    Drop a job that was rejected by a guardrail, along with anything on disk.

    The row is created before the file is streamed (it owns the id the file is
    named after), so a rejected upload has to be rolled back rather than left as
    a `failed` job. A guardrail rejection is a 4xx the client can act on, not a
    processing failure worth keeping in the jobs list.
    """
    file_path.unlink(missing_ok=True)
    db.delete(job)
    db.commit()


@router.post("", response_model=JobResponse)
def create_job(
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

    Deliberately a plain `def`: this handler streams the upload to disk and
    shells out to ffprobe, both blocking calls. Declared `async` they ran on the
    event loop, so a single large upload stalled every status poll and every
    other request for its whole duration. FastAPI runs a sync handler in its
    thread pool instead.
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

    # Save uploaded file, enforcing the size cap as it streams in.
    file_path = UPLOAD_DIR / f"{job_id}{file_ext}"
    try:
        save_within_limit(file.file, file_path, max_upload_bytes())
    except UploadTooLarge as e:
        _discard_job(db, job, file_path)
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        job.status = "failed"
        job.error_message = f"Failed to save file: {str(e)}"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    # Duration cap, enforced fail-closed. A duration ffprobe cannot read is not
    # "short enough" - accepting it is how an unbounded stream gets past the cap
    # and holds the sequential worker for hours.
    try:
        duration = enforce_duration_limit(file_path, max_duration_seconds())
    except MediaTooLong as e:
        _discard_job(db, job, file_path)
        raise HTTPException(status_code=413, detail=str(e))
    except MediaDurationUnknown as e:
        _discard_job(db, job, file_path)
        raise HTTPException(status_code=422, detail=str(e))

    job.duration_seconds = duration
    db.commit()

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


@router.get("/{job_id}/transcript", response_model=TranscriptResponse)
def get_transcript(job_id: str, db: Session = Depends(get_db)):
    """
    The transcript the analysis ran on.

    404 covers three different absences on purpose - an unknown job, a job that
    has not reached the transcribing stage yet, and a job from before the column
    existed. All three mean "there is nothing to read here", and the panel that
    consumes this hides itself either way. Returning an empty segment list
    instead would read as "this recording is silent", which is a different and
    much more misleading claim in a review tool.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stored = transcripts.from_json(job.transcript)
    if stored is None:
        raise HTTPException(status_code=404, detail="No transcript stored for this job.")

    return TranscriptResponse(
        job_id=job.id,
        language=stored.language or job.language,
        duration=stored.duration if stored.duration is not None else job.duration_seconds,
        segments=[
            TranscriptSegment(start=seg.start, end=seg.end, text=seg.text)
            for seg in stored.segments
        ],
    )


@router.delete("/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    """
    Delete a job and its associated files.

    File removal goes through ``retention.delete_job_files`` so a manual delete
    and a retention sweep leave the same state behind. The previous inline loop
    walked a hardcoded extension list and stopped at the upload, which left the
    export sitting in ``exports/`` after the job that explained it was gone.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    delete_job_files(job_id, UPLOAD_DIR, EXPORT_DIR)

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
