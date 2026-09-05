"""
Tests for GET /api/jobs/{id}/export/stream.

The download route serves the export as an attachment, which is right for a
"save this file" button but useless for playing the result back in the page --
and `window.open` on an attachment URL opens a tab that immediately closes.
The stream route serves the same file inline so an <audio>/<video> element can
load it directly.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.routes.audio as audio_routes
import app.services.exports as exports
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(exports, "EXPORT_DIR", tmp_path)
    return TestClient(app)


@pytest.fixture
def make_job(monkeypatch, tmp_path):
    """Create a completed job with a stand-in source file, and optionally an export."""

    def _make(media_type="audio", source_ext=".mp3", export_ext=None):
        job_id = str(uuid.uuid4())
        source = tmp_path / f"{job_id}{source_ext}"
        source.write_bytes(b"not really media")
        monkeypatch.setattr(audio_routes, "_get_audio_path", lambda jid: source)

        if export_ext:
            (tmp_path / f"{job_id}_edited{export_ext}").write_bytes(b"edited bytes")

        db = SessionLocal()
        try:
            db.add(
                Job(
                    id=job_id,
                    filename=f"seminar{source_ext}",
                    status="completed",
                    media_type=media_type,
                )
            )
            db.commit()
        finally:
            db.close()
        return job_id

    return _make


def test_unknown_job_is_404(client):
    assert client.get(f"/api/jobs/{uuid.uuid4()}/export/stream").status_code == 404


def test_404_before_an_export_has_been_generated(client, make_job):
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/export/stream")

    assert response.status_code == 404
    assert "Generate export first" in response.json()["detail"]


def test_serves_the_export_inline_not_as_an_attachment(client, make_job):
    job_id = make_job(export_ext=".mp3")

    response = client.get(f"/api/jobs/{job_id}/export/stream")

    assert response.status_code == 200
    assert response.content == b"edited bytes"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["content-disposition"].startswith("inline")
    assert "attachment" not in response.headers["content-disposition"]


def test_download_route_still_serves_the_same_file_as_an_attachment(client, make_job):
    job_id = make_job(export_ext=".mp3")

    response = client.get(f"/api/jobs/{job_id}/export/download")

    assert response.status_code == 200
    assert response.content == b"edited bytes"
    assert response.headers["content-disposition"].startswith("attachment")


def test_video_export_streams_with_a_video_media_type(client, make_job):
    job_id = make_job(media_type="video", source_ext=".mp4", export_ext=".mp4")

    response = client.get(f"/api/jobs/{job_id}/export/stream")

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"


def test_filename_is_derived_from_the_job_not_the_job_id(client, make_job):
    job_id = make_job(export_ext=".mp3")

    response = client.get(f"/api/jobs/{job_id}/export/stream")

    assert 'filename="seminar_edited.mp3"' in response.headers["content-disposition"]
    assert job_id not in response.headers["content-disposition"]
