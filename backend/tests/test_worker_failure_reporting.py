"""
Tests for how the worker records a failure.

Regression: the `except` block assigned `job.status` where `job` was bound
inside the `try`. When the initial query was what threw, the handler died with
`NameError: job`, the real cause was lost, and the job sat at `pending` forever
while the frontend polled it.
"""

import uuid

import pytest

import app.services.worker as worker
from app.analysis.prompt_analyzer import AnalysisError, AnalysisResult
from app.analysis.transcriber import TranscriptResult
from app.database import SessionLocal, init_db
from app.models import Job


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


def _job(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first()
    finally:
        db.close()


@pytest.fixture
def queued_job(tmp_path):
    """A pending job with a file on disk, ready for the worker to pick up."""
    job_id = str(uuid.uuid4())
    media = tmp_path / f"{job_id}.mp3"
    media.write_bytes(b"not really audio")

    db = SessionLocal()
    try:
        db.add(Job(id=job_id, filename=media.name, status="pending"))
        db.commit()
    finally:
        db.close()

    return job_id, str(media)


def _stub_processor(monkeypatch, *, transcribe=None, analyze=None):
    transcript = TranscriptResult(segments=[], language="en", duration=60.0)

    class StubProcessor:
        def transcribe(self, path, language=None):
            if transcribe is not None:
                return transcribe()
            return transcript

        def analyze(self, transcript, prompt=None, preset=None):
            if analyze is not None:
                return analyze()
            return AnalysisResult(violations=[], total_segments_analyzed=0,
                                  transcript_language="en")

    monkeypatch.setattr(worker, "get_processor", lambda: StubProcessor())
    monkeypatch.setattr(worker.Scrubber, "detect_silence", staticmethod(lambda t: []))
    monkeypatch.setattr(worker.Scrubber, "detect_filler_words", staticmethod(lambda t: []))


def _raise(exc):
    def _boom():
        raise exc
    return _boom


def test_transcription_failure_marks_the_job_failed(monkeypatch, queued_job):
    job_id, path = queued_job
    _stub_processor(monkeypatch, transcribe=_raise(RuntimeError("model download failed")))

    worker._process_job_sequentially(job_id, path)

    job = _job(job_id)
    assert job.status == "failed"
    assert "model download failed" in job.error_message


def test_analysis_failure_reports_the_real_reason(monkeypatch, queued_job):
    """An unreadable model response must reach the user, not vanish into `[]`."""
    job_id, path = queued_job
    _stub_processor(monkeypatch, analyze=_raise(AnalysisError("model returned HTML")))

    worker._process_job_sequentially(job_id, path)

    job = _job(job_id)
    assert job.status == "failed"
    assert "model returned HTML" in job.error_message


def test_worker_does_not_raise_out_of_the_job_body(monkeypatch, queued_job):
    """The queue loop must survive any single job's failure."""
    job_id, path = queued_job
    _stub_processor(monkeypatch, transcribe=_raise(RuntimeError("boom")))

    worker._process_job_sequentially(job_id, path)  # must not raise


def test_failing_initial_query_does_not_mask_the_error(monkeypatch, queued_job, caplog):
    """
    The exact regression: when the query that binds `job` is what throws, the
    handler used to die with NameError and report that instead of the real cause.
    """
    job_id, path = queued_job

    real_session = worker.SessionLocal

    class ExplodingSession:
        def __init__(self):
            self._db = real_session()
            self._exploded = False

        def query(self, *args, **kwargs):
            # Fail only the worker's first lookup; _mark_failed's re-query works.
            if not self._exploded:
                self._exploded = True
                raise RuntimeError("database is locked")
            return self._db.query(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._db, name)

    monkeypatch.setattr(worker, "SessionLocal", ExplodingSession)

    with caplog.at_level("ERROR"):
        worker._process_job_sequentially(job_id, path)

    assert "database is locked" in caplog.text
    assert "NameError" not in caplog.text

    job = _job(job_id)
    assert job.status == "failed"
    assert "database is locked" in job.error_message


def test_missing_job_row_is_not_an_error(monkeypatch):
    """A deleted job dequeued after the fact: log and move on, do not crash."""
    worker._process_job_sequentially(str(uuid.uuid4()), "/nonexistent.mp3")


def test_partial_analysis_completes_with_a_warning(monkeypatch, queued_job, tmp_path):
    """
    Some chunks unreadable: the job still completes, because its suggestions are
    reviewable - but it carries a warning naming the unanalyzed spans.
    """
    job_id, path = queued_job
    _stub_processor(monkeypatch, analyze=lambda: AnalysisResult(
        violations=[],
        total_segments_analyzed=0,
        transcript_language="en",
        failed_chunks=["chunk 2/3 [50s-100s]: garbled response"],
    ))

    worker._process_job_sequentially(job_id, path)

    job = _job(job_id)
    assert job.status == "completed"
    assert "Partial analysis" in job.error_message
    assert "50s-100s" in job.error_message


def test_clean_analysis_leaves_no_warning(monkeypatch, queued_job):
    job_id, path = queued_job
    _stub_processor(monkeypatch)

    worker._process_job_sequentially(job_id, path)

    job = _job(job_id)
    assert job.status == "completed"
    assert job.error_message is None
