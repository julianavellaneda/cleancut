"""
Which interface CleanCut is reachable on.

Every route except the admin wipes is unauthenticated: the jobs list, the
original recording, the transcript and the export are all readable by anything
that can reach the port. That is a reasonable trade for a tool you run on your
own laptop, and a hole the moment the port is on a shared network. So the
default is **loopback**, and reaching CleanCut from another machine is a
decision an operator has to type.

``CLEANCUT_HOST`` is that decision, and it names *the interface CleanCut is
reachable on* rather than the argument any one process passes to a socket:
`start.sh` hands it to uvicorn and to `next dev`, and `docker-compose.yml` uses
it as the published interface while the container still binds `0.0.0.0`
internally - a container's own network is not the host's, so binding every
interface inside it exposes nothing by itself.

Keeping it one variable is what lets this module answer the only question the
running app actually cares about: is anyone but this machine able to reach us?
`auth.check_admin_token` asks, because ``ALLOW_UNAUTHENTICATED_ADMIN`` means "on
a machine I control" - it must not hand the delete button to a network.

No third-party imports, so it can be tested with a literal env mapping the way
`limits` and `preflight` are.
"""

import ipaddress
import os
from collections.abc import Mapping

HOST_VAR = "CLEANCUT_HOST"

#: Loopback: reachable from this machine and nothing else.
DEFAULT_HOST = "127.0.0.1"

#: Hostnames that resolve to loopback but are not IP literals.
_LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}


def bind_host(env: Mapping[str, str] | None = None) -> str:
    """
    The interface CleanCut is configured to be reachable on.

    A blank or whitespace-only value counts as unset - `.env.example` ships the
    key empty, and an empty string is not a host anything can bind.
    """
    env = os.environ if env is None else env
    return (env.get(HOST_VAR) or "").strip() or DEFAULT_HOST


def is_loopback(host: str) -> bool:
    """
    Whether ``host`` is reachable only from this machine.

    Anything unrecognised is treated as **not** loopback. A hostname this
    module cannot resolve to a loopback address is either a real interface or a
    typo, and both deserve the careful answer; no DNS lookup is done, because a
    security decision that depends on a network round-trip is one that fails in
    whichever direction the network happens to fail.
    """
    candidate = (host or "").strip()
    if not candidate:
        return False
    if candidate.lower() in _LOOPBACK_NAMES:
        return True
    # An IPv6 literal may arrive bracketed, the way a URL carries it.
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def is_exposed(env: Mapping[str, str] | None = None) -> bool:
    """Whether CleanCut is reachable from somewhere other than this machine."""
    return not is_loopback(bind_host(env))


def exposure_warning(env: Mapping[str, str] | None = None) -> str | None:
    """
    A startup warning when CleanCut is bound past loopback, else None.

    Printed rather than raised: exposing the port is a supported choice, and the
    operator who typed ``CLEANCUT_HOST`` should be reminded what it means, not
    stopped from booting.
    """
    if not is_exposed(env):
        return None
    host = bind_host(env)
    return (
        f"WARNING: {HOST_VAR}={host} - CleanCut is reachable from other machines.\n"
        "  Uploads, transcripts and exports are served without authentication. "
        "Put it behind a reverse proxy that authenticates, or set "
        f"{HOST_VAR}=127.0.0.1 to keep it on this machine."
    )
