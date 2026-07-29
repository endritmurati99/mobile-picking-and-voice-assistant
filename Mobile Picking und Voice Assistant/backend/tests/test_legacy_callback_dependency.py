"""The five legacy n8n callbacks are service-to-service routes.

Regression cover for whole-branch review finding #8. These routes are
authorised by the shared callback secret and never see a browser cookie, so
they must not resolve their workflow service through the browser/grace
dependency: that returns 401 in production before the handler is reached.
"""

import pytest
from fastapi import Depends

from app.dependencies import (
    get_legacy_n8n_workflow_service,
    get_mobile_workflow_service,
    get_odoo_client,
    get_request_odoo_client_or_grace,
)
from app.routers import n8n_internal

LEGACY_CALLBACK_PATHS = {
    "/n8n/quality-assessment",
    "/n8n/replenishment-action",
    "/n8n/quality-assessment-failed",
    "/n8n/manual-review-activity",
}


def _dependency_names(route):
    return {
        dependency.call
        for dependency in route.dependant.dependencies
    }


def _flattened_calls(dependant):
    calls = set()
    for sub in dependant.dependencies:
        calls.add(sub.call)
        calls |= _flattened_calls(sub)
    return calls


def test_legacy_service_dependency_uses_the_local_client():
    signature_default = get_legacy_n8n_workflow_service.__defaults__
    assert signature_default is not None
    dependency = signature_default[0]
    assert dependency.dependency is get_odoo_client


def test_no_legacy_callback_route_depends_on_the_grace_client():
    offenders = []
    for route in n8n_internal.router.routes:
        path = getattr(route, "path", "")
        if not any(path.endswith(suffix.split("/")[-1]) for suffix in LEGACY_CALLBACK_PATHS):
            continue
        calls = _flattened_calls(route.dependant)
        if get_request_odoo_client_or_grace in calls or get_mobile_workflow_service in calls:
            offenders.append(path)
    assert offenders == [], (
        f"legacy service routes still resolve through the browser/grace client: {offenders}"
    )


def test_legacy_callback_routes_still_require_the_callback_secret():
    from app.dependencies import require_n8n_callback_secret

    checked = 0
    for route in n8n_internal.router.routes:
        path = getattr(route, "path", "")
        if not any(path.endswith(suffix.split("/")[-1]) for suffix in LEGACY_CALLBACK_PATHS):
            continue
        checked += 1
        assert require_n8n_callback_secret in _flattened_calls(route.dependant), path
    assert checked == len(LEGACY_CALLBACK_PATHS)
