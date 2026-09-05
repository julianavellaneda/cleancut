"""
Tests for the upload size and duration guardrails.

Transcription cost is linear in media length and the worker is sequential, so
one oversized upload blocks every job behind it.
"""

import io

import pytest

from app.limits import (
    MediaDurationUnknown,
    MediaTooLong,
    UploadTooLarge,
    enforce_duration_limit,
    max_duration_seconds,
    max_upload_bytes,
    probe_duration_seconds,
    save_within_limit,
)

# --- configuration ---------------------------------------------------------

def test_size_default():
    assert max_upload_bytes({}) == 500_000_000


def test_size_from_env():
    assert max_upload_bytes({"MAX_UPLOAD_MB": "25"}) == 25_000_000


def test_duration_default():
    assert max_duration_seconds({}) == 120 * 60


def test_duration_from_env():
    assert max_duration_seconds({"MAX_DURATION_MINUTES": "5"}) == 300


@pytest.mark.parametrize("value", ["", "  ", "abc", "-1", "0"])
def test_malformed_limit_falls_back_to_default(value):
    """A typo in .env must not take the API down or reject every upload."""
    assert max_upload_bytes({"MAX_UPLOAD_MB": value}) == 500_000_000


# --- streaming save --------------------------------------------------------

def test_file_under_the_cap_is_written(tmp_path):
    dest = tmp_path / "clip.mp3"

    written = save_within_limit(io.BytesIO(b"x" * 1000), dest, max_bytes=5000)

    assert written == 1000
    assert dest.read_bytes() == b"x" * 1000


def test_file_exactly_at_the_cap_is_allowed(tmp_path):
    dest = tmp_path / "clip.mp3"

    assert save_within_limit(io.BytesIO(b"x" * 1000), dest, max_bytes=1000) == 1000


def test_oversized_file_raises(tmp_path):
    dest = tmp_path / "clip.mp3"

    with pytest.raises(UploadTooLarge):
        save_within_limit(io.BytesIO(b"x" * 2000), dest, max_bytes=1000)


def test_oversized_file_leaves_nothing_on_disk(tmp_path):
    """The cap exists to bound disk use; a truncated leftover would defeat it."""
    dest = tmp_path / "clip.mp3"

    with pytest.raises(UploadTooLarge):
        save_within_limit(io.BytesIO(b"x" * 2000), dest, max_bytes=1000)

    assert not dest.exists()


def test_error_names_the_limit(tmp_path):
    dest = tmp_path / "clip.mp3"

    with pytest.raises(UploadTooLarge) as excinfo:
        save_within_limit(io.BytesIO(b"x" * 2_000_000), dest, max_bytes=1_000_000)

    assert "1 MB" in str(excinfo.value)


def test_empty_upload_is_written(tmp_path):
    dest = tmp_path / "clip.mp3"

    assert save_within_limit(io.BytesIO(b""), dest, max_bytes=1000) == 0


# --- duration probe --------------------------------------------------------

def test_unreadable_file_has_unknown_duration(tmp_path):
    """`None` means "could not tell", never zero."""
    bogus = tmp_path / "clip.mp3"
    bogus.write_bytes(b"not actually audio")

    assert probe_duration_seconds(bogus) is None


def test_missing_file_has_unknown_duration(tmp_path):
    assert probe_duration_seconds(tmp_path / "nope.mp3") is None


# --- duration enforcement --------------------------------------------------

def test_duration_under_the_cap_is_returned(tmp_path, monkeypatch):
    monkeypatch.setattr("app.limits.probe_duration_seconds", lambda p: 42.0)

    assert enforce_duration_limit(tmp_path / "clip.mp3", max_seconds=60.0) == 42.0


def test_duration_over_the_cap_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("app.limits.probe_duration_seconds", lambda p: 9999.0)

    with pytest.raises(MediaTooLong):
        enforce_duration_limit(tmp_path / "clip.mp3", max_seconds=60.0)


def test_unknown_duration_fails_closed(tmp_path, monkeypatch):
    """
    A limit anything unprobeable can skip is not a limit. An unbounded stream
    would otherwise sail past the cap and hold the sequential worker for hours.
    """
    monkeypatch.setattr("app.limits.probe_duration_seconds", lambda p: None)

    with pytest.raises(MediaDurationUnknown):
        enforce_duration_limit(tmp_path / "clip.mp3", max_seconds=60.0)


def test_duration_error_names_both_numbers():
    error = MediaTooLong(duration_seconds=9000, max_seconds=7200)

    assert "150.0 minutes" in str(error)
    assert "120 minute" in str(error)


# --- route integration -----------------------------------------------------

@pytest.fixture(autouse=True)
def db_ready():
    from app.database import init_db

    init_db()
    yield


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr("app.routes.jobs.enqueue_job", lambda job_id, path, db=None: "task")
    monkeypatch.setattr("app.routes.jobs.publish", lambda task: task)
    return TestClient(app)


def _upload(client, payload: bytes):
    return client.post(
        "/api/jobs",
        files={"file": ("clip.mp3", io.BytesIO(payload), "audio/mpeg")},
        data={},
    )


def test_oversized_upload_is_rejected_with_413(client, monkeypatch):
    monkeypatch.setattr("app.routes.jobs.max_upload_bytes", lambda: 100)

    response = _upload(client, b"x" * 5000)

    assert response.status_code == 413
    assert "limit" in response.json()["detail"]


def test_rejected_upload_creates_no_job(client, monkeypatch):
    """A guardrail rejection is a 4xx, not a `failed` job cluttering the list."""
    monkeypatch.setattr("app.routes.jobs.max_upload_bytes", lambda: 100)
    before = len(client.get("/api/jobs").json())

    _upload(client, b"x" * 5000)

    assert len(client.get("/api/jobs").json()) == before


def test_overlong_media_is_rejected_with_413(client, monkeypatch):
    monkeypatch.setattr("app.limits.probe_duration_seconds", lambda p: 9999.0)
    monkeypatch.setattr("app.routes.jobs.max_duration_seconds", lambda: 60.0)

    response = _upload(client, b"pretend audio")

    assert response.status_code == 413
    assert "minute" in response.json()["detail"]


def test_probed_duration_is_stored_on_the_job(client, monkeypatch):
    """Known before transcription, so the jobs list can show it immediately."""
    monkeypatch.setattr("app.limits.probe_duration_seconds", lambda p: 42.0)

    response = _upload(client, b"pretend audio")

    assert response.status_code == 200
    assert response.json()["duration_seconds"] == 42.0


def test_unprobeable_upload_is_rejected_with_422(client):
    """
    Fail closed. Accepting an unknown duration let a valid but unprobeable
    stream bypass MAX_DURATION_MINUTES entirely and monopolize the worker.
    """
    response = _upload(client, b"not actually audio")

    assert response.status_code == 422
    assert "duration" in response.json()["detail"]


def test_unprobeable_upload_creates_no_job(client):
    before = len(client.get("/api/jobs").json())

    _upload(client, b"not actually audio")

    assert len(client.get("/api/jobs").json()) == before


def test_rejection_leaves_nothing_on_disk(client):
    from app.routes.jobs import UPLOAD_DIR

    before = set(UPLOAD_DIR.iterdir())

    _upload(client, b"not actually audio")

    assert set(UPLOAD_DIR.iterdir()) == before
