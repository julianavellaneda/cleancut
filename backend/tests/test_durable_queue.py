"""
Tests for the durable job queue and the startup reconciliation.

The bug: the queue was a `queue.Queue` in one process, so a restart threw away
every task that had been accepted and not yet run. The upload had answered 202,
the row said `pending`, and nothing was ever going to move it again.

What is under test here is the record that survives the process - a `tasks`
row written before the in-memory put and deleted after the work - and what the
next boot does with whatever it finds:

* a task still on the books is replayed, in its original order;
* a task that has already burned through `MAX_ATTEMPTS` is abandoned, with the
  reason recorded on the job rather than replayed into another crash;
* a task whose job is gone is dropped;
* a job whose *status* claims it is mid-flight with no task to explain it is
  reconciled - re-queued when re-running it is safe, failed with an actionable
  message when it is not.
"""

import uuid
from datetime import datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database
import app.services.exports as exports
import app.services.task_store as task_store
import app.services.worker as worker
from app.analysis.prompt_analyzer import AnalysisResult, Violation
from app.analysis.transcriber import Segment, TranscriptResult
from app.models import Job, Task, Violation as ViolationRow
from app.services import transcripts
from app.services.task_store import QueuedTask

# The session factory the helpers below use. Rebound per test by `isolated_db`.
SessionLocal = None


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """
    A database of this module's own.

    Recovery is a *global* pass - it asks what the whole table is missing - so
    it cannot be asserted against the shared file every other module writes
    into. `worker` and `task_store` bind `SessionLocal` at import, so both have
    to be repointed by name; patching `database` alone would leave them talking
    to the old engine.
    """
    global SessionLocal
    engine = create_engine(
        f"sqlite:///{tmp_path / 'queue.db'}", connect_args={"check_same_thread": False}
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    monkeypatch.setattr(worker, "SessionLocal", Session)
    monkeypatch.setattr(task_store, "SessionLocal", Session)
    database.Base.metadata.create_all(bind=engine)
    SessionLocal = Session
    yield
    SessionLocal = None


@pytest.fixture(autouse=True)
def empty_queue():
    """Every test starts with an empty queue and leaves one behind."""
    _drain()
    yield
    _drain()


def _drain():
    drained = []
    while not worker.job_queue.empty():
        drained.append(worker.job_queue.get_nowait())
        worker.job_queue.task_done()
    return drained


def _make_job(**fields):
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Job(id=job_id, filename=f"{job_id}.mp3", **fields))
        db.commit()
    finally:
        db.close()
    return job_id


def _tasks(job_id=None):
    db = SessionLocal()
    try:
        q = db.query(Task)
        if job_id:
            q = q.filter(Task.job_id == job_id)
        return q.order_by(Task.created_at, Task.id).all()
    finally:
        db.close()


def _job(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first()
    finally:
        db.close()


def _add_task(job_id, kind, attempts=0, age_seconds=0, **fields):
    """Write a task row directly - what the last process would have left."""
    db = SessionLocal()
    try:
        row = Task(
            kind=kind,
            job_id=job_id,
            state="running" if attempts else "pending",
            attempts=attempts,
            created_at=datetime.utcnow() - timedelta(seconds=age_seconds),
            **fields,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


# --- The record itself -------------------------------------------------------


def test_enqueueing_a_job_writes_a_durable_row():
    job_id = _make_job(status="pending")

    worker.enqueue_job(job_id, "/tmp/whatever.mp3")

    rows = _tasks(job_id)
    assert len(rows) == 1
    assert rows[0].kind == "process"
    assert rows[0].file_path == "/tmp/whatever.mp3"
    assert rows[0].state == "pending"
    assert rows[0].attempts == 0


def test_an_export_records_its_action_override():
    """`edit_action` exists nowhere else, so a replay has to read it back."""
    job_id = _make_job(status="completed")

    worker.enqueue_export(job_id, "mute")

    row = _tasks(job_id)[0]
    assert (row.kind, row.edit_action) == ("export", "mute")


def test_a_reanalysis_records_the_new_question():
    job_id = _make_job(status="analyzing")

    worker.enqueue_reanalysis(job_id, prompt="find the fillers", preset=None)

    row = _tasks(job_id)[0]
    assert (row.kind, row.prompt, row.preset) == ("reanalyze", "find the fillers", None)


def test_the_queued_task_carries_the_row_it_came_from():
    job_id = _make_job(status="pending")

    worker.enqueue_job(job_id, "/tmp/whatever.mp3")

    queued = _drain()
    assert [t.task_id for t in queued] == [_tasks(job_id)[0].id]


def test_running_a_task_counts_the_attempt_then_clears_the_row(monkeypatch):
    job_id = _make_job(status="pending")
    worker.enqueue_job(job_id, "/tmp/whatever.mp3")
    task = _drain()[0]

    seen = {}

    def _spy(t):
        # Mid-flight the row is claimed, not deleted: this is what a crash
        # would leave behind for the next boot to find.
        row = _tasks(job_id)[0]
        seen["state"] = row.state
        seen["attempts"] = row.attempts

    monkeypatch.setattr(worker, "_dispatch", _spy)
    worker._run_task(task)

    assert seen == {"state": "running", "attempts": 1}
    assert _tasks(job_id) == []


def test_a_failing_task_is_still_retired(monkeypatch):
    """
    A handler that raises has already recorded why on the job. Replaying it
    would re-run a pipeline expected to fail again and overwrite that reason.
    """
    job_id = _make_job(status="pending")
    worker.enqueue_job(job_id, "/tmp/whatever.mp3")
    task = _drain()[0]

    def _boom(t):
        raise RuntimeError("ffmpeg is on fire")

    monkeypatch.setattr(worker, "_dispatch", _boom)
    worker._run_task(task)

    assert _tasks(job_id) == []


# --- Recovery ----------------------------------------------------------------


def test_an_interrupted_task_is_replayed_with_its_arguments():
    job_id = _make_job(status="transcribing")
    _add_task(job_id, "process", attempts=1, file_path="/tmp/interrupted.mp3")

    report = worker.recover_interrupted_work()

    assert report.replayed == 1
    task = _drain()[0]
    assert (task.kind, task.job_id, task.file_path) == (
        "process", job_id, "/tmp/interrupted.mp3",
    )
    # Still on the books - it is outstanding again, not done.
    assert _tasks(job_id)[0].state == "pending"


def test_replay_keeps_the_order_the_queue_had():
    first = _make_job(status="pending")
    second = _make_job(status="pending")
    _add_task(first, "process", age_seconds=60, file_path="/tmp/a.mp3")
    _add_task(second, "process", age_seconds=30, file_path="/tmp/b.mp3")

    worker.recover_interrupted_work()

    assert [t.job_id for t in _drain()] == [first, second]


def test_a_task_that_has_used_up_its_attempts_is_abandoned():
    """
    Otherwise one unreadable upload is a permanent crash loop: it kills the
    process, comes back on the next boot, and kills it again.
    """
    job_id = _make_job(status="transcribing")
    _add_task(job_id, "process", attempts=worker.MAX_ATTEMPTS, file_path="/tmp/poison.mp3")

    report = worker.recover_interrupted_work()

    assert (report.replayed, report.abandoned) == (0, 1)
    assert _drain() == []
    assert _tasks(job_id) == []
    job = _job(job_id)
    assert job.status == "failed"
    assert "abandoned" in job.error_message


def test_an_abandoned_export_leaves_the_reviewed_job_alone():
    """The same split as every other export failure: the review survives it."""
    job_id = _make_job(status="completed", export_status="exporting")
    _add_task(job_id, "export", attempts=worker.MAX_ATTEMPTS)

    worker.recover_interrupted_work()

    job = _job(job_id)
    assert job.status == "completed"
    assert job.export_status == "failed"
    assert "abandoned" in job.export_error


def test_an_abandoned_reanalysis_leaves_the_job_completed():
    job_id = _make_job(status="analyzing")
    _add_task(job_id, "reanalyze", attempts=worker.MAX_ATTEMPTS, prompt="x")

    worker.recover_interrupted_work()

    job = _job(job_id)
    assert job.status == "completed"
    assert "Re-analysis" in job.error_message


def test_a_task_whose_job_is_gone_is_dropped():
    orphan = _add_task(str(uuid.uuid4()), "process", file_path="/tmp/ghost.mp3")

    report = worker.recover_interrupted_work()

    assert report.dropped == 1
    assert _drain() == []
    assert [t.id for t in _tasks()] == [] or orphan not in [t.id for t in _tasks()]


def test_a_job_interrupted_before_its_task_was_recorded_is_requeued(tmp_path, monkeypatch):
    """
    The window between committing the job row and writing the task row. There
    is no transcript yet, so re-running the whole pipeline is safe.
    """
    job_id = _make_job(status="pending")
    monkeypatch.setattr(worker, "UPLOAD_DIR", tmp_path)
    (tmp_path / f"{job_id}.mp3").write_bytes(b"not really audio")

    report = worker.recover_interrupted_work()

    assert report.reconciled == 1
    task = _drain()[0]
    assert (task.kind, task.job_id) == ("process", job_id)
    assert task.file_path == str(tmp_path / f"{job_id}.mp3")
    # And it is durable this time.
    assert [t.kind for t in _tasks(job_id)] == ["process"]


def test_a_stranded_job_whose_media_is_gone_fails_with_an_explanation(tmp_path, monkeypatch):
    job_id = _make_job(status="transcribing")
    monkeypatch.setattr(worker, "UPLOAD_DIR", tmp_path)

    worker.recover_interrupted_work()

    assert _drain() == []
    job = _job(job_id)
    assert job.status == "failed"
    assert "restart" in job.error_message


def test_a_reviewed_job_is_never_re_run_over_the_top(tmp_path, monkeypatch):
    """
    A job stuck in `analyzing` with a stored transcript could be an interrupted
    *re-analysis*, and re-running it as a fresh job would re-transcribe and
    delete a review to tidy up a status field. Guessing wrong here is not
    recoverable; a failed status with an actionable message is.
    """
    job_id = _make_job(status="analyzing")
    monkeypatch.setattr(worker, "UPLOAD_DIR", tmp_path)
    (tmp_path / f"{job_id}.mp3").write_bytes(b"not really audio")

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.transcript = transcripts.to_json(
            TranscriptResult(
                segments=[Segment(text="already transcribed", start=0.0, end=1.0, words=[])],
                language="en",
                duration=1.0,
            )
        )
        db.add(ViolationRow(id=str(uuid.uuid4()), job_id=job_id, text="keep me",
                            start_time=0.0, end_time=1.0, label="Filler Word",
                            status="accepted"))
        db.commit()
    finally:
        db.close()

    worker.recover_interrupted_work()

    assert _drain() == []
    assert _job(job_id).status == "failed"
    db = SessionLocal()
    try:
        assert db.query(ViolationRow).filter(ViolationRow.job_id == job_id).count() == 1
    finally:
        db.close()


def test_an_interrupted_render_with_no_task_is_not_silently_restarted():
    """
    `edit_action` lived on the task row. Without it the only render we could
    start is one nobody asked for, so the honest move is to say so.
    """
    job_id = _make_job(status="completed", export_status="queued")

    report = worker.recover_interrupted_work()

    assert report.reconciled == 1
    assert _drain() == []
    job = _job(job_id)
    assert job.export_status == "failed"
    assert "restart" in job.export_error


def test_an_auto_fix_render_is_left_to_the_task_that_owns_it():
    """
    An `auto_fix` job renders inside its own process task. Failing its export
    here would put a red banner on a job whose replayed task is about to
    produce exactly the file the status is waiting for.
    """
    job_id = _make_job(status="exporting", export_status="exporting")
    _add_task(job_id, "process", file_path="/tmp/a.mp3")

    report = worker.recover_interrupted_work()

    assert (report.replayed, report.reconciled) == (1, 0)
    assert _job(job_id).export_status == "exporting"


def test_recovery_leaves_finished_jobs_alone():
    done = _make_job(status="completed", export_status="ready")
    failed = _make_job(status="failed")

    report = worker.recover_interrupted_work()

    assert not report.did_something
    assert _job(done).export_status == "ready"
    assert _job(failed).status == "failed"


# --- Replay must not duplicate what the first attempt wrote -------------------


class _StubFfmpeg:
    def input(self, *a, **k):
        return self

    def output(self, *a, **k):
        return self

    def run(self, *a, **k):
        return None


def test_re_running_a_job_replaces_its_suggestions(monkeypatch, tmp_path):
    """
    A job interrupted after its suggestions were committed comes back with two
    copies of every one of them unless the replay clears the first attempt.
    """
    job_id = _make_job(status="transcribing")
    media = tmp_path / f"{job_id}.mp3"
    media.write_bytes(b"not really audio")

    db = SessionLocal()
    try:
        db.add(ViolationRow(id=str(uuid.uuid4()), job_id=job_id, text="um",
                            start_time=0.0, end_time=0.4, label="Filler Word"))
        db.commit()
    finally:
        db.close()

    transcript = TranscriptResult(segments=[], language="en", duration=60.0)

    class StubProcessor:
        def transcribe(self, path, language=None):
            return transcript

        def analyze(self, transcript, prompt=None, preset=None):
            return AnalysisResult(
                violations=[Violation(text="um", start_time=0.0, end_time=0.4,
                                      label="Filler Word", action="cut",
                                      reasoning="hesitation")],
                total_segments_analyzed=0,
                transcript_language="en",
            )

    monkeypatch.setattr(worker, "get_processor", lambda: StubProcessor())
    monkeypatch.setattr(worker, "decode_pcm_mono",
                        lambda path, sr=8000: np.zeros(sr, dtype=np.float32))
    monkeypatch.setattr(worker.Scrubber, "detect_silence",
                        staticmethod(lambda t, *a, **k: []))
    monkeypatch.setattr(worker.Scrubber, "detect_filler_words",
                        staticmethod(lambda t: []))
    monkeypatch.setattr(worker, "ffmpeg", _StubFfmpeg())
    monkeypatch.setattr(exports, "ffmpeg", _StubFfmpeg())

    worker._process_job_sequentially(job_id, str(media))

    db = SessionLocal()
    try:
        rows = db.query(ViolationRow).filter(ViolationRow.job_id == job_id).all()
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0].reasoning == "hesitation"


# --- The books stay clean ----------------------------------------------------


def test_deleting_a_job_takes_its_queued_work_with_it():
    job_id = _make_job(status="pending")
    _add_task(job_id, "process", file_path="/tmp/a.mp3")

    db = SessionLocal()
    try:
        db.delete(db.query(Job).filter(Job.id == job_id).first())
        db.commit()
    finally:
        db.close()

    assert _tasks(job_id) == []


def test_has_outstanding_sees_only_this_jobs_work():
    busy = _make_job(status="completed")
    idle = _make_job(status="completed")
    _add_task(busy, "export")

    db = SessionLocal()
    try:
        assert task_store.has_outstanding(db, busy, "export")
        assert not task_store.has_outstanding(db, idle, "export")
        assert not task_store.has_outstanding(db, busy, "process")
    finally:
        db.close()


def test_a_task_with_no_row_is_still_runnable(monkeypatch):
    """`task_id=None` is the direct-call shape the older tests use."""
    ran = []
    monkeypatch.setattr(worker, "_dispatch", lambda t: ran.append(t))

    worker._run_task(QueuedTask(kind="process", job_id="nobody", file_path="/tmp/x"))

    assert len(ran) == 1
