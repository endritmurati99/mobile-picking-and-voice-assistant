"""Read-only smoke test for the local backend.

It always checks the public liveness and instance-list routes. When both
``ODOO_USER`` and ``ODOO_PASSWORD`` exist in the selected dotenv file, it also
creates a browser session for every configured warehouse and reads its open
pickings. It never creates, claims, confirms, or otherwise changes an order.
"""

import argparse
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]


class SmokeFailure(RuntimeError):
    pass


def _request(client, method, path, **kwargs):
    try:
        return getattr(client, method.lower())(path, **kwargs)
    except httpx.HTTPError as exc:
        raise SmokeFailure(f"{method} {path} request failed ({type(exc).__name__})") from exc


def _expect(response, method, path, *, status=200, json=True):
    if response.status_code != status:
        raise SmokeFailure(f"{method} {path} returned HTTP {response.status_code}")
    return response.json() if json else None


def _origin(values):
    origins = values.get("PWA_ORIGINS", "")
    if origins:
        return origins.split(",", 1)[0].strip()
    return f"https://{values.get('LAN_HOST', 'localhost')}"


def run_smoke(client, values, *, health_only=False):
    health = _expect(_request(client, "GET", "/api/health/live"), "GET", "/api/health/live")
    if health.get("status") != "ok":
        raise SmokeFailure("GET /api/health/live did not report status=ok")

    instances = _expect(_request(client, "GET", "/api/auth/instances"), "GET", "/api/auth/instances")
    if not isinstance(instances, list) or not instances:
        raise SmokeFailure("GET /api/auth/instances returned no instances")
    if health_only:
        return

    login = values.get("ODOO_USER", "")
    password = values.get("ODOO_PASSWORD", "")
    if not login or not password:
        raise SmokeFailure("authenticated smoke requires both ODOO_USER and ODOO_PASSWORD")

    origin = _origin(values)
    for instance in instances:
        name = instance.get("name")
        if not isinstance(name, str) or not name:
            raise SmokeFailure("GET /api/auth/instances returned an invalid instance")
        csrf = None
        try:
            session = _expect(
                _request(
                    client,
                    "POST",
                "/api/auth/picker-session",
                headers={"Origin": origin},
                json={
                    "login": login,
                    "password": password,
                    "device_id": str(uuid4()),
                    "odoo_instance": name,
                    },
                ),
                "POST",
                "/api/auth/picker-session",
            )
            csrf = session.get("csrf_token")
            if not isinstance(csrf, str) or len(csrf) < 43:
                raise SmokeFailure("POST /api/auth/picker-session returned no CSRF token")
            principal = _expect(
                _request(client, "GET", "/api/auth/me", headers={"Origin": origin}),
                "GET",
                "/api/auth/me",
            )
            if principal.get("odoo_instance") != name:
                raise SmokeFailure("GET /api/auth/me returned the wrong Odoo instance")
            rotated = _expect(
                _request(client, "POST", "/api/auth/csrf", headers={"Origin": origin}),
                "POST",
                "/api/auth/csrf",
            )
            csrf = rotated.get("csrf_token")
            if not isinstance(csrf, str) or len(csrf) < 43:
                raise SmokeFailure("POST /api/auth/csrf returned no CSRF token")
            pickings = _expect(
                _request(client, "GET", "/api/pickings", headers={"Origin": origin}),
                "GET",
                "/api/pickings",
            )
            if not isinstance(pickings, list):
                raise SmokeFailure("GET /api/pickings did not return a list")
        finally:
            if csrf:
                _expect(
                    _request(
                        client,
                        "POST",
                        "/api/auth/logout",
                        headers={"Origin": origin, "X-CSRF-Token": csrf},
                    ),
                    "POST",
                    "/api/auth/logout",
                    status=204,
                    json=False,
                )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only backend smoke test")
    parser.add_argument("--base-url", default="https://localhost")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--verify-tls", action="store_true")
    parser.add_argument("--health-only", action="store_true")
    args = parser.parse_args(argv)

    values = dotenv_values(args.env_file)
    try:
        with httpx.Client(base_url=args.base_url, verify=args.verify_tls, timeout=10) as client:
            run_smoke(client, values, health_only=args.health_only)
    except SmokeFailure as exc:
        print(f"[FAIL] {exc}")
        return 1
    except httpx.HTTPError as exc:
        print(f"[FAIL] HTTP request failed ({type(exc).__name__})")
        return 1
    print("[OK] read-only API smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
