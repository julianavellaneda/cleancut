"""
Tests for export having moved off the request thread and onto the worker queue.

Regression: POST /{job_id}/export ran apply_edits inline, so a long re-encode
held the HTTP request open for the length of the media with no timeout handling
on the client - the UI sat on "Exporting..." with no way to tell a slow export
from a dead one. The route now validates synchronously, queues the render, and
answers 202; the frontend polls `export_status` the way it polls `status`.

The queue and the worker thread are not exercised here - as in the other worker
tests, `_process_export` is called directly and synchronously.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.routes.audio as audio_routes
import app.services.exports as exports
import app.services.worker as worker
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job, Task, Violation


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


class RecordingEditor:
    """Captures the render call instead of invoking FFmpeg."""

    last = None

    def apply_edits(self, input_path, output_path, segments_to_cut=None,
                    segments_to_mute=None, media_type="audio"):
        RecordingEditor.last = {
            "cuts": sorted(segments_to_cut or []),
            "mutes": sorted(segments_to_mute or []),
        }


class ExplodingEditor:
    """Stands in for an FFmpeg pass that dies mid-render."""

    def apply_edits(self, *args, **kwargs):
        raise RuntimeError("ffmpeg fell over")


@pytest.fixture
def enqueued(monkeypatch):
    """Record what the route hands to the queue, without running the worker."""
    calls = []
    monkeypatch.setattr(audio_routes, "enqueue_export",
                        lambda job_id, edit_action=None: calls.append((job_id, edit_action)))
    return calls


@pytest.fixture
def client(monkeypatch, tmp_path, enqueued):
    monkeypatch.setattr(exports, "MediaEditor", RecordingEditor)
    monkeypatch.setattr(audio_routes, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(worker, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(worker, "UPLOAD_DIR", tmp_path)
    RecordingEditor.last = None
    return TestClient(app)


@pytest.fixture
def make_job(monkeypatch, tmp_path):
    def _make(violations=((1.0, 2.0, "cut", "accepted"),), status="completed"):
        job_id = str(uuid.uuid4())
        media = tmp_path / f"{job_id}.mp3"
        media.write_bytes(b"not really audio")
        monkeypatch.setattr(audio_routes, "_get_audio_path", lambda jid: media)

        db = SessionLocal()
        try:
            db.add(Job(id=job_id, filename=f"{job_id}.mp3", status=status))
            for start, end, action, vstatus in violations:
                db.add(Violation(id=str(uuid.uuid4()), job_id=job_id, text="x",
                                 start_time=start, end_time=end,
                                 action=action, status=vstatus))
            db.commit()
        finally:
            db.close()
        return job_id
    return _make


def _job(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first()
    finally:
        db.close()


# --- the route answers immediately -----------------------------------------

def test_export_returns_202_without_rendering(client, make_job, enqueued):
    """The headline fix: the request returns before FFmpeg ever starts."""
    job_id = make_job()

    response = client.post(f"/api/jobs/{job_id}/export", json={})

    assert response.status_code == 202
    assert response.json()["export_status"] == "queued"
    assert RecordingEditor.last is None, "the render must not run on the request thread"
    assert enqueued == [(job_id, None)]


def test_a_second_export_is_refused_while_one_is_outstanding(client, make_job, enqueued):
    """
    One render per job. Queuing a second burned a second FFmpeg pass over the
    length of the media for a file the first was about to write anyway, and let
    a double-click leave `export_status` describing whichever finished last.
    """
    job_id = make_job()
    db = SessionLocal()
    try:
        db.add(Task(id=str(uuid.uuid4()), kind="export", job_id=job_id, state="running"))
        db.commit()
    finally:
        db.close()

    response = client.post(f"/api/jobs/{job_id}/export", json={})

    assert response.status_code == 409
    assert "already in progress" in response.json()["detail"]
    assert enqueued == []


def test_export_marks_the_job_queued(client, make_job):
    job_id = make_job()

    client.post(f"/api/jobs/{job_id}/export", json={})

    assert _job(job_id).export_status == "queued"


def test_global_override_is_carried_onto_the_queue(client, make_job, enqueued):
    job_id = make_job()

    client.post(f"/api/jobs/{job_id}/export", json={"edit_action": "mute"})

    assert enqueued == [(job_id, "mute")]


# --- validation still happens synchronously ---------------------------------

def test_unknown_job_still_404s_without_queueing(client, enqueued):
    assert client.post(f"/api/jobs/{uuid.uuid4()}/export", json={}).status_code == 404
    assert enqueued == []


def test_incomplete_job_still_400s_without_queueing(client, make_job, enqueued):
    job_id = make_job(status="transcribing")

    response = client.post(f"/api/jobs/{job_id}/export", json={})

    assert response.status_code == 400
    assert enqueued == []


def test_nothing_accepted_still_400s_without_queueing(client, make_job, enqueued):
    """A cheap rejection must stay immediate and specific, not become a queued failure."""
    job_id = make_job(violations=((1.0, 2.0, "cut", "pending"),))

    response = client.post(f"/api/jobs/{job_id}/export", json={})

    assert response.status_code == 400
    assert "No accepted edits" in response.json()["detail"]
    assert enqueued == []


# --- the worker side --------------------------------------------------------

def test_worker_export_drives_the_job_to_ready(client, make_job):
    job_id = make_job()
    client.post(f"/api/jobs/{job_id}/export", json={})

    worker._process_export(job_id)

    job = _job(job_id)
    assert job.export_status == "ready"
    assert job.export_error is None
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]


def test_worker_export_only_renders_accepted_edits(client, make_job):
    job_id = make_job(violations=(
        (1.0, 2.0, "cut", "accepted"),
        (3.0, 4.0, "cut", "rejected"),
        (5.0, 6.0, "mute", "accepted"),
    ))

    worker._process_export(job_id)

    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]
    assert RecordingEditor.last["mutes"] == [(5.0, 6.0)]


def test_a_failed_render_does_not_fail_the_job(client, make_job, monkeypatch):
    """
    A completed job carries a review the user just spent real time on. An FFmpeg
    problem is retryable; it must not mark the job `failed` and strand that work
    behind an error screen.
    """
    monkeypatch.setattr(exports, "MediaEditor", ExplodingEditor)
    job_id = make_job()

    worker._process_export(job_id)

    job = _job(job_id)
    assert job.export_status == "failed"
    assert "ffmpeg fell over" in job.export_error
    assert job.status == "completed"


def test_a_retry_clears_the_previous_export_error(client, make_job, monkeypatch):
    monkeypatch.setattr(exports, "MediaEditor", ExplodingEditor)
    job_id = make_job()
    worker._process_export(job_id)
    assert _job(job_id).export_status == "failed"

    monkeypatch.setattr(exports, "MediaEditor", RecordingEditor)
    worker._process_export(job_id)

    job = _job(job_id)
    assert job.export_status == "ready"
    assert job.export_error is None


def test_missing_source_media_is_an_export_failure_not_a_crash(client, make_job, monkeypatch, tmp_path):
    job_id = make_job()
    (tmp_path / f"{job_id}.mp3").unlink()

    worker._process_export(job_id)

    assert _job(job_id).export_status == "failed"


def test_export_for_an_unknown_job_is_a_no_op(client):
    worker._process_export(str(uuid.uuid4()))  # must not raise


# --- the poll can actually see the export state -----------------------------
#
# Regression: `_build_job_response` assembled the response field by field and
# left both export columns out, so GET /api/jobs/{id} answered with the schema
# default "none" no matter what the worker had written. Every state below was
# invisible to the client polling it: the button stayed on "Export" through a
# running render and never became a download when one finished.

def _polled(client, job_id):
    response = client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    return response.json()


def _set_export_state(job_id, status, error=None):
    """Park a job in a state the worker passes through too fast to catch."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.export_status = status
        job.export_error = error
        db.commit()
    finally:
        db.close()


def test_poll_reports_queued_after_the_export_request(client, make_job):
    job_id = make_job()

    client.post(f"/api/jobs/{job_id}/export", json={})

    assert _polled(client, job_id)["export_status"] == "queued"


def test_poll_reports_exporting_while_the_render_runs(client, make_job):
    job_id = make_job()
    _set_export_state(job_id, "exporting")

    assert _polled(client, job_id)["export_status"] == "exporting"


def test_poll_reports_ready_once_the_render_finishes(client, make_job):
    """Without this the download link never appears, whatever the worker did."""
    job_id = make_job()
    client.post(f"/api/jobs/{job_id}/export", json={})

    worker._process_export(job_id)

    body = _polled(client, job_id)
    assert body["export_status"] == "ready"
    assert body["export_error"] is None


def test_poll_reports_a_failed_render_and_its_reason(client, make_job, monkeypatch):
    monkeypatch.setattr(exports, "MediaEditor", ExplodingEditor)
    job_id = make_job()

    worker._process_export(job_id)

    body = _polled(client, job_id)
    assert body["export_status"] == "failed"
    assert "ffmpeg fell over" in body["export_error"]
    # The review survives a bad render; only the export is failed.
    assert body["status"] == "completed"


def test_poll_reports_none_before_any_export(client, make_job):
    job_id = make_job()

    body = _polled(client, job_id)
    assert body["export_status"] == "none"
    assert body["export_error"] is None


def test_a_row_predating_the_column_reads_as_no_export(client, make_job):
    """Migrated rows carry NULL, which the response must render as "none"."""
    job_id = make_job()
    _set_export_state(job_id, None)

    assert _polled(client, job_id)["export_status"] == "none"
