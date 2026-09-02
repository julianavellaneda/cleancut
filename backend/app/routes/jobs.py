"""
Job routes - upload, list, and status endpoints.
"""

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, or_
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
from ..models import Job, Violation
from ..schemas import (
    ActiveJobResponse,
    JobResponse,
    JobListResponse,
    PresetResponse,
    ReanalyzeRequest,
    ReanalyzeResponse,
    TranscriptResponse,
    TranscriptSegment,
)
from ..services.processor import PRESETS, is_valid_preset
from ..services.retention import delete_job_files, is_in_flight
from ..services import transcripts
from ..services import task_store
from ..services.worker import enqueue_job, enqueue_reanalysis, publish

router = APIRouter()

# Directories. The export directory is `services.exports`'s to own and to
# create; this route only ever asks it to delete.
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


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

    # The duration and the task row commit together, and the task is published
    # only once that commit has returned. Both halves matter: this handler used
    # to commit the job `pending` and *then* open a second session for the task
    # row, so a failure in between answered 500 while leaving a job that no
    # worker would ever pick up and no restart would ever recover - permanently
    # `pending`, with nothing on the books to explain it.
    job.duration_seconds = duration
    task = enqueue_job(job_id, str(file_path), db=db)
    db.commit()
    publish(task)

    # Return immediately with pending status
    return _build_job_response(job, db)


#: How many jobs one page of the list returns by default, and the most it will
#: return however large a `limit` is asked for. The cap is the part that
#: matters: without it a client picks the size of the query, and the endpoint
#: the home page calls on a timer is not the place to allow that.
DEFAULT_JOB_PAGE = 50
MAX_JOB_PAGE = 200


@router.get("", response_model=List[JobListResponse])
def list_jobs(
    limit: int = Query(DEFAULT_JOB_PAGE, ge=1, le=MAX_JOB_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    List jobs, newest first, one bounded page at a time.

    `len(job.violations)` used to make this one SELECT per job on top of the
    list query - and each of those SELECTs loaded every column of every
    suggestion to arrive at a number. A job with 400 suggestions pulled 400 rows
    of quoted text and reasoning across the wire so the card could print "400".
    One grouped COUNT answers the page instead: two queries, no row bodies, and
    the count computed by SQLite rather than by Python.

    The page bound is the other half of that. Retention is off unless
    `RETENTION_HOURS` is set, so on a default install this table only grows, and
    an unbounded `SELECT *` over it was the response the home page fetched every
    three seconds. The aggregate is now scoped to the ids on this page rather
    than grouping the whole table, so neither query's cost depends on how long
    the install has been running.

    A job with no suggestions has no row in the aggregate, so the lookup
    defaults to 0 rather than assuming every job id appears.
    """
    jobs = (
        db.query(Job)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    counts = _violation_counts(db, [job.id for job in jobs])
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
            violation_count=counts.get(job.id, 0)
        )
        for job in jobs
    ]


def _violation_counts(db: Session, job_ids: List[str]) -> dict:
    """
    How many suggestions each of these jobs has, in one grouped COUNT.

    Scoped to the ids asked about rather than grouping the whole table: both
    callers are polled on a timer, and the work of answering them should depend
    on the size of the page, not on the size of the history.
    """
    if not job_ids:
        return {}
    return dict(
        db.query(Violation.job_id, func.count(Violation.id))
        .filter(Violation.job_id.in_(job_ids))
        .group_by(Violation.job_id)
        .all()
    )


# The statuses that mean a job still owes an answer. Kept here rather than
# imported from the worker so the route does not depend on the worker module
# just to name four strings; `retention.TERMINAL_STATUSES` is the other side of
# the same fact.
ACTIVE_JOB_STATUSES = ("pending", "converting", "transcribing", "analyzing", "exporting")
ACTIVE_EXPORT_STATUSES = ("queued", "exporting")


@router.get("/active", response_model=List[ActiveJobResponse])
def list_active_jobs(db: Session = Depends(get_db)):
    """
    The jobs still being worked on, and nothing else.

    What the home page's timer should ask for. It used to poll `GET /api/jobs`,
    re-fetching every job in the entire history - filename, prompt, preset,
    timestamps and all - every three seconds, to notice that one of them had
    moved from `transcribing` to `analyzing`. Everything but the status is
    immutable while a job runs, so re-sending it is pure waste, and the waste
    grew with the table.

    Both pipelines are asked about, for the same reason the retention sweeper
    asks about both: `status` returns to `completed` the moment analysis
    finishes and says nothing about a render queued behind it, so polling on
    `status` alone would stop the timer while an export was still going.

    Declared before `/{job_id}`, or the path-param route shadows it - the same
    trap `/presets` sits above.
    """
    jobs = (
        db.query(Job)
        .filter(
            or_(
                Job.status.in_(ACTIVE_JOB_STATUSES),
                Job.export_status.in_(ACTIVE_EXPORT_STATUSES),
            )
        )
        .order_by(Job.created_at.desc())
        .all()
    )
    counts = _violation_counts(db, [job.id for job in jobs])
    return [
        ActiveJobResponse(
            id=job.id,
            status=job.status,
            export_status=job.export_status or "none",
            violation_count=counts.get(job.id, 0),
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


@router.post("/{job_id}/reanalyze", response_model=ReanalyzeResponse, status_code=202)
def reanalyze_job(job_id: str, request: ReanalyzeRequest, db: Session = Depends(get_db)):
    """
    Ask a different question about a transcript that has already been made.

    This is the whole return on persisting the transcript: transcription is the
    slowest stage of the job and a new prompt has nothing to do with it, so a
    re-run reads the stored words instead of putting the audio back through
    Whisper.

    Validated here, queued for the worker, answered 202 - the same shape as
    export, and polled the same way through `status`. Refused when the job has
    no stored transcript (409 rather than 404: the job is real, it simply
    predates the column or never got that far) and when it is still in the
    pipeline, since the run in flight would overwrite whatever this one wrote.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is still {job.status}; wait for it to finish before re-analyzing.",
        )

    if transcripts.from_json(job.transcript) is None:
        raise HTTPException(
            status_code=409,
            detail="This job has no stored transcript to re-analyze.",
        )

    preset = request.preset or None
    if not is_valid_preset(preset):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{preset}'. Available: {', '.join(PRESETS)}",
        )

    prompt = (request.prompt or "").strip() or None
    if not prompt and not preset:
        raise HTTPException(
            status_code=400,
            detail="Re-analysis needs a prompt or a preset.",
        )

    # `status` moves now, so the frontend's existing poll picks the re-run up
    # immediately. The prompt does not: the review screen labels the suggestion
    # list with `job.prompt`, and until the new suggestions exist that list is
    # still the answer to the old question. The worker writes both together
    # when the analysis comes back, so a failed run leaves nothing to undo.
    # A preset replaces a prompt and vice versa, since the analyzer runs in one
    # mode or the other; that swap happens there too.
    job.status = "analyzing"
    try:
        task = enqueue_reanalysis(job_id, prompt=prompt, preset=preset, db=db)
    except task_store.DuplicateTask:
        # Two re-runs asked for at once. The status check above catches the
        # ordinary case; this catches the pair that passed it together.
        raise HTTPException(
            status_code=409,
            detail="A re-analysis is already queued for this job.",
        )
    db.commit()
    publish(task)

    return ReanalyzeResponse(job_id=job_id, prompt=prompt, preset=preset)


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

    Refused with a **409** while the job is still being worked on. Deleting had
    no coordination with the worker at all: FFmpeg could write an export
    *after* ``delete_job_files`` had already scanned the directory, leaving
    media on disk with no job to explain it. The retention sweeper collects
    exactly that orphan - but retention is off unless ``RETENTION_HOURS`` is
    set, so on a default install the file simply stayed, forever, after a
    delete the user was told had succeeded.

    ``retention.is_in_flight`` is the same helper the sweeper uses to decide a
    job is too busy to collect, asked here for the same reason: it covers both
    pipelines, and `status` alone says nothing about a render queued behind a
    completed analysis. The worker re-checks that the job still exists before
    publishing a render, which closes the narrower race where a job finishes
    between this check and the delete.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if is_in_flight(job):
        stage = job.status if job.status not in ("completed", "failed") else "exporting"
        raise HTTPException(
            status_code=409,
            detail=(
                f"This job is still {stage}. Wait for it to finish before deleting it."
            ),
        )

    delete_job_files(job_id, UPLOAD_DIR)

    # Delete job (cascades to violations)
    db.delete(job)
    db.commit()

    return {"message": "Job deleted"}


def _build_job_response(job: Job, db: Session) -> JobResponse:
    """
    Build JobResponse with violation counts.

    The export fields are carried explicitly. This response is assembled field by
    field rather than from the ORM object, so a column the worker writes but this
    function forgets does not surface as a stale value - it surfaces as the
    schema default. That is what happened to `export_status`: the poll that drives
    the export button read "none" forever, so a queued render never became
    "Exporting..." and a finished one never became a download.

    `or "none"` covers rows migrated in before the column existed, which are NULL
    rather than 'none' until something writes them.

    The four counts come from one grouped COUNT rather than from
    `job.violations`. The review page polls this endpoint for the whole time a
    job is open, and loading the relationship pulled every suggestion's text and
    reasoning on every poll purely to length-check the list. `status` is the only
    column any of the four counts reads, and SQLite can count faster than we can
    materialize ORM objects to do it.
    """
    by_status = dict(
        db.query(Violation.status, func.count(Violation.id))
        .filter(Violation.job_id == job.id)
        .group_by(Violation.status)
        .all()
    )
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
        export_status=job.export_status or "none",
        export_error=job.export_error,
        edit_revision=job.edit_revision or 0,
        export_revision=job.export_revision,
        violation_count=sum(by_status.values()),
        pending_count=by_status.get("pending", 0),
        accepted_count=by_status.get("accepted", 0),
        rejected_count=by_status.get("rejected", 0)
    )
