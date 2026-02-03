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
from ..services.audio_editor import AudioEditor, generate_waveform_peaks

router = APIRouter()

# Directories
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"
EXPORT_DIR.mkdir(exist_ok=True)


def _get_audio_path(job_id: str) -> Path | None:
    """Find the audio file for a job."""
    for ext in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"]:
        path = UPLOAD_DIR / f"{job_id}{ext}"
        if path.exists():
            return path
    return None


@router.get("/{job_id}/audio")
def stream_audio(job_id: str, db: Session = Depends(get_db)):
    """Stream the original audio file."""
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
        ".webm": "audio/webm"
    }
    media_type = media_types.get(audio_path.suffix.lower(), "audio/mpeg")

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
def export_audio(
    job_id: str,
    request: ExportRequest = ExportRequest(),
    db: Session = Depends(get_db)
):
    """Generate edited audio with accepted violations removed/muted."""
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
            detail="No accepted violations to remove. Accept some violations first."
        )

    # Prepare segments to edit
    segments = [(v.start_time, v.end_time) for v in violations]

    # Process audio
    try:
        editor = AudioEditor()
        audio = editor.load_audio(str(audio_path))

        if request.edit_action == "mute":
            edited = editor.mute_segments(audio, segments)
        else:  # cut
            edited = editor.cut_segments(audio, segments)

        # Export
        export_filename = f"{Path(job.filename).stem}_edited.mp3"
        export_path = EXPORT_DIR / f"{job_id}_edited.mp3"
        editor.export(edited, str(export_path), format="mp3")

        return ExportResponse(
            job_id=job_id,
            export_filename=export_filename,
            message=f"Exported with {len(violations)} violation(s) {request.edit_action}ed"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.get("/{job_id}/export/download")
def download_export(job_id: str, db: Session = Depends(get_db)):
    """Download the exported audio file."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    export_path = EXPORT_DIR / f"{job_id}_edited.mp3"
    if not export_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Export not found. Generate export first with POST /export"
        )

    export_filename = f"{Path(job.filename).stem}_edited.mp3"

    return FileResponse(
        export_path,
        media_type="audio/mpeg",
        filename=export_filename,
        headers={"Content-Disposition": f'attachment; filename="{export_filename}"'}
    )
