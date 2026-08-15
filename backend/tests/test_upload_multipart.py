"""
Tests for multipart upload field handling.

Regression: `prompt` was declared as a bare `str | None = None` alongside
`file: UploadFile = File(...)`, which makes FastAPI read it as a *query*
parameter. The frontend sent it in the FormData body, so it silently never
arrived and every job ran the default instruction.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


@pytest.fixture
def client(monkeypatch):
    """
    TestClient without entering the lifespan context, so the background worker
    never starts and no job is actually transcribed.
    """
    enqueued = []
    monkeypatch.setattr(
        "app.routes.jobs.enqueue_job",
        lambda job_id, path: enqueued.append((job_id, path)),
    )
    c = TestClient(app)
    c.enqueued = enqueued
    return c


def _upload(client, data=None, filename="clip.mp3"):
    return client.post(
        "/api/jobs",
        files={"file": (filename, io.BytesIO(b"fake audio bytes"), "audio/mpeg")},
        data=data or {},
    )


def _job(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first()
    finally:
        db.close()


def test_prompt_arrives_from_form_data(client):
    """The flagship feature: a custom instruction sent in the body is stored."""
    prompt = "Flag every specific income claim and any health claim."
    response = _upload(client, {"prompt": prompt, "auto_fix": "false",
                                "auto_scrub": "false", "bsm_mode": "false"})

    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] == prompt
    assert _job(body["id"]).prompt == prompt


def test_boolean_flags_arrive_from_form_data(client):
    response = _upload(client, {"auto_fix": "true", "auto_scrub": "true",
                                "bsm_mode": "false"})

    assert response.status_code == 200
    body = response.json()
    assert body["auto_fix"] is True
    assert body["auto_scrub"] is True
    assert body["bsm_mode"] is False

    job = _job(body["id"])
    assert (job.auto_fix, job.auto_scrub, job.bsm_mode) == (True, True, False)


def test_bsm_mode_without_prompt(client):
    """Strict mode is the one path that legitimately sends no prompt."""
    response = _upload(client, {"auto_fix": "false", "auto_scrub": "false",
                                "bsm_mode": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["bsm_mode"] is True
    assert body["prompt"] is None


def test_defaults_when_only_file_is_sent(client):
    response = _upload(client)

    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] is None
    assert body["auto_fix"] is False
    assert body["auto_scrub"] is False
    assert body["bsm_mode"] is False
    assert body["media_type"] == "audio"


def test_video_extension_sets_media_type(client):
    response = _upload(client, filename="seminar.mp4")

    assert response.status_code == 200
    assert response.json()["media_type"] == "video"


def test_unsupported_extension_rejected(client):
    response = _upload(client, filename="notes.txt")

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_enqueues_exactly_one_job(client):
    response = _upload(client, {"prompt": "find filler words"})

    assert response.status_code == 200
    assert len(client.enqueued) == 1
    assert client.enqueued[0][0] == response.json()["id"]


def test_prompt_is_not_read_from_query_string(client):
    """
    Pin the regression directly: a prompt in the query string must be ignored
    now that the parameter is body-only. If this ever passes again, the
    parameter has silently reverted to a query param.
    """
    response = client.post(
        "/api/jobs?prompt=from-query-string",
        files={"file": ("clip.mp3", io.BytesIO(b"bytes"), "audio/mpeg")},
        data={"prompt": "from-form-data"},
    )

    assert response.status_code == 200
    assert response.json()["prompt"] == "from-form-data"
