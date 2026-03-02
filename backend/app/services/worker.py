"""
Job worker - sequential processing of audio jobs using a queue.
"""

import queue
import threading
import shutil
import logging
import uuid
from pathlib import Path
from pydub import AudioSegment

from ..database import SessionLocal
from ..models import Job, Violation
from ..services.processor import get_processor
from ..services.audio_editor import AudioEditor

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
    """Run transcription and compliance analysis for a single job."""
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

        analysis = processor.analyze(transcript)

        # Step 3: Save results
        violations_to_fix = []
        for v in analysis.violations:
            status = "accepted" if job.auto_fix else "pending"
            violation = Violation(
                id=str(uuid.uuid4()),
                job_id=job_id,
                text=v.text,
                start_time=v.start_time,
                end_time=v.end_time,
                rule_violated=v.rule_violated,
                severity=v.severity,
                reasoning=v.reasoning,
                status=status
            )
            db.add(violation)
            if job.auto_fix:
                violations_to_fix.append((v.start_time, v.end_time))

        # Step 4: Auto-fix if requested
        if job.auto_fix:
            job.status = "exporting"
            db.commit()
            
            export_path = EXPORT_DIR / f"{job_id}_edited.mp3"
            editor = AudioEditor()

            if violations_to_fix:
                audio = editor.load_audio(file_path_to_use)
                edited = editor.cut_segments(audio, violations_to_fix)
                editor.export(edited, str(export_path), format="mp3")
            else:
                # No violations found, just copy the original as edited version
                if file_path_to_use.lower().endswith(".mp3"):
                    shutil.copy(file_path_to_use, export_path)
                else:
                    audio = editor.load_audio(file_path_to_use)
                    editor.export(audio, str(export_path), format="mp3")

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
