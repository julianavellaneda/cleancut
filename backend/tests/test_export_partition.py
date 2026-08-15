"""
Tests for how the export route routes each accepted violation to cut or mute.

Regression: `Violation.action` was stored, returned and rendered as a badge,
but export applied one global action hardcoded to "cut" by the UI, so mute was
unreachable. The route now partitions by each violation's own action, with
ExportRequest.edit_action available as an optional global override.

MediaEditor is stubbed here - the filter graphs themselves are covered by
test_media_editor.py. What matters is which segments land in which bucket.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.routes.audio as audio_routes
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

    def apply_edits(self, input_path, output_path, segments_to_cut=None,
                    segments_to_mute=None, media_type="audio"):
        RecordingEditor.last = {
            "cuts": sorted(segments_to_cut or []),
            "mutes": sorted(segments_to_mute or []),
            "media_type": media_type,
        }


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_routes, "MediaEditor", RecordingEditor)
    monkeypatch.setattr(audio_routes, "EXPORT_DIR", tmp_path)
    RecordingEditor.last = None
    return TestClient(app)


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
            db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed",
                       media_type=media_type))
            for start, end, action, status in violations:
                db.add(Violation(
                    id=str(uuid.uuid4()), job_id=job_id, text="x",
                    start_time=start, end_time=end, action=action, status=status,
                ))
            db.commit()
        finally:
            db.close()
        return job_id
    return _make


def test_all_cut_violations_go_to_the_cut_bucket(client, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "accepted"), (5.0, 6.0, "cut", "accepted")])

    assert client.post(f"/api/jobs/{job_id}/export", json={}).status_code == 200
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0), (5.0, 6.0)]
    assert RecordingEditor.last["mutes"] == []


def test_all_mute_violations_go_to_the_mute_bucket(client, make_job):
    job_id = make_job([(1.0, 2.0, "mute", "accepted"), (5.0, 6.0, "mute", "accepted")])

    assert client.post(f"/api/jobs/{job_id}/export", json={}).status_code == 200
    assert RecordingEditor.last["cuts"] == []
    assert RecordingEditor.last["mutes"] == [(1.0, 2.0), (5.0, 6.0)]


def test_mixed_actions_are_partitioned(client, make_job):
    """The headline fix - both actions honored in one export."""
    job_id = make_job([
        (1.0, 2.0, "cut", "accepted"),
        (5.0, 6.0, "mute", "accepted"),
        (8.0, 9.0, "cut", "accepted"),
    ])

    assert client.post(f"/api/jobs/{job_id}/export", json={}).status_code == 200
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0), (8.0, 9.0)]
    assert RecordingEditor.last["mutes"] == [(5.0, 6.0)]


def test_only_accepted_violations_are_exported(client, make_job):
    job_id = make_job([
        (1.0, 2.0, "cut", "accepted"),
        (3.0, 4.0, "cut", "rejected"),
        (5.0, 6.0, "mute", "pending"),
    ])

    assert client.post(f"/api/jobs/{job_id}/export", json={}).status_code == 200
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]
    assert RecordingEditor.last["mutes"] == []


def test_global_override_forces_mute(client, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "accepted"), (5.0, 6.0, "mute", "accepted")])

    response = client.post(f"/api/jobs/{job_id}/export", json={"edit_action": "mute"})

    assert response.status_code == 200
    assert RecordingEditor.last["cuts"] == []
    assert RecordingEditor.last["mutes"] == [(1.0, 2.0), (5.0, 6.0)]


def test_global_override_forces_cut(client, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "accepted"), (5.0, 6.0, "mute", "accepted")])

    response = client.post(f"/api/jobs/{job_id}/export", json={"edit_action": "cut"})

    assert response.status_code == 200
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0), (5.0, 6.0)]
    assert RecordingEditor.last["mutes"] == []


def test_null_override_honors_per_violation_actions(client, make_job):
    """What the frontend now sends: an explicit null, not a default of 'cut'."""
    job_id = make_job([(1.0, 2.0, "cut", "accepted"), (5.0, 6.0, "mute", "accepted")])

    response = client.post(f"/api/jobs/{job_id}/export", json={"edit_action": None})

    assert response.status_code == 200
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]
    assert RecordingEditor.last["mutes"] == [(5.0, 6.0)]


def test_missing_action_defaults_to_cut(client, make_job):
    job_id = make_job([(1.0, 2.0, None, "accepted")])

    assert client.post(f"/api/jobs/{job_id}/export", json={}).status_code == 200
    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]


def test_export_rejects_job_with_no_accepted_violations(client, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "pending")])

    response = client.post(f"/api/jobs/{job_id}/export", json={})

    assert response.status_code == 400
    assert "No accepted edits" in response.json()["detail"]
    assert RecordingEditor.last is None


def test_export_rejects_incomplete_job(client, make_job, tmp_path):
    job_id = make_job([(1.0, 2.0, "cut", "accepted")])
    db = SessionLocal()
    try:
        db.query(Job).filter(Job.id == job_id).first().status = "transcribing"
        db.commit()
    finally:
        db.close()

    response = client.post(f"/api/jobs/{job_id}/export", json={})

    assert response.status_code == 400
    assert "not completed" in response.json()["detail"].lower()


def test_export_404_for_unknown_job(client):
    assert client.post(f"/api/jobs/{uuid.uuid4()}/export", json={}).status_code == 404


def test_media_type_is_passed_through(client, make_job):
    job_id = make_job([(1.0, 2.0, "cut", "accepted")], media_type="video")

    assert client.post(f"/api/jobs/{job_id}/export", json={}).status_code == 200
    assert RecordingEditor.last["media_type"] == "video"


def test_export_message_counts_both_kinds(client, make_job):
    job_id = make_job([
        (1.0, 2.0, "cut", "accepted"),
        (5.0, 6.0, "mute", "accepted"),
        (8.0, 9.0, "mute", "accepted"),
    ])

    message = client.post(f"/api/jobs/{job_id}/export", json={}).json()["message"]

    assert "1 cut" in message
    assert "2 muted" in message
