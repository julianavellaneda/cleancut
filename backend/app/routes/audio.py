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
from ..services.media_editor import MediaEditor, generate_waveform_peaks

router = APIRouter()

# Directories
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"
EXPORT_DIR.mkdir(exist_ok=True)


def _get_audio_path(job_id: str) -> Path | None:
    """Find the audio/video file for a job."""
    for ext in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".mov", ".aif", ".aiff"]:
        path = UPLOAD_DIR / f"{job_id}{ext}"
        if path.exists():
            return path
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

    # Determine media type
    media_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime"
    }
    media_type = media_types.get(audio_path.suffix.lower(), "application/octet-stream")

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


@router.post("/{job_id}/export", response_model=ExportResponse)
def export_media(
    job_id: str,
    request: ExportRequest = ExportRequest(),
    db: Session = Depends(get_db)
):
    """Generate edited media with accepted violations removed/muted."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")

    audio_path = _get_audio_path(job_id)
    if not audio_path:
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Get accepted violations
    violations = (
        db.query(Violation)
        .filter(Violation.job_id == job_id, Violation.status == "accepted")
        .order_by(Violation.start_time)
        .all()
    )

    if not violations:
        raise HTTPException(
            status_code=400,
            detail="No accepted edits to remove. Accept some suggested edits first."
        )

    # Prepare segments to edit
    segments = [(v.start_time, v.end_time) for v in violations]

    # Process media
    try:
        editor = MediaEditor()
        
        # Export filename and path
        export_ext = audio_path.suffix if job.media_type == "video" else ".mp3"
        export_filename = f"{Path(job.filename).stem}_edited{export_ext}"
        export_path = EXPORT_DIR / f"{job_id}_edited{export_ext}"

        if request.edit_action == "mute":
            editor.mute_segments(str(audio_path), str(export_path), segments, media_type=job.media_type)
        else:  # cut
            editor.cut_segments(str(audio_path), str(export_path), segments, media_type=job.media_type)

        return ExportResponse(
            job_id=job_id,
            export_filename=export_filename,
            message=f"Exported with {len(violations)} edit(s) {request.edit_action}ed"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.get("/{job_id}/export/download")
def download_export(job_id: str, db: Session = Depends(get_db)):
    """Download the exported media file."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Try different possible edited extensions
    audio_path = _get_audio_path(job_id)
    export_ext = audio_path.suffix if (audio_path and job.media_type == "video") else ".mp3"
    export_path = EXPORT_DIR / f"{job_id}_edited{export_ext}"
    
    if not export_path.exists():
        # Fallback to .mp3 if exact match not found
        export_path = EXPORT_DIR / f"{job_id}_edited.mp3"

    if not export_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Export not found. Generate export first with POST /export"
        )

    export_filename = f"{Path(job.filename).stem}_edited{export_path.suffix}"

    media_type = "video/mp4" if export_path.suffix == ".mp4" else "audio/mpeg"

    return FileResponse(
        export_path,
        media_type=media_type,
        filename=export_filename,
        headers={"Content-Disposition": f'attachment; filename="{export_filename}"'}
    )
