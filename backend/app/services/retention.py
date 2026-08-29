"""
Time-based retention - delete old jobs and their media.

The README promises that uploads and exports stay on local disk and can be
wiped; on a shared or deployed instance "can be wiped" has to mean "is wiped,
without anyone remembering to". Retention is off by default because on a laptop
the recordings are the user's own and deleting them by surprise is worse than
keeping them.

Kept free of FastAPI imports so a sweep can be exercised directly in tests.
"""

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping

from ..database import SessionLocal
from ..models import Job

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"

DEFAULT_SWEEP_MINUTES = 15.0

# A job that is not in one of these states is still moving through the worker.
# Age alone does not make it collectable: the pipeline is sequential, so a job
# can sit queued behind a long one for longer than the retention window and
# still be perfectly alive. Deleting the source out from under the transcriber
# would fail the job for a reason that looks like a bug.
TERMINAL_STATUSES = frozenset({"completed", "failed"})

# A completed job can still have work in flight. `job.status` goes back to
# `completed` the moment analysis finishes, so it says nothing about a render
# queued or running behind it - and a render is exactly the operation that
# reads the source media and writes into `exports/`. Sweeping one mid-flight
# deletes the input under FFmpeg and then races the worker to the output
# directory, which is how a job that was actively being used ends as a failed
# export with no file and no row to explain it.
ACTIVE_EXPORT_STATUSES = frozenset({"queued", "exporting"})


def is_in_flight(job) -> bool:
    """
    Whether a job is still being worked on, and so not collectable by age.

    Two questions, because a job has two pipelines: `status` for the analysis
    side and `export_status` for the render. Either one moving is enough.
    """
    if job.status not in TERMINAL_STATUSES:
        return True
    return (job.export_status or "none") in ACTIVE_EXPORT_STATUSES


@dataclass(frozen=True)
class PurgeReport:
    """What one sweep did. Returned for logging and for assertions in tests."""

    jobs_deleted: int = 0
    files_deleted: int = 0
    skipped_in_flight: int = 0

    @property
    def did_something(self) -> bool:
        return bool(self.jobs_deleted or self.files_deleted)


def retention_seconds(env: Mapping[str, str] | None = None) -> float | None:
    """
    Maximum age of a job, from ``RETENTION_HOURS``.

    ``None`` means keep everything forever - the default, and also where an
    unparseable value lands. A typo in `.env` must not start deleting media on a
    schedule nobody intended; failing open here is the safe direction, which is
    the opposite of the choice ``limits.py`` makes for the upload caps.
    """
    env = os.environ if env is None else env
    raw = (env.get("RETENTION_HOURS") or "").strip()
    if not raw:
        return None
    try:
        hours = float(raw)
    except ValueError:
        logger.warning(f"RETENTION_HOURS={raw!r} is not a number; retention stays off.")
        return None
    if hours <= 0:
        return None
    return hours * 3600


def sweep_interval_seconds(env: Mapping[str, str] | None = None) -> float:
    """How often the sweeper runs, from ``RETENTION_SWEEP_MINUTES``."""
    env = os.environ if env is None else env
    raw = (env.get("RETENTION_SWEEP_MINUTES") or "").strip()
    try:
        minutes = float(raw) if raw else DEFAULT_SWEEP_MINUTES
    except ValueError:
        minutes = DEFAULT_SWEEP_MINUTES
    if minutes <= 0:
        minutes = DEFAULT_SWEEP_MINUTES
    return minutes * 60


def job_files(
    job_id: str,
    upload_dir: Path = UPLOAD_DIR,
    export_dir: Path = EXPORT_DIR,
) -> Iterator[Path]:
    """
    Every file on disk belonging to a job: the upload and any export.

    Globbed rather than reconstructed from a list of extensions, so a container
    the upload validator learns about later cannot silently escape deletion.
    """
    yield from sorted(upload_dir.glob(f"{job_id}.*"))
    yield from sorted(export_dir.glob(f"{job_id}_edited.*"))


def delete_job_files(
    job_id: str,
    upload_dir: Path = UPLOAD_DIR,
    export_dir: Path = EXPORT_DIR,
) -> int:
    """Remove a job's media. Returns the number of files actually unlinked."""
    removed = 0
    for path in job_files(job_id, upload_dir, export_dir):
        try:
            path.unlink()
            removed += 1
        except OSError:
            # A file that is gone, locked, or on a read-only mount is not worth
            # aborting the sweep for - the next pass will try again.
            logger.exception(f"Could not delete {path}")
    return removed


def _job_id_from_filename(path: Path) -> str:
    """``<uuid>.mp3`` and ``<uuid>_edited.mp4`` both map back to ``<uuid>``."""
    return path.name.split(".", 1)[0].removesuffix("_edited")


def purge_expired(
    db,
    max_age_seconds: float,
    now: datetime | None = None,
    upload_dir: Path = UPLOAD_DIR,
    export_dir: Path = EXPORT_DIR,
) -> PurgeReport:
    """
    Delete finished jobs older than ``max_age_seconds``, plus orphaned media.

    "Finished" is :func:`is_in_flight` - both pipelines idle, not just the
    analysis one.

    ``now`` is injectable so tests can age a job without sleeping. It is naive
    UTC to match ``Job.created_at``, which is written by ``datetime.utcnow``.

    The orphan pass exists because files outlive rows: a crashed upload, a
    row deleted by ``/api/admin/reset-database`` without the matching storage
    wipe, or an export written for a job that was deleted mid-render. Those are
    the leaks a retention promise is actually about.
    """
    now = datetime.utcnow() if now is None else now
    cutoff = now - timedelta(seconds=max_age_seconds)
    # The same cutoff as an epoch second, for comparing against st_mtime.
    # `cutoff` is naive UTC (it has to be, to compare with Job.created_at), and
    # a naive datetime's .timestamp() would read it as *local* time - which
    # silently moves the file cutoff by the machine's UTC offset.
    cutoff_epoch = cutoff.replace(tzinfo=timezone.utc).timestamp()

    jobs_deleted = 0
    files_deleted = 0
    skipped = 0

    for job in db.query(Job).filter(Job.created_at < cutoff).all():
        if is_in_flight(job):
            skipped += 1
            continue
        files_deleted += delete_job_files(job.id, upload_dir, export_dir)
        db.delete(job)  # cascades to violations
        jobs_deleted += 1

    db.commit()

    live_ids = {row[0] for row in db.query(Job.id).all()}
    for directory in (upload_dir, export_dir):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if _job_id_from_filename(path) in live_ids:
                continue
            try:
                # mtime, not the job's created_at - there is no row to ask.
                if path.stat().st_mtime >= cutoff_epoch:
                    continue
                path.unlink()
                files_deleted += 1
            except OSError:
                logger.exception(f"Could not delete orphaned file {path}")

    report = PurgeReport(jobs_deleted, files_deleted, skipped)
    if report.did_something or skipped:
        logger.info(
            f"Retention sweep: deleted {report.jobs_deleted} job(s) and "
            f"{report.files_deleted} file(s), skipped {skipped} still in flight."
        )
    return report


def run_sweep(max_age_seconds: float) -> PurgeReport:
    """One sweep against the real database, with its own short-lived session."""
    db = SessionLocal()
    try:
        return purge_expired(db, max_age_seconds)
    finally:
        db.close()


_stop_sweeping = threading.Event()


def _sweep_loop(max_age_seconds: float, interval_seconds: float) -> None:
    while True:
        try:
            run_sweep(max_age_seconds)
        except Exception:
            # A sweep that raises must not kill the thread; the next interval
            # gets another attempt, exactly like the worker loop.
            logger.exception("Retention sweep failed")
        if _stop_sweeping.wait(interval_seconds):
            return


def start_retention_sweeper(env: Mapping[str, str] | None = None) -> threading.Thread | None:
    """
    Start the background sweeper, or don't when retention is off.

    Returns the thread so a caller can join it in a test; ``None`` when
    ``RETENTION_HOURS`` is unset, which is the default and means keep forever.
    The first sweep runs immediately rather than after one interval, so a
    restart is enough to collect whatever expired while the server was down.
    """
    max_age = retention_seconds(env)
    if max_age is None:
        logger.info("RETENTION_HOURS is unset; uploads and exports are kept indefinitely.")
        return None

    interval = sweep_interval_seconds(env)
    _stop_sweeping.clear()
    thread = threading.Thread(
        target=_sweep_loop, args=(max_age, interval), daemon=True, name="retention-sweeper"
    )
    thread.start()
    logger.info(
        f"Retention on: jobs older than {max_age / 3600:.1f}h are deleted, "
        f"swept every {interval / 60:.0f} min."
    )
    return thread


def stop_retention_sweeper() -> None:
    """Ask the sweeper to exit at its next wake-up."""
    _stop_sweeping.set()
