import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "test-api.py"
SPEC = importlib.util.spec_from_file_location("test_api_script", SCRIPT)
test_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(test_api)


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class Client:
    def __init__(self):
        self.calls = []
        self.instance = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, path, **kwargs):
        self.calls.append(("GET", path, kwargs))
        if path == "/api/health/live":
            return Response(payload={"status": "ok"})
        if path == "/api/auth/instances":
            return Response(payload=[{"name": "lager1"}, {"name": "lager2"}])
        if path == "/api/auth/me":
            return Response(payload={"odoo_instance": self.instance})
        if path == "/api/pickings":
            return Response(payload=[])
        raise AssertionError(path)

    def post(self, path, **kwargs):
        self.calls.append(("POST", path, kwargs))
        if path == "/api/auth/picker-session":
            self.instance = kwargs["json"]["odoo_instance"]
            return Response(payload={"csrf_token": "x" * 43})
        if path == "/api/auth/csrf":
            return Response(payload={"csrf_token": "y" * 43})
        if path == "/api/auth/logout":
            return Response(status_code=204)
        raise AssertionError(path)


def test_health_only_smoke_uses_the_current_public_routes_without_login():
    client = Client()

    test_api.run_smoke(client, {}, health_only=True)

    assert [(method, path) for method, path, _ in client.calls] == [
        ("GET", "/api/health/live"),
        ("GET", "/api/auth/instances"),
    ]


def test_default_smoke_requires_both_odoo_credentials():
    with pytest.raises(test_api.SmokeFailure, match="requires both ODOO_USER and ODOO_PASSWORD"):
        test_api.run_smoke(Client(), {})


def test_authenticated_smoke_logs_into_every_instance_and_only_reads_pickings():
    client = Client()

    test_api.run_smoke(
        client,
        {"ODOO_USER": "operator", "ODOO_PASSWORD": "not-printed", "LAN_HOST": "localhost"},
    )

    paths = [(method, path) for method, path, _ in client.calls]
    assert paths.count(("POST", "/api/auth/picker-session")) == 2
    assert paths.count(("POST", "/api/auth/csrf")) == 2
    assert paths.count(("POST", "/api/auth/logout")) == 2
    assert paths.count(("GET", "/api/pickings")) == 2
    assert all("/claim" not in path and "/confirm" not in path for _, path in paths)
    logout_headers = [kwargs["headers"] for method, path, kwargs in client.calls if path == "/api/auth/logout"]
    assert all(headers["X-CSRF-Token"] == "y" * 43 for headers in logout_headers)


def test_partial_dotenv_credentials_fail_before_any_login():
    with pytest.raises(test_api.SmokeFailure, match="both ODOO_USER and ODOO_PASSWORD"):
        test_api.run_smoke(Client(), {"ODOO_USER": "operator"})


def test_cli_returns_nonzero_for_a_failed_smoke(monkeypatch):
    class FailingClient(Client):
        def get(self, path, **kwargs):
            return Response(status_code=503)

    monkeypatch.setattr(test_api, "dotenv_values", lambda _path: {})
    monkeypatch.setattr(test_api.httpx, "Client", lambda **_kwargs: FailingClient())

    assert test_api.main(["--health-only"]) == 1
