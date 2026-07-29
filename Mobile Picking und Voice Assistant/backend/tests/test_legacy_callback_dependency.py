"""The five legacy n8n callbacks are service-to-service routes.

Regression cover for whole-branch review finding #8. These routes are
authorised by the shared callback secret and never see a browser cookie, so
they must not resolve their workflow service through the browser/grace
dependency: that returns 401 in production before the handler is reached.
"""

from app.dependencies import (
    get_legacy_n8n_workflow_service,
    get_mobile_workflow_service,
    get_odoo_client,
    get_request_odoo_client_or_grace,
    require_n8n_callback_secret,
)
from app.routers import n8n_internal

LEGACY_CALLBACK_PATHS = {
    "/internal/n8n/quality-assessment-ai",
    "/internal/n8n/quality-assessment",
    "/internal/n8n/replenishment-action",
    "/internal/n8n/quality-assessment-failed",
    "/internal/n8n/manual-review-activity",
}


def _flattened_calls(dependant):
    calls = set()
    for sub in dependant.dependencies:
        calls.add(sub.call)
        calls |= _flattened_calls(sub)
    return calls


def _routes_requiring_callback_secret():
    """Every route in this router authorised by the shared n8n callback secret.

    Derived from the router itself rather than from a hand-maintained path
    list, so a route that starts (or stops) depending on
    `require_n8n_callback_secret` changes what this function returns instead
    of silently going unchecked.
    """
    return [
        route
        for route in n8n_internal.router.routes
        if require_n8n_callback_secret in _flattened_calls(route.dependant)
    ]


def test_legacy_service_dependency_uses_the_local_client():
    signature_default = get_legacy_n8n_workflow_service.__defaults__
    assert signature_default is not None
    dependency = signature_default[0]
    assert dependency.dependency is get_odoo_client


def test_no_legacy_callback_route_depends_on_the_grace_client():
    offenders = []
    for route in _routes_requiring_callback_secret():
        calls = _flattened_calls(route.dependant)
        if get_request_odoo_client_or_grace in calls or get_mobile_workflow_service in calls:
            offenders.append(route.path)
    assert offenders == [], (
        f"legacy service routes still resolve through the browser/grace client: {offenders}"
    )


def test_legacy_callback_routes_still_require_the_callback_secret():
    # Assert against the router-derived set, not a count compared to the
    # length of the hand-written LEGACY_CALLBACK_PATHS constant: a constant
    # can never catch a route missing from the constant itself. The equality
    # below fails loudly if the router gains or loses a service-authorized
    # route without this list being updated to match.
    routes = _routes_requiring_callback_secret()
    checked_paths = {route.path for route in routes}
    assert checked_paths == LEGACY_CALLBACK_PATHS
    assert len(routes) == len(LEGACY_CALLBACK_PATHS)
