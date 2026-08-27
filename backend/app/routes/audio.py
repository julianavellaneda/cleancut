"""
Audio routes - streaming, waveform, and export endpoints.
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Job, Violation
from ..schemas import ExportRequest, ExportResponse
from ..services import exports
from ..services.media_editor import generate_waveform_peaks
from ..services.worker import enqueue_export

router = APIRouter()

# Directories
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"
EXPORT_DIR.mkdir(exist_ok=True)


MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


def _get_audio_path(job_id: str) -> Path | None:
    """Find the audio/video file for a job."""
    for ext in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".mov", ".aif", ".aiff"]:
        path = UPLOAD_DIR / f"{job_id}{ext}"
        if path.exists():
            return path
    return None


def _get_export_path(job_id: str, job: Job) -> Path | None:
    """Find the exported file for a job, or None if no export has been generated."""
    audio_path = _get_audio_path(job_id)
    export_ext = exports.export_suffix(job, audio_path) if audio_path else ".mp3"
    for candidate in (EXPORT_DIR / f"{job_id}_edited{export_ext}", EXPORT_DIR / f"{job_id}_edited.mp3"):
        if candidate.exists():
            return candidate
    return None


@router.get("/{job_id}/audio")
def stream_audio(job_id: str, db: Session = Depends(get_db)):
    """Stream the original audio/video file."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    audio_path = _get_audio_path(job_id)
    if not audio_path:
        raise HTTPException(status_code=404, detail="Audio file not found")

    media_type = MEDIA_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        audio_path,
        media_type=media_type,
        filename=job.filename
    )


@router.get("/{job_id}/audio/waveform")
def get_waveform(job_id: str, db: Session = Depends(get_db)):
    """Get waveform peaks for visualization."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if we have cached waveform data
    if job.waveform_data:
        return {"peaks": json.loads(job.waveform_data)}

    audio_path = _get_audio_path(job_id)
    if not audio_path:
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Generate waveform peaks
    try:
        peaks = generate_waveform_peaks(str(audio_path), num_peaks=800)

        # Cache the waveform data
        job.waveform_data = json.dumps(peaks)
        db.commit()

        return {"peaks": peaks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate waveform: {str(e)}")


@router.post("/{job_id}/export", response_model=ExportResponse, status_code=202)
def export_media(
    job_id: str,
    request: ExportRequest = ExportRequest(),
    db: Session = Depends(get_db)
):
    """
    Queue an edited render of the accepted suggestions.

    Every cheap rejection below still happens synchronously, so a caller with
    nothing accepted gets an immediate, specific 400 rather than a queued job
    that fails minutes later. Only the FFmpeg pass itself is deferred: it can
    run for the length of the media, and holding the request open for that long
    left the UI unable to tell a slow export from a dead one.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")

    audio_path = _get_audio_path(job_id)
    if not audio_path:
        raise HTTPException(status_code=404, detail="Audio file not found")

    accepted = (
        db.query(Violation)
        .filter(Violation.job_id == job_id, Violation.status == "accepted")
        .count()
    )
    if not accepted:
        raise HTTPException(
            status_code=400,
            detail="No accepted edits to remove. Accept some suggested edits first."
        )

    job.export_status = "queued"
    job.export_error = None
    db.commit()

    enqueue_export(job_id, request.edit_action)

    export_filename = exports.export_filename_for(job, exports.export_suffix(job, audio_path))
    return ExportResponse(
        job_id=job_id,
        export_filename=export_filename,
        message=f"Export queued for {accepted} accepted edit(s). Poll the job for export_status.",
        export_status="queued",
    )


@router.get("/{job_id}/export/download")
def download_export(job_id: str, db: Session = Depends(get_db)):
    """Download the exported media file as an attachment."""
    job, export_path, export_filename = _resolve_export(job_id, db)

    return FileResponse(
        export_path,
        media_type=MEDIA_TYPES.get(export_path.suffix.lower(), "application/octet-stream"),
        filename=export_filename,
        headers={"Content-Disposition": f'attachment; filename="{export_filename}"'}
    )


@router.get("/{job_id}/export/stream")
def stream_export(job_id: str, db: Session = Depends(get_db)):
    """Stream the exported media inline, so the result can be played back in the browser.

    Same file as /export/download, served without the attachment disposition.
    """
    _job, export_path, export_filename = _resolve_export(job_id, db)

    return FileResponse(
        export_path,
        media_type=MEDIA_TYPES.get(export_path.suffix.lower(), "application/octet-stream"),
        filename=export_filename,
        headers={"Content-Disposition": f'inline; filename="{export_filename}"'}
    )


def _resolve_export(job_id: str, db: Session) -> tuple[Job, Path, str]:
    """Look up a job and its generated export, raising 404 if either is missing."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Belt and braces. `invalidate_export` already deletes a superseded file, so
    # this normally cannot trigger - but a stale file that survived (an unlink
    # that failed, a render that landed after the edits moved) must not be
    # handed to the user as their finished master.
    if exports.export_is_stale(job):
        raise HTTPException(
            status_code=409,
            detail="This export is out of date. The edits changed since it was rendered; export again.",
        )

    export_path = _get_export_path(job_id, job)
    if not export_path:
        raise HTTPException(
            status_code=404,
            detail="Export not found. Generate export first with POST /export"
        )

    return job, export_path, f"{Path(job.filename).stem}_edited{export_path.suffix}"
