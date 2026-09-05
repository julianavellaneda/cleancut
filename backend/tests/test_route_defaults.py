"""
No route may carry a model instance as a parameter default.

`POST /{job_id}/export` used to declare `request: ExportRequest =
ExportRequest()`. A default is evaluated once, when the module is imported, so
that was a single Pydantic object shared by every bodyless request to that route
for the life of the process. Pydantic models are mutable, so the day anything
assigns to a field of one - a route normalising an input, a dependency filling
in a blank - the value is still there for the next caller, and every caller
after that. Nothing mutated it, so nothing was broken; it was one line of
ordinary code away from being a cross-request data leak.

This is the same rule ruff's B008 enforces, and the reason `pyproject.toml`
exempts FastAPI's own parameter API from it: `Depends(...)`, `Form(...)`,
`File(...)` and friends are calls in a default position too, and they are
*required* - a bare default makes FastAPI read the field as a query parameter,
so an upload form's value silently never arrives. That exemption is narrow on
purpose. This test is what stops it being read as permission to put any
constructed object in a default.

The routers are inspected directly rather than through `app.routes`, which is
not the obvious choice and is the load-bearing one. `include_router` does not
flatten its argument in FastAPI 0.141: it appends an `_IncludedRouter` wrapper
that exposes neither `.routes` nor the endpoints beneath it, so the natural
`for route in app.routes` walk finds four docs endpoints, no route this project
serves, and passes while checking nothing. The first version of this file did
exactly that. `test_every_router_is_inspected` is here so it cannot happen
again quietly.
"""

import inspect

from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.routes import admin, audio, jobs, violations

# Every router main.py mounts. A new one added there and not here would not be
# checked, which is what the count assertion below is for.
ROUTERS = {
    "jobs": jobs.router,
    "violations": violations.router,
    "audio": audio.router,
    "admin": admin.router,
}


def _api_routes():
    for label, router in ROUTERS.items():
        for route in router.routes:
            if isinstance(route, APIRoute):
                yield label, route


def _parameter_defaults():
    """(label, path, method, parameter name, default) across every route."""
    for label, route in _api_routes():
        signature = inspect.signature(route.endpoint)
        method = "/".join(sorted(route.methods or []))
        for name, parameter in signature.parameters.items():
            if parameter.default is not inspect.Parameter.empty:
                yield label, route.path, method, name, parameter.default


def test_every_router_is_inspected():
    """
    A guard that finds nothing passes. This asserts the walk above actually
    reaches routes, so a FastAPI change to how routers are stored shows up as a
    failure here rather than as two assertions quietly checking an empty list.
    """
    routes = list(_api_routes())
    assert len(routes) >= 15, (
        f"only found {len(routes)} routes across {len(ROUTERS)} routers"
    )

    found = {label for label, _ in routes}
    assert found == set(ROUTERS), f"no routes found for {set(ROUTERS) - found}"

    defaults = list(_parameter_defaults())
    assert defaults, "no parameter defaults found at all - the walk is not working"


def test_no_route_shares_a_model_instance_across_requests():
    offenders = [
        f"{method} {label}{path} ({name} = a {type(default).__name__} instance)"
        for label, path, method, name, default in _parameter_defaults()
        if isinstance(default, BaseModel)
    ]
    assert not offenders, (
        "These parameter defaults are single objects built at import time and "
        f"shared by every request to the route: {offenders}. Use "
        "`Body(default_factory=Model)` so each request gets its own."
    )


def test_the_export_body_stays_optional():
    """
    The fix must not have made the body required. `POST /export` with no body
    at all is a documented way to say "honour each violation's own action", and
    `default_factory` preserves that while still building a fresh instance per
    request.
    """
    defaults = [
        default
        for _label, path, _method, name, default in _parameter_defaults()
        if path.endswith("/export") and name == "request"
    ]
    assert len(defaults) == 1, f"expected one export body parameter, found {defaults}"
    assert getattr(defaults[0], "default_factory", None) is not None, (
        "the export body's default must come from a factory, not a shared instance"
    )
