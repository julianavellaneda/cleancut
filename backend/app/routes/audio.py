"""
Audio routes - streaming, waveform, and export endpoints.
"""

import json
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from ..database import get_db
from ..models import Job, Violation
from ..schemas import ExportRequest, ExportResponse
from ..services import exports
from ..services.media_editor import generate_waveform_peaks
from ..services import task_store
from ..services.worker import enqueue_export, publish

router = APIRouter()

# Directories. The export directory lives in `services.exports`, which is also
# what creates it before a render; nothing here writes into it.
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"


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


# One lock per job, so two requests for the same waveform take turns instead of
# each running its own FFmpeg decode. `_waveform_locks_guard` protects the dict
# itself; the per-job locks are what the requests actually wait on.
#
# This route is a sync `def`, so FastAPI runs it in the thread pool - which is
# exactly why the pile-up was possible. A page reload before the first decode
# finishes, or a second tab, meant two threads each holding a full decode of the
# same recording (~115 MB an hour at 8 kHz f32) to compute a byte-identical
# answer. The waiter does not repeat the work: it re-reads the cached column
# after acquiring, by which time the winner has written it.
_waveform_locks: dict[str, threading.Lock] = {}
_waveform_locks_guard = threading.Lock()


def _waveform_lock(job_id: str) -> threading.Lock:
    """The lock for one job's waveform generation, created on first ask."""
    with _waveform_locks_guard:
        return _waveform_locks.setdefault(job_id, threading.Lock())


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
    export_dir = exports.EXPORT_DIR
    for candidate in (export_dir / f"{job_id}_edited{export_ext}", export_dir / f"{job_id}_edited.mp3"):
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

    # Generate waveform peaks, one decode at a time per job.
    with _waveform_lock(job_id):
        # Re-read the cache now that it is our turn. Whoever held the lock just
        # committed the peaks for this exact file, so the second request through
        # is a cache hit rather than a duplicate decode. `expire` drops this
        # session's copy of the row, forcing the read to go back to the DB - the
        # writer was a different session and this one would otherwise serve the
        # NULL it loaded before waiting.
        #
        # The row can also be gone by now - a retention sweep or a manual delete
        # while we waited - and re-reading an expired attribute off a deleted row
        # raises. That is a 404, the same answer the job lookup above would have
        # given a moment later, not a 500.
        try:
            db.expire(job, ["waveform_data"])
            cached = job.waveform_data
        except ObjectDeletedError:
            raise HTTPException(status_code=404, detail="Job not found")
        if cached:
            return {"peaks": json.loads(cached)}

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

    # One render per job at a time. Queuing a second used to be silently
    # allowed - the later one simply overwrote the earlier's output - which
    # burned an FFmpeg pass over the length of the media for nothing, and let a
    # double-click leave `export_status` describing whichever finished last.
    # 409 rather than 202: the request is refused, and the caller is already
    # polling the state that will tell it when the first one lands.
    if task_store.has_outstanding(db, job_id, "export"):
        raise HTTPException(
            status_code=409,
            detail="An export is already in progress for this job. Wait for it to finish.",
        )

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

    # `export_status` and the task row commit as one, and the task is published
    # only after. Committing "queued" separately left a job advertising a render
    # that had not been recorded - the UI showed "Exporting..." forever, and a
    # restart found no task to replay because none was ever written.
    job.export_status = "queued"
    job.export_error = None
    try:
        task = enqueue_export(job_id, request.edit_action, db=db)
    except task_store.DuplicateTask:
        # The `has_outstanding` check above is a read followed by a write, so
        # two requests can pass it together. The constraint catches that pair;
        # this turns it into the same 409 the check already gives, rather than
        # a 500 and two FFmpeg passes over the same output path.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An export is already in progress for this job. Wait for it to finish.",
        )
    db.commit()
    publish(task)

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
