"""
CleanCut is loopback-only until an operator says otherwise.

Every route but the admin wipes is unauthenticated, so the interface the port
sits on *is* the access control. Three things have to agree for that to hold,
and they live in three different languages: `app/network.py` decides what counts
as exposed, `start.sh` binds uvicorn and `next dev`, and `docker-compose.yml`
publishes the ports. The shell and the compose file cannot be unit-tested by
running them, so they are pinned here as text - a regression in either is a
one-character edit that reopens the port silently.
"""

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.auth import ALLOW_UNAUTHENTICATED_ADMIN_VAR, check_admin_token
from app.network import (
    DEFAULT_HOST,
    HOST_VAR,
    bind_host,
    exposure_warning,
    is_exposed,
    is_loopback,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- bind_host() ------------------------------------------------------------


def test_bind_host_defaults_to_loopback():
    assert bind_host({}) == DEFAULT_HOST
    assert is_loopback(bind_host({}))


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_host_is_not_a_host(value):
    """`.env.example` ships the key empty; that must read as unset, not as ''."""
    assert bind_host({HOST_VAR: value}) == DEFAULT_HOST


def test_bind_host_honours_an_explicit_value():
    assert bind_host({HOST_VAR: " 0.0.0.0 "}) == "0.0.0.0"


# --- is_loopback() ----------------------------------------------------------


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.1.2.3", "::1", "[::1]", "localhost", "LOCALHOST"]
)
def test_loopback_hosts(host):
    assert is_loopback(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",
        "::",
        "192.168.1.20",
        "10.0.0.5",
        "example.com",
        "",
        "not-an-address",
    ],
)
def test_non_loopback_hosts(host):
    """Anything unrecognised is treated as exposed - the careful direction."""
    assert is_loopback(host) is False


def test_is_exposed_tracks_the_configured_host():
    assert is_exposed({}) is False
    assert is_exposed({HOST_VAR: "127.0.0.1"}) is False
    assert is_exposed({HOST_VAR: "0.0.0.0"}) is True


# --- exposure_warning() -----------------------------------------------------


def test_no_warning_on_loopback():
    assert exposure_warning({}) is None


def test_warning_names_the_host_and_the_risk():
    warning = exposure_warning({HOST_VAR: "0.0.0.0"})
    assert warning is not None
    assert "0.0.0.0" in warning
    assert "authentication" in warning


# --- the admin opt-in is scoped to a machine you control --------------------


def test_ungated_admin_still_works_on_loopback():
    check_admin_token(None, env={ALLOW_UNAUTHENTICATED_ADMIN_VAR: "1"})


def test_ungated_admin_is_refused_once_the_port_is_exposed():
    """
    The flag means "anything that can reach the port may wipe everything". On a
    port a network can reach, that is not what the operator agreed to.
    """
    env = {ALLOW_UNAUTHENTICATED_ADMIN_VAR: "1", HOST_VAR: "0.0.0.0"}
    with pytest.raises(HTTPException) as excinfo:
        check_admin_token(None, env=env)
    assert excinfo.value.status_code == 503
    assert HOST_VAR in excinfo.value.detail
    assert "0.0.0.0" in excinfo.value.detail


def test_a_configured_token_still_works_when_exposed():
    """Exposure disables the *ungated* path, not the gate itself."""
    env = {"ADMIN_TOKEN": "s3cret", HOST_VAR: "0.0.0.0"}
    check_admin_token("s3cret", env=env)
    with pytest.raises(HTTPException) as excinfo:
        check_admin_token("wrong", env=env)
    assert excinfo.value.status_code == 401


# --- the two config files that actually bind the ports ----------------------


def test_start_sh_binds_loopback_by_default():
    script = (REPO_ROOT / "start.sh").read_text()
    assert 'BIND_HOST="${CLEANCUT_HOST:-127.0.0.1}"' in script
    assert "--host 0.0.0.0" not in script
    assert 'uvicorn app.main:app --host "$BIND_HOST"' in script
    # next dev binds every interface unless told otherwise, so the frontend
    # needs the same argument - it serves the review page for these recordings.
    assert '--hostname "$BIND_HOST"' in script


def test_compose_publishes_on_loopback_by_default():
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    published = re.findall(r'^\s+- "(.*:\d+:\d+)"\s*$', compose, flags=re.MULTILINE)
    assert published, "no published ports found - did the compose format change?"
    for entry in published:
        assert entry.startswith("${CLEANCUT_HOST:-127.0.0.1}:"), entry
