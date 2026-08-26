"""
Tests for the shared-secret gate on the destructive admin routes.

Regression: POST /api/admin/reset-database, /clear-storage and /reset-all wiped
every job row and every uploaded file for anyone who could reach the port, with
no credential of any kind. They are now gated behind ADMIN_TOKEN.

The gate stays off when no token is configured, so the local dev flow is
unchanged - that behavior is under test too, since silently requiring a token
would break every existing setup.
"""

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.routes.admin as admin_routes
from app.auth import ADMIN_TOKEN_HEADER, admin_token, check_admin_token
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job

DESTRUCTIVE = ["/api/admin/reset-database", "/api/admin/clear-storage", "/api/admin/reset-all"]


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A client whose storage wipes point at tmp_path, not the real uploads dir."""
    uploads = tmp_path / "uploads"
    exports = tmp_path / "exports"
    uploads.mkdir()
    exports.mkdir()
    monkeypatch.setattr(admin_routes, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(admin_routes, "EXPORT_DIR", exports)
    return TestClient(app)


@pytest.fixture
def no_token(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    return "s3cret"


# --- admin_token() ---------------------------------------------------------

@pytest.mark.parametrize("env", [{}, {"ADMIN_TOKEN": ""}, {"ADMIN_TOKEN": "   "}])
def test_blank_or_absent_token_means_ungated(env):
    """`.env.example` ships the key empty; an empty string is not a usable token."""
    assert admin_token(env) is None


def test_configured_token_is_stripped():
    assert admin_token({"ADMIN_TOKEN": "  hunter2\n"}) == "hunter2"


# --- check_admin_token() ---------------------------------------------------

def test_check_passes_when_ungated_even_without_a_header():
    check_admin_token(None, env={})


@pytest.mark.parametrize("supplied", [None, "", "wrong", "s3cre", "s3cret "])
def test_check_rejects_anything_but_an_exact_match(supplied):
    with pytest.raises(HTTPException) as excinfo:
        check_admin_token(supplied, env={"ADMIN_TOKEN": "s3cret"})
    assert excinfo.value.status_code == 401


def test_check_accepts_the_exact_token():
    check_admin_token("s3cret", env={"ADMIN_TOKEN": "s3cret"})


# --- the routes ------------------------------------------------------------

@pytest.mark.parametrize("path", DESTRUCTIVE)
def test_destructive_routes_are_open_when_no_token_is_configured(client, no_token, path):
    assert client.post(path).status_code == 200


@pytest.mark.parametrize("path", DESTRUCTIVE)
def test_destructive_routes_401_without_the_header(client, with_token, path):
    response = client.post(path)

    assert response.status_code == 401
    assert ADMIN_TOKEN_HEADER in response.json()["detail"]


@pytest.mark.parametrize("path", DESTRUCTIVE)
def test_destructive_routes_401_with_the_wrong_header(client, with_token, path):
    assert client.post(path, headers={ADMIN_TOKEN_HEADER: "nope"}).status_code == 401


@pytest.mark.parametrize("path", DESTRUCTIVE)
def test_destructive_routes_accept_the_right_header(client, with_token, path):
    assert client.post(path, headers={ADMIN_TOKEN_HEADER: with_token}).status_code == 200


def test_reset_all_is_gated_in_its_own_right(client, with_token):
    """
    reset_all calls the other two as plain Python functions, not over HTTP, so a
    dependency declared on those never runs for it. Without its own gate it
    would have stayed the widest hole of the three.
    """
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed"))
        db.commit()
    finally:
        db.close()

    assert client.post("/api/admin/reset-all").status_code == 401

    db = SessionLocal()
    try:
        assert db.query(Job).filter(Job.id == job_id).first() is not None
    finally:
        db.close()


def test_stats_stays_readable_without_a_token(client, with_token):
    """Reads are not gated - only the three routes that destroy data are."""
    assert client.get("/api/admin/stats").status_code == 200
