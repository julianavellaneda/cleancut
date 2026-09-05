"""
Job worker - sequential processing of media jobs using a queue.
"""

import logging
import queue
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import ffmpeg
from sqlalchemy import or_

from ..database import SessionLocal
from ..models import Job, Violation
from ..services import exports, task_store, transcripts
from ..services.levels import find_quiet_regions
from ..services.media_editor import DECODE_SAMPLE_RATE, decode_pcm_mono
from ..services.processor import get_processor
from ..services.scrubber import Scrubber
from ..services.task_store import MAX_ATTEMPTS, QueuedTask

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Job Queue
job_queue = queue.Queue()

# Directories. The export directory is not one of these: `services.exports`
# owns it, and is read through at call time so one patch reaches every caller.
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"


def publish(task: QueuedTask) -> QueuedTask:
    """
    Hand an already-recorded task to the worker thread.

    Split out from recording so a route can commit first and publish second.
    Nothing may be published before its row is committed: the in-memory queue
    must never hold work the database has not promised to keep.
    """
    job_queue.put(task)
    logger.info(f"{task.kind} task for job {task.job_id} published. Queue size: {job_queue.qsize()}")
    return task


def _enqueue(task: QueuedTask, db=None) -> QueuedTask:
    """
    Write the task down, then hand it to the worker thread.

    With `db`, the row joins the caller's transaction and this returns *without*
    publishing: the caller commits its own change alongside the row and then
    calls :func:`publish`. That is how every route enqueues, so a job can never
    be committed `pending` or `queued` with its task row missing.

    Without `db`, the row is committed in a session of its own and published
    here. That path is for callers with no transaction to join - recovery, and
    tests.
    """
    if db is not None:
        return task_store.record_in(db, task)

    task = task_store.record(task)
    return publish(task)


def enqueue_job(job_id: str, file_path: str, db=None) -> QueuedTask:
    """Add a job to the queue for sequential processing."""
    return _enqueue(QueuedTask(kind="process", job_id=job_id, file_path=file_path), db)


def enqueue_export(job_id: str, edit_action: str | None = None, db=None) -> QueuedTask:
    """
    Queue an export render.

    Export goes through the same single worker thread as everything else so a
    two-hour re-encode cannot hold an HTTP request open, and so two exports
    never contend for FFmpeg at once. The `(job_id, kind)` constraint on the
    task row is what makes "never two" true when two requests arrive together,
    rather than merely likely.
    """
    return _enqueue(QueuedTask(kind="export", job_id=job_id, edit_action=edit_action), db)


def enqueue_reanalysis(
    job_id: str, prompt: str | None = None, preset: str | None = None, db=None
) -> QueuedTask:
    """
    Queue a fresh analysis of a job's stored transcript.

    Same single worker thread as everything else, so a re-run queues behind any
    job already transcribing rather than competing with it for the machine.

    The new question travels with the task. It is not written onto the job
    until the answer comes back - see :func:`_process_reanalysis`.
    """
    return _enqueue(
        QueuedTask(kind="reanalyze", job_id=job_id, prompt=prompt, preset=preset), db
    )


@dataclass(frozen=True)
class RecoveryReport:
    """What one startup reconciliation did. Returned for logging and tests."""

    replayed: int = 0
    abandoned: int = 0
    reconciled: int = 0
    dropped: int = 0

    @property
    def did_something(self) -> bool:
        return bool(self.replayed or self.abandoned or self.reconciled or self.dropped)


# The statuses that mean the analysis pipeline still owes this job an answer.
# Mirrors `retention.TERMINAL_STATUSES` from the other side: a job in one of
# these was mid-flight when the process ended.
UNFINISHED_STATUSES = frozenset({"pending", "converting", "transcribing", "analyzing", "exporting"})
ACTIVE_EXPORT_STATUSES = frozenset({"queued", "exporting"})


def _abandon(db, job, kind: str, attempts: int):
    """
    Give up on a task that has already been tried too many times.

    A task that takes the process down with it comes back on the next boot and
    takes it down again; without a stop, one unreadable upload is a permanent
    crash loop. Where the reason gets recorded follows the same split as every
    other failure here: an export or a re-analysis leaves the reviewed job
    `completed`, because neither is allowed to strand finished work behind an
    error screen, while a first-pass failure is a failed job.
    """
    detail = f"abandoned after {attempts} attempt(s); it did not survive being retried"
    if kind == "export":
        job.export_status = "failed"
        job.export_error = f"Export {detail}."
    elif kind == "reanalyze":
        job.status = "completed"
        job.error_message = (
            f"Re-analysis {detail}. The previous suggestions are unchanged."
        )
    else:
        job.status = "failed"
        job.error_message = f"Processing {detail}."
    logger.error(f"Task {kind} for job {job.id} {detail}.")


def recover_interrupted_work() -> RecoveryReport:
    """
    Put the queue back the way the last process left it.

    Two passes, because there are two ways work can be outstanding.

    The first is a task row: written before the in-memory put and deleted after
    the work, so anything still here was interrupted. Those are replayed in
    their original order - unless the job they name is gone (nothing to run), or
    they have already used up `MAX_ATTEMPTS`.

    The second is a job whose *status* says it is mid-flight with no task to
    explain it. That is the narrow window between committing the job row and
    recording its task, plus every row created before this table existed. A
    first pass that never stored a transcript is safe to simply run again, so it
    is re-queued. Anything else is not: a job already carrying a transcript,
    suggestions and a reviewer's decisions could be sitting in `analyzing`
    because a *re-analysis* was interrupted, and re-running it as a fresh job
    would re-transcribe over the top and delete a review to fix a status field.
    Those are marked failed with a message saying what to do, which is a
    recoverable state; guessing wrong is not.
    """
    db = SessionLocal()
    try:
        replayed = abandoned = reconciled = dropped = 0

        for row in task_store.outstanding(db):
            job = db.query(Job).filter(Job.id == row.job_id).first()
            if job is None:
                # The job was deleted while its task sat in the queue. The
                # cascade normally takes these; a row from a wiped database
                # (`/api/admin/reset-database` deletes in bulk) can outlive it.
                db.delete(row)
                dropped += 1
                continue
            if (row.attempts or 0) >= MAX_ATTEMPTS:
                _abandon(db, job, row.kind, row.attempts or 0)
                db.delete(row)
                abandoned += 1
                continue
            row.state = "pending"
            job_queue.put(task_store.to_task(row))
            replayed += 1

        db.commit()

        kinds_by_job = task_store.outstanding_kinds_by_job(db)
        stranded = db.query(Job).filter(
            or_(
                Job.status.in_(UNFINISHED_STATUSES),
                Job.export_status.in_(ACTIVE_EXPORT_STATUSES),
            )
        ).all()

        for job in stranded:
            kinds = kinds_by_job.get(job.id, set())

            if job.status in UNFINISHED_STATUSES and not (kinds & {"process", "reanalyze"}):
                source = _find_source_file(job.id)
                if transcripts.from_json(job.transcript) is None and source is not None:
                    job.status = "pending"
                    _enqueue(QueuedTask(kind="process", job_id=job.id, file_path=str(source)))
                    logger.info(f"Job {job.id} was interrupted before it ran; re-queued.")
                else:
                    job.status = "failed"
                    job.error_message = (
                        "Interrupted by a server restart. Re-analyze this job, or upload "
                        "the file again, to try once more."
                    )
                reconciled += 1

            if ((job.export_status or "none") in ACTIVE_EXPORT_STATUSES
                    and not (kinds & {"export", "process"})):
                # `process` counts here too: an `auto_fix` job renders inside its
                # own task, so a replayed process task is already going to
                # produce the export this status is waiting on.
                #
                # Not re-queued: `edit_action` lived on the task row and is gone,
                # so the only render we could start is one nobody asked for.
                job.export_status = "failed"
                job.export_error = (
                    "The render was interrupted by a server restart. Export again."
                )
                reconciled += 1

        db.commit()

        report = RecoveryReport(replayed, abandoned, reconciled, dropped)
        if report.did_something:
            logger.info(
                f"Startup recovery: replayed {replayed} task(s), abandoned {abandoned}, "
                f"reconciled {reconciled} job(s), dropped {dropped} orphan(s)."
            )
        return report
    except Exception:
        logger.exception("Startup recovery failed; the queue starts empty.")
        db.rollback()
        return RecoveryReport()
    finally:
        db.close()


def start_worker():
    """Start the background worker thread."""
    thread = threading.Thread(target=_worker_loop, daemon=True)
    thread.start()
    logger.info("Sequential Job Worker started.")


def _dispatch(task: QueuedTask):
    """Run one task. Split out so recovery and tests can drive it directly."""
    if task.kind == "export":
        _process_export(task.job_id, task.edit_action)
    elif task.kind == "reanalyze":
        _process_reanalysis(task.job_id, prompt=task.prompt, preset=task.preset)
    else:
        _process_job_sequentially(task.job_id, task.file_path)


def _run_task(task: QueuedTask):
    """
    Claim one task, run it, and clear it from the books.

    The durable row is opened before the work and deleted after it, in a
    `finally`: an exception escaping a handler must still retire the task.
    Anything that got this far has already recorded its own failure on the job,
    and replaying it on the next boot would re-run a pipeline expected to fail
    again while overwriting the reason it failed the first time.
    """
    try:
        task_store.begin(task)
        logger.info(f"Worker picking up {task.kind} task for Job {task.job_id}...")
        _dispatch(task)
    except Exception as e:
        logger.error(f"Worker loop error: {str(e)}")
    finally:
        task_store.finish(task)


def _worker_loop():
    """
    Continuously pull and process tasks from the queue.

    `task_done()` sits in a `finally`; it used to be the last line of a `try`,
    where an escaping exception skipped it and left the queue's unfinished
    count permanently wrong.
    """
    while True:
        task = job_queue.get()
        try:
            _run_task(task)
        finally:
            job_queue.task_done()


def _is_pre_accepted(suggestion, job) -> bool:
    """
    Whether a suggestion may be applied without anyone having looked at it.

    `auto_scrub` governs the deterministic detectors, `auto_fix` the LLM's
    suggestions - two separate promises about two separate kinds of confidence.

    Neither flag covers a suggestion the analyzer could not place. When a quote
    cannot be found in the transcript, its span is the model's own estimate, and
    applying an estimate unattended cuts whatever happens to be there. Those land
    as `pending` however the job was configured: the flag was a statement about
    trusting the *findings*, not about trusting a guess at where one is.

    `is_ambiguous` is the same argument one level down. The scrubber matches on
    spelling, and a few of the spellings it matches are ordinary words - cutting
    an unevidenced "like" unattended turns "I like this" into "I this". Neither
    flag says the suggestion is wrong; both say it is not the kind of thing that
    gets applied with nobody in the room.
    """
    if getattr(suggestion, "is_approximate", False):
        return False
    if getattr(suggestion, "is_ambiguous", False):
        return False
    if suggestion.label in exports.SCRUBBER_LABELS:
        return bool(job.auto_scrub)
    return bool(job.auto_fix)


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

        # Captured before the edits are read, and compared again once the render
        # lands. A reviewer can accept or reject something while a long re-encode
        # is running; without this check the worker would then mark a file
        # "ready" that answers a question nobody is asking any more.
        rendered_revision = job.edit_revision or 0

        violations = (
            db.query(Violation)
            .filter(Violation.job_id == job_id, Violation.status == "accepted")
            .order_by(Violation.start_time)
            .all()
        )
        cuts, mutes = exports.partition_edits(violations, edit_action)
        exports.ensure_export_dir()
        export_path = exports.export_path_for(job, source_path)

        exports.render_export(str(source_path), export_path, cuts, mutes, job.media_type)

        # Two questions on the way back, in this order: does the job still
        # exist, and do its edits still match. The first is the tombstone. A
        # delete is refused while a render is in flight, but a job can finish
        # between that check and the delete - and this render then produces a
        # file for a job that is gone, which nothing but a retention sweep would
        # ever collect.
        #
        # `db.refresh(job)` used to answer the second question, but it raises
        # rather than answering when the row is gone. The re-query below has to
        # be preceded by `expire_all`: this session loaded the job before the
        # render started, so an unexpired query would be served from the
        # identity map and compare against the revision as it stood *then* -
        # which is exactly the value the check exists to distrust.
        db.expire_all()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            exports.delete_export_files(job_id)
            logger.info(
                f"Export for job {job_id} discarded: the job was deleted while it rendered."
            )
            return

        if (job.edit_revision or 0) != rendered_revision:
            # The edit list moved under the render. Publishing it would put a
            # download button next to a file that no longer matches the review,
            # which is the exact failure this phase exists to close.
            exports.delete_export_files(job_id)
            job.export_status = "none"
            job.export_error = None
            job.export_revision = None
            db.commit()
            logger.info(
                f"Export for job {job_id} discarded: the edits changed while it rendered."
            )
            return

        job.export_status = "ready"
        job.export_error = None
        job.export_revision = rendered_revision
        db.commit()
        logger.info(f"Export for job {job_id} finished: {exports.describe_edits(cuts, mutes)}")

    except Exception as e:
        logger.error(f"Export for job {job_id} failed: {e}", exc_info=True)
        _mark_export_failed(db, job_id, str(e))
    finally:
        db.close()


def _process_reanalysis(job_id: str, prompt: str | None = None, preset: str | None = None):
    """
    Re-run the LLM analysis over a job's stored transcript.

    The point of storing the transcript: a new prompt used to mean a new
    Whisper pass, which is the slowest and most expensive stage of the job and
    has nothing to do with the question being changed.

    What it replaces and what it leaves alone is the whole design here. The
    LLM's suggestions are the answer to the old prompt, so they go - including
    the ones already accepted or rejected, since a decision about a suggestion
    that no longer exists cannot be carried forward honestly. The scrubber's
    are deterministic, unrelated to the prompt, and would come back identical,
    so they and every decision made on them stay exactly as they are.

    The new question is written onto the job in the *same commit* as the
    suggestions it produced, and not before. `jobs.prompt` is what the review
    screen labels the list with, so writing it at request time made a failed
    re-run - or a crash, or a shutdown - leave the old suggestions sitting under
    the new prompt, each one apparently the answer to a question nobody had
    asked when it was made. Deferring it means there is nothing to restore on
    failure: the row was never moved.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Re-analysis requested for unknown job {job_id}")
            return

        stored = transcripts.from_json(job.transcript)
        if stored is None:
            _mark_reanalysis_failed(
                db, job_id, "Re-analysis needs a stored transcript; this job has none.",
            )
            return

        job.status = "analyzing"
        # The warning belonged to the previous analysis. Clearing it here means
        # a re-run that succeeds does not inherit "partial analysis" from the
        # run it replaced.
        job.error_message = None
        db.commit()

        transcript = transcripts.to_transcript_result(stored)
        analysis = get_processor().analyze(
            transcript, prompt=prompt, preset=preset,
        )

        (db.query(Violation)
           .filter(Violation.job_id == job_id,
                   Violation.label.notin_(exports.SCRUBBER_LABELS))
           .delete(synchronize_session=False))

        for v in analysis.violations:
            db.add(Violation(
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
                is_approximate=bool(getattr(v, "is_approximate", False)),
                is_ambiguous=bool(getattr(v, "is_ambiguous", False)),
                # Never pre-accepted. `auto_fix` is a choice made about the
                # upload; a re-analysis is a choice made in the review screen,
                # where the whole point is to look at what came back.
                status="pending",
            ))

        if getattr(analysis, "failed_chunks", None):
            skipped = len(analysis.failed_chunks)
            job.error_message = (
                f"Partial analysis: {skipped} section(s) of the transcript could not be "
                f"analyzed and may contain unflagged content. "
                + " | ".join(analysis.failed_chunks[:3])
            )
            logger.warning(f"Job {job_id} re-analyzed with {skipped} failed chunk(s).")

        # The new suggestions and the question they answer land together.
        job.prompt = prompt
        job.preset = preset
        job.status = "completed"
        db.commit()

        # Every LLM suggestion the old export was rendered from has just been
        # deleted, decisions included, so whatever sits in exports/ describes an
        # edit list that no longer exists.
        exports.invalidate_export(db, job)

        logger.info(f"Job {job_id} re-analyzed: {len(analysis.violations)} suggestion(s).")

    except Exception as e:
        logger.error(f"Re-analysis of job {job_id} failed: {e}", exc_info=True)
        _mark_reanalysis_failed(db, job_id, str(e))
    finally:
        db.close()


def _mark_reanalysis_failed(db, job_id: str, message: str):
    """
    Record a failed re-analysis without marking the job failed.

    The same argument as `_mark_export_failed`: the job is a completed job with
    a reviewed edit list, and a bad LLM response to a second prompt must not
    strand that behind an error screen. The old suggestions are still there -
    the delete only runs once the new analysis has come back - so putting the
    status back to `completed` describes what the reviewer is actually looking
    at. So does `job.prompt`, which the failed run never got as far as writing.
    """
    try:
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            logger.error(f"Re-analysis of job {job_id} failed and its row is gone: {message}")
            return
        job.status = "completed"
        job.error_message = f"Re-analysis failed, the previous suggestions are unchanged: {message}"
        db.commit()
    except Exception:
        logger.exception(f"Could not record the failed re-analysis of job {job_id}")


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

        # A replayed task starts from scratch, so anything a previous attempt
        # managed to write has to go first. Without this, a job interrupted
        # after its suggestions were committed comes back with two copies of
        # every one of them. A first attempt finds nothing to delete.
        removed = (
            db.query(Violation)
            .filter(Violation.job_id == job_id)
            .delete(synchronize_session=False)
        )
        if removed:
            db.commit()
            logger.info(f"Job {job_id} is being re-run; cleared {removed} stale suggestion(s).")

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
            status = "accepted" if _is_pre_accepted(v, job) else "pending"

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
                # The same two flags `_is_pre_accepted` just consulted, kept on
                # the row so the reviewer can see why this one is still pending
                # on a job that asked for everything to be applied.
                is_approximate=bool(getattr(v, "is_approximate", False)),
                is_ambiguous=bool(getattr(v, "is_ambiguous", False)),
                status=status
            )
            db.add(violation)

        # Step 4: Auto-fix if requested (LLM fixes or Scrubber fixes)
        if job.auto_fix or job.auto_scrub:
            job.status = "exporting"
            job.export_status = "exporting"
            db.commit()

            exports.ensure_export_dir()
            export_path = exports.export_path_for(job, file_path_to_use)

            # What gets rendered is exactly what was written as `accepted`
            # above - one predicate, asked twice, so the file on disk cannot
            # disagree with the review screen describing it.
            applied = [v for v in all_suggestions if _is_pre_accepted(v, job)]
            cuts, mutes = exports.partition_edits(applied)
            exports.render_export(file_path_to_use, export_path, cuts, mutes, job.media_type)
            job.export_status = "ready"
            # Nothing has been reviewed yet, so this render matches the edit set
            # exactly - revision 0. The first decision the reviewer makes bumps
            # past it and retires the file.
            job.export_revision = job.edit_revision or 0

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
