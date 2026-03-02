"""
Job worker - sequential processing of media jobs using a queue.
"""

import queue
import threading
import shutil
import logging
import uuid
import ffmpeg
from pathlib import Path

from ..database import SessionLocal
from ..models import Job, Violation
from ..services.processor import get_processor
from ..services.media_editor import MediaEditor
from ..services.scrubber import Scrubber

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Job Queue
job_queue = queue.Queue()

# Directories
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"


def enqueue_job(job_id: str, file_path: str):
    """Add a job to the queue for sequential processing."""
    job_queue.put((job_id, file_path))
    logger.info(f"Job {job_id} enqueued. Queue size: {job_queue.qsize()}")


def start_worker():
    """Start the background worker thread."""
    thread = threading.Thread(target=_worker_loop, daemon=True)
    thread.start()
    logger.info("Sequential Job Worker started.")


def _worker_loop():
    """Continuously pull and process jobs from the queue."""
    while True:
        try:
            job_id, file_path = job_queue.get()
            logger.info(f"Worker picking up Job {job_id}...")
            _process_job_sequentially(job_id, file_path)
            job_queue.task_done()
        except Exception as e:
            logger.error(f"Worker loop error: {str(e)}")


def _process_job_sequentially(job_id: str, file_path: str):
    """Run transcription and semantic analysis for a single job."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        file_path_obj = Path(file_path)
        file_ext = file_path_obj.suffix.lower()
        file_path_to_use = file_path

        # Step 0: Convert AIFF to MP3 if needed (Whisper handles most other formats)
        if file_ext in [".aif", ".aiff"]:
            job.status = "converting"
            db.commit()
            
            try:
                mp3_path = file_path_obj.with_suffix(".mp3")
                ffmpeg.input(file_path).output(str(mp3_path), format="mp3").run(overwrite_output=True, quiet=True)
                file_path_to_use = str(mp3_path)
                
                # Update job record with new filename
                job.filename = f"{job_id}.mp3"
                db.commit()
                
                # Delete original AIFF
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

        analysis = processor.analyze(transcript, prompt=job.prompt)

        # Step 2.5: Deterministic Scrubbing (Silence & Fillers)
        scrubber_violations = []
        # Always run scrubber, but status depends on auto_scrub
        scrubber_violations.extend(Scrubber.detect_silence(transcript))
        scrubber_violations.extend(Scrubber.detect_filler_words(transcript))

        # Combine all violations
        all_suggestions = analysis.violations + scrubber_violations

        # Step 3: Save results (Suggested Edits)
        for v in all_suggestions:
            # For scrubber violations, we use auto_scrub to decide initial status
            # For LLM violations, we use auto_fix
            is_scrubber = v.label in ["Dead Air", "Filler Word"]
            if is_scrubber:
                status = "accepted" if job.auto_scrub else "pending"
            else:
                status = "accepted" if job.auto_fix else "pending"
                
            violation = Violation(
                id=str(uuid.uuid4()),
                job_id=job_id,
                text=v.text,
                start_time=v.start_time,
                end_time=v.end_time,
                label=v.label,
                action=v.action,
                reasoning=v.reasoning,
                status=status
            )
            db.add(violation)

        # Step 4: Auto-fix if requested (LLM fixes or Scrubber fixes)
        if job.auto_fix or job.auto_scrub:
            job.status = "exporting"
            db.commit()
            
            # Use original extension for video, mp3 for audio
            export_ext = file_path_obj.suffix if job.media_type == "video" else ".mp3"
            export_path = EXPORT_DIR / f"{job_id}_edited{export_ext}"
            
            editor = MediaEditor()
            
            # Map accepted suggestions to time segments for editing
            # If auto_fix is on, we take all LLM violations.
            # If auto_scrub is on, we take all scrubber violations.
            segments_to_fix = []
            for v in all_suggestions:
                is_scrubber = v.label in ["Dead Air", "Filler Word"]
                if (is_scrubber and job.auto_scrub) or (not is_scrubber and job.auto_fix):
                    segments_to_fix.append((v.start_time, v.end_time))

            if segments_to_fix:
                editor.cut_segments(
                    file_path_to_use, 
                    str(export_path), 
                    segments_to_fix, 
                    media_type=job.media_type
                )
            else:
                # No suggestions found, just copy/transcode original as edited version
                ffmpeg.input(file_path_to_use).output(str(export_path)).run(overwrite_output=True, quiet=True)

        job.status = "completed"
        db.commit()
        logger.info(f"Job {job_id} completed successfully.")

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        db.commit()
        logger.error(f"Job {job_id} failed: {str(e)}")
    finally:
        db.close()
