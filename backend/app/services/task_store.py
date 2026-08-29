"""
The durable half of the job queue.

`queue.Queue` is the fast half: it is what the worker thread actually blocks
on. This module is the record of the same thing on disk, so that "what work is
outstanding" survives the process that was going to do it. Every enqueue writes
a row here first and puts on the queue second - in that order, so a crash in
between leaves a task that gets replayed rather than one that was promised to
an HTTP caller and then quietly dropped.

Row-level only, on purpose. What to *do* about an interrupted task - replay it,
abandon it, mark the job failed - is policy, and it lives in `worker.py` next
to the pipelines it is deciding about.

Each call takes its own short-lived session rather than a caller's: an enqueue
happens inside a request whose transaction may still roll back, and a task
record that disappears with the request would put the durable copy *behind* the
in-memory one, which is the failure this module exists to prevent.
"""

import logging
from dataclasses import dataclass, replace
from datetime import datetime

from ..database import SessionLocal
from ..models import Task

logger = logging.getLogger(__name__)

# How many times a task may be picked up before it is abandoned. A task is only
# ever picked up twice if the first attempt took the whole process down with
# it, so this is not a retry policy for ordinary failures (those are caught and
# recorded on the job); it is the stop on a crash loop, where an unreadable file
# would otherwise kill the server on every boot for the rest of time.
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class QueuedTask:
    """
    One unit of background work, as the worker thread sees it.

    A named record rather than a positional tuple: the queue carries three
    kinds of work, and "which element was the file path again" is not a
    question worth re-answering at every unpack site.

    `task_id` points at the durable row this came from. It is optional so a
    test can drive the worker body directly, but everything the app enqueues
    has one.
    """

    kind: str  # "process", "export" or "reanalyze"
    job_id: str
    file_path: str | None = None
    edit_action: str | None = None
    # The question a re-analysis is being asked. Carried on the task rather
    # than read back off the job, so `jobs.prompt` can stay describing the
    # suggestions that are actually on screen until the new ones replace them.
    prompt: str | None = None
    preset: str | None = None
    task_id: str | None = None


def to_task(row: Task) -> QueuedTask:
    """The in-memory task a stored row describes."""
    return QueuedTask(
        kind=row.kind,
        job_id=row.job_id,
        file_path=row.file_path,
        edit_action=row.edit_action,
        prompt=row.prompt,
        preset=row.preset,
        task_id=row.id,
    )


def record(task: QueuedTask) -> QueuedTask:
    """
    Persist a task and return it carrying the id of its row.

    A failure to write is *not* swallowed. Losing the row would leave the queue
    holding work with no durable record - exactly the state this replaces - and
    the caller (an upload, an export request) would rather answer 500 than
    accept work it cannot promise to keep.
    """
    db = SessionLocal()
    try:
        row = Task(
            kind=task.kind,
            job_id=task.job_id,
            file_path=task.file_path,
            edit_action=task.edit_action,
            prompt=task.prompt,
            preset=task.preset,
            state="pending",
            attempts=0,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        return replace(task, task_id=row.id)
    finally:
        db.close()


def begin(task: QueuedTask) -> None:
    """
    Mark a task as being worked on, and count the attempt.

    The count goes up *before* the work runs, not after it succeeds: the whole
    point is to notice a task that never comes back.

    Bookkeeping failures here are logged and swallowed. A database hiccup
    updating a counter must not stop the job the counter is about.
    """
    if task.task_id is None:
        return
    db = SessionLocal()
    try:
        row = db.query(Task).filter(Task.id == task.task_id).first()
        if row is None:
            return
        row.state = "running"
        row.attempts = (row.attempts or 0) + 1
        db.commit()
    except Exception:
        logger.exception(f"Could not mark task {task.task_id} as running")
    finally:
        db.close()


def finish(task: QueuedTask) -> None:
    """
    Drop a task's row once the worker is done with it.

    Deleted whether the handler succeeded or raised. A handler that fails has
    already recorded why on the job itself; replaying it on the next boot would
    re-run a pipeline that is expected to fail again, and hide the recorded
    reason behind a fresh one.
    """
    if task.task_id is None:
        return
    db = SessionLocal()
    try:
        db.query(Task).filter(Task.id == task.task_id).delete()
        db.commit()
    except Exception:
        logger.exception(f"Could not clear task {task.task_id}")
    finally:
        db.close()


def outstanding(db) -> list[Task]:
    """
    Every task still on the books, oldest first.

    `pending` and `running` are both outstanding after a restart: a row left
    `running` belongs to a worker thread that no longer exists, so it is work
    that was interrupted, not work in progress.
    """
    return (
        db.query(Task)
        .order_by(Task.created_at, Task.id)
        .all()
    )


def outstanding_kinds_by_job(db) -> dict[str, set[str]]:
    """
    Which kinds of work are on the books, grouped by job.

    One query for the whole reconciliation pass rather than one per job: this
    runs at startup, where the alternative is a SELECT per row in the jobs
    table before the server will answer anything.
    """
    kinds: dict[str, set[str]] = {}
    for job_id, kind in db.query(Task.job_id, Task.kind).all():
        kinds.setdefault(job_id, set()).add(kind)
    return kinds


def has_outstanding(db, job_id: str, kind: str) -> bool:
    """Whether a task of this kind is already queued or running for a job."""
    return (
        db.query(Task.id)
        .filter(Task.job_id == job_id, Task.kind == kind)
        .first()
        is not None
    )
