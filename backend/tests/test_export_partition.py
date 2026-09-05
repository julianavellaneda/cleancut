"""
Tests for how the export route routes each accepted violation to cut or mute.

Regression: `Violation.action` was stored, returned and rendered as a badge,
but export applied one global action hardcoded to "cut" by the UI, so mute was
unreachable. The route now partitions by each violation's own action, with
ExportRequest.edit_action available as an optional global override.

MediaEditor is stubbed here - the filter graphs themselves are covered by
test_media_editor.py. What matters is which segments land in which bucket.

Export is queued rather than rendered inline, so each test posts (expecting 202)
and then drives `worker._process_export` synchronously, the way the worker tests
call `_process_job_sequentially` directly. The queue and the thread stay out of it.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.routes.audio as audio_routes
import app.services.exports as exports
import app.services.worker as worker
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job, Violation


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


class RecordingEditor:
    """Captures the cut/mute buckets instead of invoking FFmpeg."""

    last = None

    def apply_edits(
        self,
        input_path,
        output_path,
        segments_to_cut=None,
        segments_to_mute=None,
        media_type="audio",
    ):
        RecordingEditor.last = {
            "cuts": sorted(segments_to_cut or []),
            "mutes": sorted(segments_to_mute or []),
            "media_type": media_type,
        }


@pytest.fixture
def client(monkeypatch, tmp_path):
    # The editor is swapped on `exports`, the single module that now owns
    # rendering for both the queued export and the worker's auto-fix branch.
    monkeypatch.setattr(exports, "MediaEditor", RecordingEditor)
    monkeypatch.setattr(exports, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(worker, "UPLOAD_DIR", tmp_path)
    # Keep the live worker thread out of it; the tests drive the export directly.
    monkeypatch.setattr(audio_routes, "enqueue_export", lambda *a, **k: "task")
    monkeypatch.setattr(audio_routes, "publish", lambda task: task)
    RecordingEditor.last = None
    return TestClient(app)


@pytest.fixture
def do_export(client):
    """POST the export, then run the queued render synchronously."""

    def _do(job_id, payload=None):
        payload = {} if payload is None else payload
        response = client.post(f"/api/jobs/{job_id}/export", json=payload)
        if response.status_code == 202:
            worker._process_export(job_id, payload.get("edit_action"))
        return response

    return _do


@pytest.fixture
def make_job(monkeypatch, tmp_path):
    """Create a completed job with violations, plus a stand-in media file."""

    def _make(violations, media_type="audio"):
        job_id = str(uuid.uuid4())
        media = tmp_path / f"{job_id}.mp3"
        media.write_bytes(b"not really audio")
        monkeypatch.setattr(audio_routes, "_get_audio_path", lambda jid: media)

        db = SessionLocal()
        try:
            db.add(
                Job(
                    id=job_id,
                    filename=f"{job_id}.mp3",
                    status="completed",
                    media_type=media_type,
                )
            )
            for start, end, action, status in violations:
                db.add(
                    Violation(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        text="x",
                        start_time=start,
                        end_time=end,
                        action=action,
                        status=status,
                    )
                )
            db.commit()
        finally:
            db.close()
        return job_id

    return _make


def test_all_cut_violations_go_to_the_cut_bucket(do_export, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "accepted"), (5.0, 6.0, "cut", "accepted")])

    assert do_export(job_id, {}).status_code == 202
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0), (5.0, 6.0)]
    assert RecordingEditor.last["mutes"] == []


def test_all_mute_violations_go_to_the_mute_bucket(do_export, make_job):
    job_id = make_job([(1.0, 2.0, "mute", "accepted"), (5.0, 6.0, "mute", "accepted")])

    assert do_export(job_id, {}).status_code == 202
    assert RecordingEditor.last["cuts"] == []
    assert RecordingEditor.last["mutes"] == [(1.0, 2.0), (5.0, 6.0)]


def test_mixed_actions_are_partitioned(do_export, make_job):
    """The headline fix - both actions honored in one export."""
    job_id = make_job(
        [
            (1.0, 2.0, "cut", "accepted"),
            (5.0, 6.0, "mute", "accepted"),
            (8.0, 9.0, "cut", "accepted"),
        ]
    )

    assert do_export(job_id, {}).status_code == 202
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0), (8.0, 9.0)]
    assert RecordingEditor.last["mutes"] == [(5.0, 6.0)]


def test_only_accepted_violations_are_exported(do_export, make_job):
    job_id = make_job(
        [
            (1.0, 2.0, "cut", "accepted"),
            (3.0, 4.0, "cut", "rejected"),
            (5.0, 6.0, "mute", "pending"),
        ]
    )

    assert do_export(job_id, {}).status_code == 202
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]
    assert RecordingEditor.last["mutes"] == []


def test_global_override_forces_mute(do_export, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "accepted"), (5.0, 6.0, "mute", "accepted")])

    response = do_export(job_id, {"edit_action": "mute"})

    assert response.status_code == 202
    assert RecordingEditor.last["cuts"] == []
    assert RecordingEditor.last["mutes"] == [(1.0, 2.0), (5.0, 6.0)]


def test_global_override_forces_cut(do_export, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "accepted"), (5.0, 6.0, "mute", "accepted")])

    response = do_export(job_id, {"edit_action": "cut"})

    assert response.status_code == 202
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0), (5.0, 6.0)]
    assert RecordingEditor.last["mutes"] == []


def test_null_override_honors_per_violation_actions(do_export, make_job):
    """What the frontend now sends: an explicit null, not a default of 'cut'."""
    job_id = make_job([(1.0, 2.0, "cut", "accepted"), (5.0, 6.0, "mute", "accepted")])

    response = do_export(job_id, {"edit_action": None})

    assert response.status_code == 202
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]
    assert RecordingEditor.last["mutes"] == [(5.0, 6.0)]


def test_missing_action_defaults_to_cut(do_export, make_job):
    job_id = make_job([(1.0, 2.0, None, "accepted")])

    assert do_export(job_id, {}).status_code == 202
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]


def test_export_rejects_job_with_no_accepted_violations(do_export, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "pending")])

    response = do_export(job_id, {})

    assert response.status_code == 400
    assert "No accepted edits" in response.json()["detail"]
    assert RecordingEditor.last is None


def test_export_rejects_incomplete_job(do_export, make_job, tmp_path):
    job_id = make_job([(1.0, 2.0, "cut", "accepted")])
    db = SessionLocal()
    try:
        db.query(Job).filter(Job.id == job_id).first().status = "transcribing"
        db.commit()
    finally:
        db.close()

    response = do_export(job_id, {})

    assert response.status_code == 400
    assert "not completed" in response.json()["detail"].lower()


def test_export_404_for_unknown_job(client):
    assert client.post(f"/api/jobs/{uuid.uuid4()}/export", json={}).status_code == 404


def test_media_type_is_passed_through(do_export, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "accepted")], media_type="video")

    assert do_export(job_id, {}).status_code == 202
    assert RecordingEditor.last["media_type"] == "video"


def test_queued_response_names_the_accepted_count(do_export, make_job):
    """The POST answers before FFmpeg runs, so it reports what was queued."""
    job_id = make_job(
        [
            (1.0, 2.0, "cut", "accepted"),
            (5.0, 6.0, "mute", "accepted"),
            (8.0, 9.0, "mute", "rejected"),
        ]
    )

    body = do_export(job_id, {}).json()

    assert body["export_status"] == "queued"
    assert "2 accepted edit(s)" in body["message"]


def test_describe_edits_counts_both_kinds():
    """The cut/mute summary moved to `exports` when export became asynchronous."""
    message = exports.describe_edits([(1.0, 2.0)], [(5.0, 6.0), (8.0, 9.0)])

    assert "1 cut" in message
    assert "2 muted" in message
