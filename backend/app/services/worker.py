"""
Job worker - sequential processing of media jobs using a queue.
"""

import queue
import threading
import shutil
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

import ffmpeg

from ..database import SessionLocal
from ..models import Job, Violation
from ..services.processor import get_processor
from ..services.media_editor import DECODE_SAMPLE_RATE, decode_pcm_mono
from ..services.scrubber import Scrubber
from ..services import transcripts
from ..services.levels import find_quiet_regions
from ..services import exports

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Job Queue
job_queue = queue.Queue()

# Directories
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"


@dataclass(frozen=True)
class QueuedTask:
    """
    One unit of background work.

    A named record rather than a positional tuple: the queue now carries two
    kinds of work, and "which element was the file path again" is not a question
    worth re-answering at every unpack site.
    """
    kind: str  # "process" or "export"
    job_id: str
    file_path: str | None = None
    edit_action: str | None = None


def enqueue_job(job_id: str, file_path: str):
    """Add a job to the queue for sequential processing."""
    job_queue.put(QueuedTask(kind="process", job_id=job_id, file_path=file_path))
    logger.info(f"Job {job_id} enqueued. Queue size: {job_queue.qsize()}")


def enqueue_export(job_id: str, edit_action: str | None = None):
    """
    Queue an export render.

    Export goes through the same single worker thread as everything else so a
    two-hour re-encode cannot hold an HTTP request open, and so two exports
    never contend for FFmpeg at once.
    """
    job_queue.put(QueuedTask(kind="export", job_id=job_id, edit_action=edit_action))
    logger.info(f"Export for job {job_id} enqueued. Queue size: {job_queue.qsize()}")


def start_worker():
    """Start the background worker thread."""
    thread = threading.Thread(target=_worker_loop, daemon=True)
    thread.start()
    logger.info("Sequential Job Worker started.")


def _worker_loop():
    """Continuously pull and process tasks from the queue."""
    while True:
        try:
            task = job_queue.get()
            logger.info(f"Worker picking up {task.kind} task for Job {task.job_id}...")
            if task.kind == "export":
                _process_export(task.job_id, task.edit_action)
            else:
                _process_job_sequentially(task.job_id, task.file_path)
            job_queue.task_done()
        except Exception as e:
            logger.error(f"Worker loop error: {str(e)}")


def _append_job_warning(db, job, message: str):
    """
    Add a non-fatal warning to a job without clobbering an existing one.

    ``error_message`` doubles as the warning banner on a completed job, so a
    partial analysis and a skipped level pass have to be able to coexist there -
    overwriting would mean the second problem silently erased the first.
    """
    job.error_message = f"{job.error_message} | {message}" if job.error_message else message
    db.commit()


def _mark_failed(db, job_id: str, message: str):
    """
    Record a failure on the job row, from a session of unknown health.

    The exception that got us here may have left the session mid-transaction, so
    roll back and re-query rather than reusing whatever object the caller had.
    A secondary failure here is logged and swallowed: losing the error message is
    bad, but crashing the worker thread over it is worse.
    """
    try:
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            logger.error(f"Job {job_id} failed and its row is gone; cannot record: {message}")
            return
        job.status = "failed"
        job.error_message = message
        db.commit()
    except Exception:
        logger.exception(f"Could not record the failure of job {job_id}")


def _mark_export_failed(db, job_id: str, message: str):
    """
    Record an export failure without touching ``job.status``.

    A job whose export blew up is still a completed job with a reviewed edit
    list. Marking it `failed` would strand the user's work behind an error
    screen over an FFmpeg problem they can simply retry.
    """
    try:
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            logger.error(f"Export for job {job_id} failed and its row is gone: {message}")
            return
        job.export_status = "failed"
        job.export_error = message
        db.commit()
    except Exception:
        logger.exception(f"Could not record the export failure of job {job_id}")


def _process_export(job_id: str, edit_action: str | None = None):
    """Render the accepted edits for an already-completed job."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Export requested for unknown job {job_id}")
            return

        source_path = _find_source_file(job_id)
        if source_path is None:
            _mark_export_failed(db, job_id, "Source media file not found.")
            return

        job.export_status = "exporting"
        job.export_error = None
        db.commit()

        violations = (
            db.query(Violation)
            .filter(Violation.job_id == job_id, Violation.status == "accepted")
            .order_by(Violation.start_time)
            .all()
        )
        cuts, mutes = exports.partition_edits(violations, edit_action)
        export_path = exports.export_path_for(job, source_path, EXPORT_DIR)
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)

        exports.render_export(str(source_path), export_path, cuts, mutes, job.media_type)

        job.export_status = "ready"
        job.export_error = None
        db.commit()
        logger.info(f"Export for job {job_id} finished: {exports.describe_edits(cuts, mutes)}")

    except Exception as e:
        logger.error(f"Export for job {job_id} failed: {e}", exc_info=True)
        _mark_export_failed(db, job_id, str(e))
    finally:
        db.close()


def _find_source_file(job_id: str) -> Path | None:
    """Locate the uploaded media for a job by probing the known extensions."""
    for ext in (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".mov", ".aif", ".aiff"):
        candidate = UPLOAD_DIR / f"{job_id}{ext}"
        if candidate.exists():
            return candidate
    return None


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
        # Stored before analysis rather than after: analysis is the stage that
        # can fail on a bad LLM response, and a transcript that survives that
        # failure is still worth having on the job.
        job.transcript = transcripts.to_json(transcript)
        db.commit()

        # Step 2: Analyzing
        job.status = "analyzing"
        db.commit()

        analysis = processor.analyze(
            transcript,
            prompt=job.prompt,
            preset=job.preset,
        )

        # A partial analysis still completes - the suggestions it did produce
        # are reviewable - but the job carries a warning naming the spans that
        # went unanalyzed, so "no violations there" is never assumed.
        if getattr(analysis, "failed_chunks", None):
            skipped = len(analysis.failed_chunks)
            job.error_message = (
                f"Partial analysis: {skipped} section(s) of the transcript could not be "
                f"analyzed and may contain unflagged content. "
                + " | ".join(analysis.failed_chunks[:3])
            )
            db.commit()
            logger.warning(f"Job {job_id} analyzed with {skipped} failed chunk(s).")

        # Step 2.5: Deterministic Scrubbing (Silence & Fillers)
        scrubber_violations = []

        # Dead air is confirmed against amplitude, not just against the absence
        # of a transcript - see Scrubber.detect_silence. One decode, reused; the
        # RMS pass itself runs at roughly 1000x realtime.
        #
        # A decode failure is caught here rather than allowed to reach the
        # job-wide handler, which would mark the job `failed` and throw away a
        # perfectly good transcript and analysis. Silence detection is skipped
        # (passing None), never quietly downgraded to transcript gaps, and the
        # job carries a warning saying so. A missing ffmpeg binary cannot be the
        # cause: preflight.verify_environment() refuses to start the server
        # without one, so what lands here is a per-file problem.
        quiet_regions = None
        try:
            samples = decode_pcm_mono(file_path_to_use, DECODE_SAMPLE_RATE)
            quiet_regions = find_quiet_regions(samples, DECODE_SAMPLE_RATE)
        except Exception as e:
            # ffmpeg-python packs the real diagnosis into e.stderr; str(e) is
            # only ever the generic "ffmpeg error (see stderr output for detail)".
            stderr = getattr(e, "stderr", None)
            lines = stderr.decode("utf-8", "replace").strip().splitlines() if stderr else []
            reason = lines[-1] if lines else str(e)
            logger.warning(f"Job {job_id}: level pass failed, skipping dead air detection: {reason}")
            _append_job_warning(db, job, (
                "Dead air detection skipped: the audio could not be decoded for a "
                f"level check, so no silence was measured. ({reason})"
            ))

        # Always run scrubber, but status depends on auto_scrub
        scrubber_violations.extend(Scrubber.detect_silence(transcript, quiet_regions))
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
                rule_violated=getattr(v, "rule_violated", None),
                severity=getattr(v, "severity", None),
                action=v.action,
                reasoning=v.reasoning,
                status=status
            )
            db.add(violation)

        # Step 4: Auto-fix if requested (LLM fixes or Scrubber fixes)
        if job.auto_fix or job.auto_scrub:
            job.status = "exporting"
            job.export_status = "exporting"
            db.commit()

            export_path = exports.export_path_for(job, file_path_to_use, EXPORT_DIR)

            # Map pre-accepted suggestions to time segments. auto_fix governs the
            # LLM's suggestions, auto_scrub the deterministic ones. Each keeps its
            # own action - a preset like pii-redaction defaults to mute, and
            # auto-applying it as a cut would delete the audio instead of
            # silencing it.
            applied = [
                v for v in all_suggestions
                if (v.label in exports.SCRUBBER_LABELS and job.auto_scrub)
                or (v.label not in exports.SCRUBBER_LABELS and job.auto_fix)
            ]
            cuts, mutes = exports.partition_edits(applied)
            exports.render_export(file_path_to_use, export_path, cuts, mutes, job.media_type)
            job.export_status = "ready"

        job.status = "completed"
        db.commit()
        logger.info(f"Job {job_id} completed successfully.")

    except Exception as e:
        # Never touch `job` here - if the initial query is what threw, it is
        # unbound, and the resulting NameError would mask the real cause.
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        _mark_failed(db, job_id, str(e))
    finally:
        db.close()
