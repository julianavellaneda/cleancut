"""
Shared-secret gate for the destructive admin routes.

The admin endpoints wipe the database and every uploaded file. On a laptop that
is a convenience; on anything reachable from a network it is a hole. This module
gates them behind ``ADMIN_TOKEN``.

The gate fails **closed**: with no ``ADMIN_TOKEN`` configured the destructive
routes are refused outright rather than left open. An unset variable is the
state every deployment starts in and the one an operator is least likely to
notice, so it must not be the state that hands a stranger the delete button.

Local dev still needs the one-click reset, so the old ungated behaviour survives
as an explicit opt-in: ``ALLOW_UNAUTHENTICATED_ADMIN=1``. Typing that is a
decision; leaving ``ADMIN_TOKEN`` blank was not.

Both env vars are read per-request rather than at import time: `main` loads the
root `.env` before importing routes, and a function-level read stays correct no
matter how that import order shifts.
"""

import os
import secrets
from typing import Mapping

from fastapi import Header, HTTPException

ADMIN_TOKEN_HEADER = "X-Admin-Token"

ALLOW_UNAUTHENTICATED_ADMIN_VAR = "ALLOW_UNAUTHENTICATED_ADMIN"

_TRUTHY = {"1", "true", "yes", "on"}


def admin_token(env: Mapping[str, str] | None = None) -> str | None:
    """
    The configured admin secret, or None when the admin routes are ungated.

    A blank or whitespace-only value counts as unset - `.env.example` ships the
    key with an empty value, and an empty string must not become a usable token.
    """
    env = os.environ if env is None else env
    return (env.get("ADMIN_TOKEN") or "").strip() or None


def unauthenticated_admin_allowed(env: Mapping[str, str] | None = None) -> bool:
    """
    Whether the operator has explicitly opted out of the admin gate.

    Only for a machine you control: it restores the pre-fail-closed behaviour,
    where anything that can reach the port can wipe every job and every file.
    A configured ``ADMIN_TOKEN`` takes precedence - the flag opens the routes to
    everyone, so it must never *weaken* a gate an operator deliberately set.
    """
    env = os.environ if env is None else env
    return (env.get(ALLOW_UNAUTHENTICATED_ADMIN_VAR) or "").strip().lower() in _TRUTHY


def check_admin_token(supplied: str | None, env: Mapping[str, str] | None = None) -> None:
    """
    Raise unless the request may run a destructive admin action.

    401 when a token is configured and the request did not supply it; **503**
    when no token is configured at all, since then there is no header the caller
    could send - the fault is the server's configuration, and saying so is what
    stops an operator hunting for a credential that does not exist.

    Split out from the FastAPI dependency so it can be tested with a literal
    env mapping, the way ``limits.max_upload_bytes`` is.
    """
    expected = admin_token(env)
    if expected is None:
        if unauthenticated_admin_allowed(env):
            return
        raise HTTPException(
            status_code=503,
            detail=(
                "The destructive admin routes are disabled because no ADMIN_TOKEN is "
                "configured. Set ADMIN_TOKEN in the root .env and send it in the "
                f"{ADMIN_TOKEN_HEADER} header, or set "
                f"{ALLOW_UNAUTHENTICATED_ADMIN_VAR}=1 to leave them open on a machine "
                "you control."
            ),
        )
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
