"""
Locks in the retention policy the README promises.

The regressions that matter here: retention must stay off unless someone asks
for it, a job still moving through the worker must never have its source
deleted out from under it, and the sweep has to take the export as well as the
upload - files outliving their rows is the whole leak retention exists to fix.

No FFmpeg, no threads: the sweep is called directly with an injected ``now``.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database import SessionLocal, init_db
from app.models import Job, Violation
from app.services import retention


def _epoch_hours_ago(hours: float) -> float:
    """An mtime that many hours in the past, in real epoch seconds."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()


@pytest.fixture
def db():
    init_db()
    session = SessionLocal()
    try:
        session.query(Violation).delete()
        session.query(Job).delete()
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def media_dirs(tmp_path):
    uploads = tmp_path / "uploads"
    exports = tmp_path / "exports"
    uploads.mkdir()
    exports.mkdir()
    return uploads, exports


def _make_job(db, media_dirs, *, age_hours: float, status: str = "completed") -> str:
    uploads, exports = media_dirs
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        filename=f"{job_id}.mp3",
        original_filename="seminar.mp3",
        status=status,
        created_at=datetime.utcnow() - timedelta(hours=age_hours),
    )
    db.add(job)
    db.commit()
    (uploads / f"{job_id}.mp3").write_bytes(b"upload")
    (exports / f"{job_id}_edited.mp3").write_bytes(b"export")
    return job_id


def _purge(db, media_dirs, max_age_hours: float):
    uploads, exports = media_dirs
    return retention.purge_expired(
        db,
        max_age_seconds=max_age_hours * 3600,
        upload_dir=uploads,
        export_dir=exports,
    )


# --- configuration -----------------------------------------------------------


def test_retention_is_off_by_default():
    assert retention.retention_seconds({}) is None


def test_unparseable_retention_fails_open():
    """A typo in .env must not start deleting media on a schedule nobody chose."""
    assert retention.retention_seconds({"RETENTION_HOURS": "twelve"}) is None
    assert retention.retention_seconds({"RETENTION_HOURS": "0"}) is None
    assert retention.retention_seconds({"RETENTION_HOURS": "-4"}) is None


def test_retention_hours_parses():
    assert retention.retention_seconds({"RETENTION_HOURS": "24"}) == 24 * 3600
    assert retention.retention_seconds({"RETENTION_HOURS": " 0.5 "}) == 1800


def test_sweep_interval_defaults_and_overrides():
    assert retention.sweep_interval_seconds({}) == retention.DEFAULT_SWEEP_MINUTES * 60
    assert retention.sweep_interval_seconds({"RETENTION_SWEEP_MINUTES": "5"}) == 300
    assert (
        retention.sweep_interval_seconds({"RETENTION_SWEEP_MINUTES": "nope"})
        == retention.DEFAULT_SWEEP_MINUTES * 60
    )


def test_sweeper_does_not_start_when_disabled():
    assert retention.start_retention_sweeper({}) is None


# --- the sweep ---------------------------------------------------------------


def test_expired_job_and_both_of_its_files_go(db, media_dirs):
    uploads, exports = media_dirs
    job_id = _make_job(db, media_dirs, age_hours=30)

    report = _purge(db, media_dirs, 24)

    assert report.jobs_deleted == 1
    assert report.files_deleted == 2
    assert db.query(Job).filter(Job.id == job_id).first() is None
    assert not (uploads / f"{job_id}.mp3").exists()
    assert not (exports / f"{job_id}_edited.mp3").exists()


def test_fresh_job_is_untouched(db, media_dirs):
    uploads, _ = media_dirs
    job_id = _make_job(db, media_dirs, age_hours=1)

    report = _purge(db, media_dirs, 24)

    assert report == retention.PurgeReport(0, 0, 0)
    assert db.query(Job).filter(Job.id == job_id).first() is not None
    assert (uploads / f"{job_id}.mp3").exists()


@pytest.mark.parametrize(
    "status", ["pending", "converting", "transcribing", "analyzing", "exporting"]
)
def test_in_flight_job_survives_its_own_expiry(db, media_dirs, status):
    """
    The worker is sequential, so a job can be queued behind a long one for
    longer than the retention window and still be alive. Deleting its source
    mid-pipeline fails the job for a reason that looks like a bug.
    """
    uploads, _ = media_dirs
    job_id = _make_job(db, media_dirs, age_hours=30, status=status)

    report = _purge(db, media_dirs, 24)

    assert report.jobs_deleted == 0
    assert report.skipped_in_flight == 1
    assert db.query(Job).filter(Job.id == job_id).first() is not None
    assert (uploads / f"{job_id}.mp3").exists()


@pytest.mark.parametrize("export_status", ["queued", "exporting"])
def test_a_render_in_flight_keeps_a_completed_job(db, media_dirs, export_status):
    """
    `job.status` goes back to `completed` the moment analysis finishes, so it
    says nothing about a render queued behind it. Sweeping on that alone deleted
    the source from under FFmpeg and raced the worker to `exports/` - the job
    was being actively used at the moment it was collected as abandoned.
    """
    uploads, _ = media_dirs
    job_id = _make_job(db, media_dirs, age_hours=30, status="completed")
    db.query(Job).filter(Job.id == job_id).first().export_status = export_status
    db.commit()

    report = _purge(db, media_dirs, 24)

    assert report.jobs_deleted == 0
    assert report.skipped_in_flight == 1
    assert db.query(Job).filter(Job.id == job_id).first() is not None
    assert (uploads / f"{job_id}.mp3").exists()


@pytest.mark.parametrize("export_status", ["none", "ready", "failed", None])
def test_a_settled_export_does_not_hold_a_job_open(db, media_dirs, export_status):
    """
    The counterpart: `ready` and `failed` are finished renders, and a job that
    never exported at all must not become immortal. Retention that quietly stops
    collecting is the same broken promise as retention that collects too eagerly.
    """
    job_id = _make_job(db, media_dirs, age_hours=30, status="completed")
    db.query(Job).filter(Job.id == job_id).first().export_status = export_status
    db.commit()

    assert _purge(db, media_dirs, 24).jobs_deleted == 1
    assert db.query(Job).filter(Job.id == job_id).first() is None


def test_failed_jobs_are_collectable(db, media_dirs):
    job_id = _make_job(db, media_dirs, age_hours=30, status="failed")

    assert _purge(db, media_dirs, 24).jobs_deleted == 1
    assert db.query(Job).filter(Job.id == job_id).first() is None


def test_violations_go_with_the_job(db, media_dirs):
    job_id = _make_job(db, media_dirs, age_hours=30)
    db.add(Violation(job_id=job_id, text="um", start_time=1.0, end_time=1.2))
    db.commit()

    _purge(db, media_dirs, 24)

    assert db.query(Violation).filter(Violation.job_id == job_id).count() == 0


def test_orphaned_files_are_swept(db, media_dirs):
    """
    Files outlive rows - a crashed upload, or /api/admin/reset-database run
    without the matching storage wipe. Nothing will ever reference these again.
    """
    uploads, exports = media_dirs
    orphan_id = str(uuid.uuid4())
    stale_upload = uploads / f"{orphan_id}.mp3"
    stale_export = exports / f"{orphan_id}_edited.mp3"
    stale_upload.write_bytes(b"x")
    stale_export.write_bytes(b"x")
    old = _epoch_hours_ago(30)
    for path in (stale_upload, stale_export):
        os.utime(path, (old, old))

    report = _purge(db, media_dirs, 24)

    assert report.files_deleted == 2
    assert not stale_upload.exists()
    assert not stale_export.exists()


def test_recent_orphan_stays(db, media_dirs):
    """An upload written seconds ago has no row yet - that is not a leak."""
    uploads, _ = media_dirs
    in_progress = uploads / f"{uuid.uuid4()}.mp3"
    in_progress.write_bytes(b"x")

    assert _purge(db, media_dirs, 24).files_deleted == 0
    assert in_progress.exists()


def test_gitkeep_survives(db, media_dirs):
    """The directories are tracked by a dotfile; sweeping it breaks a fresh clone."""
    uploads, _ = media_dirs
    keep = uploads / ".gitkeep"
    keep.write_bytes(b"")
    old = _epoch_hours_ago(24 * 400)
    os.utime(keep, (old, old))

    _purge(db, media_dirs, 24)

    assert keep.exists()


def test_live_job_files_are_not_treated_as_orphans(db, media_dirs):
    """The orphan pass must key off the row, not the file's age."""
    uploads, _ = media_dirs
    job_id = _make_job(db, media_dirs, age_hours=30, status="transcribing")
    old = _epoch_hours_ago(30)
    os.utime(uploads / f"{job_id}.mp3", (old, old))

    _purge(db, media_dirs, 24)

    assert (uploads / f"{job_id}.mp3").exists()


# --- the shared file-deletion helper ----------------------------------------


def test_delete_job_files_takes_the_export_too(media_dirs):
    """
    DELETE /api/jobs/{id} used to walk a hardcoded extension list and stop at
    the upload, leaving the export behind with nothing to explain it.
    """
    uploads, exports = media_dirs
    job_id = str(uuid.uuid4())
    (uploads / f"{job_id}.mov").write_bytes(b"x")
    (exports / f"{job_id}_edited.mov").write_bytes(b"x")

    assert retention.delete_job_files(job_id, uploads, exports) == 2
    assert list(uploads.iterdir()) == []
    assert list(exports.iterdir()) == []


def test_delete_job_files_is_quiet_when_there_is_nothing(media_dirs):
    uploads, exports = media_dirs
    assert retention.delete_job_files(str(uuid.uuid4()), uploads, exports) == 0


def test_delete_job_files_leaves_other_jobs_alone(media_dirs):
    uploads, exports = media_dirs
    mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())
    (uploads / f"{mine}.mp3").write_bytes(b"x")
    (uploads / f"{theirs}.mp3").write_bytes(b"x")

    retention.delete_job_files(mine, uploads, exports)

    assert (uploads / f"{theirs}.mp3").exists()


def test_job_id_recovered_from_either_filename():
    job_id = str(uuid.uuid4())
    assert retention._job_id_from_filename(Path(f"{job_id}.mp3")) == job_id
    assert retention._job_id_from_filename(Path(f"{job_id}_edited.mp4")) == job_id
