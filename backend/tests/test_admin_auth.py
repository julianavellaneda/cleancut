"""
Tests for the shared-secret gate on the destructive admin routes.

Regression: POST /api/admin/reset-database, /clear-storage and /reset-all wiped
every job row and every uploaded file for anyone who could reach the port, with
no credential of any kind. They are now gated behind ADMIN_TOKEN.

The gate fails **closed**: an unconfigured ADMIN_TOKEN disables the routes (503)
rather than leaving them open. The old ungated behaviour is still reachable, but
only by setting ALLOW_UNAUTHENTICATED_ADMIN=1 - both halves of that are under
test, since the whole point is that the unset default is the safe one.
"""

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.routes.admin as admin_routes
import app.services.exports as export_service
from app.auth import (
    ADMIN_TOKEN_HEADER,
    ALLOW_UNAUTHENTICATED_ADMIN_VAR,
    admin_token,
    check_admin_token,
    unauthenticated_admin_allowed,
)
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
    monkeypatch.setattr(export_service, "EXPORT_DIR", exports)
    return TestClient(app)


@pytest.fixture(autouse=True)
def unconfigured(monkeypatch):
    """The default every test starts from: neither variable set."""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv(ALLOW_UNAUTHENTICATED_ADMIN_VAR, raising=False)


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    return "s3cret"


@pytest.fixture
def dev_open(monkeypatch):
    """The explicit local-dev opt-out of the gate."""
    monkeypatch.setenv(ALLOW_UNAUTHENTICATED_ADMIN_VAR, "1")


# --- admin_token() ---------------------------------------------------------

@pytest.mark.parametrize("env", [{}, {"ADMIN_TOKEN": ""}, {"ADMIN_TOKEN": "   "}])
def test_blank_or_absent_token_means_unconfigured(env):
    """`.env.example` ships the key empty; an empty string is not a usable token."""
    assert admin_token(env) is None


def test_configured_token_is_stripped():
    assert admin_token({"ADMIN_TOKEN": "  hunter2\n"}) == "hunter2"


# --- unauthenticated_admin_allowed() ---------------------------------------

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_opt_out_accepts_the_usual_spellings_of_yes(value):
    assert unauthenticated_admin_allowed({ALLOW_UNAUTHENTICATED_ADMIN_VAR: value}) is True


@pytest.mark.parametrize("env", [{}, {ALLOW_UNAUTHENTICATED_ADMIN_VAR: ""},
                                 {ALLOW_UNAUTHENTICATED_ADMIN_VAR: "0"},
                                 {ALLOW_UNAUTHENTICATED_ADMIN_VAR: "false"},
                                 {ALLOW_UNAUTHENTICATED_ADMIN_VAR: "maybe"}])
def test_opt_out_is_off_unless_it_is_a_clear_yes(env):
    assert unauthenticated_admin_allowed(env) is False


# --- check_admin_token() ---------------------------------------------------

def test_check_refuses_when_nothing_is_configured():
    """
    The regression this phase fixes: an unset ADMIN_TOKEN used to mean "open".
    503, not 401 - there is no header the caller could have sent.
    """
    with pytest.raises(HTTPException) as excinfo:
        check_admin_token(None, env={})

    assert excinfo.value.status_code == 503
    assert "ADMIN_TOKEN" in excinfo.value.detail
    assert ALLOW_UNAUTHENTICATED_ADMIN_VAR in excinfo.value.detail


def test_check_refuses_an_unconfigured_server_even_with_a_header():
    """A guessed token cannot enable a gate the operator never configured."""
    with pytest.raises(HTTPException) as excinfo:
        check_admin_token("anything", env={})
    assert excinfo.value.status_code == 503


def test_check_passes_when_the_operator_opted_out():
    check_admin_token(None, env={ALLOW_UNAUTHENTICATED_ADMIN_VAR: "1"})


def test_a_configured_token_still_wins_over_the_opt_out():
    """The flag opens the routes; it must never weaken a gate that was set."""
    env = {"ADMIN_TOKEN": "s3cret", ALLOW_UNAUTHENTICATED_ADMIN_VAR: "1"}

    with pytest.raises(HTTPException) as excinfo:
        check_admin_token(None, env=env)
    assert excinfo.value.status_code == 401

    check_admin_token("s3cret", env=env)


@pytest.mark.parametrize("supplied", [None, "", "wrong", "s3cre", "s3cret "])
def test_check_rejects_anything_but_an_exact_match(supplied):
    with pytest.raises(HTTPException) as excinfo:
        check_admin_token(supplied, env={"ADMIN_TOKEN": "s3cret"})
    assert excinfo.value.status_code == 401


def test_check_accepts_the_exact_token():
    check_admin_token("s3cret", env={"ADMIN_TOKEN": "s3cret"})


# --- the routes ------------------------------------------------------------

@pytest.mark.parametrize("path", DESTRUCTIVE)
def test_destructive_routes_are_disabled_when_nothing_is_configured(client, path):
    response = client.post(path)

    assert response.status_code == 503
    assert "ADMIN_TOKEN" in response.json()["detail"]


@pytest.mark.parametrize("path", DESTRUCTIVE)
def test_destructive_routes_are_open_after_an_explicit_opt_out(client, dev_open, path):
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


def test_stats_survives_the_fail_closed_default(client):
    """
    The dashboard must still load on an unconfigured server. Failing closed
    disables the wipes; it does not take the page down with them.
    """
    assert client.get("/api/admin/stats").status_code == 200
