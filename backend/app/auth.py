"""
Shared-secret gate for the destructive admin routes.

The admin endpoints wipe the database and every uploaded file. On a laptop that
is a convenience; on anything reachable from a network it is a hole. This module
gates them behind ``ADMIN_TOKEN``.

The gate is *off* when no token is configured, so the local dev flow and the
existing docker-compose demo keep working untouched. Setting ``ADMIN_TOKEN``
turns it on. The env var is read per-request rather than at import time: `main`
loads the root `.env` before importing routes, and a function-level read stays
correct no matter how that import order shifts.
"""

import os
import secrets
from typing import Mapping

from fastapi import Header, HTTPException

ADMIN_TOKEN_HEADER = "X-Admin-Token"


def admin_token(env: Mapping[str, str] | None = None) -> str | None:
    """
    The configured admin secret, or None when the admin routes are ungated.

    A blank or whitespace-only value counts as unset - `.env.example` ships the
    key with an empty value, and an empty string must not become a usable token.
    """
    env = os.environ if env is None else env
    return (env.get("ADMIN_TOKEN") or "").strip() or None


def check_admin_token(supplied: str | None, env: Mapping[str, str] | None = None) -> None:
    """
    Raise 401 unless the request may run a destructive admin action.

    Split out from the FastAPI dependency so it can be tested with a literal
    env mapping, the way ``limits.max_upload_bytes`` is.
    """
    expected = admin_token(env)
    if expected is None:
        return
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail=(
                f"Invalid or missing admin token. Send the configured ADMIN_TOKEN "
                f"in the {ADMIN_TOKEN_HEADER} header."
            ),
        )


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency wrapping :func:`check_admin_token`."""
    check_admin_token(x_admin_token)
