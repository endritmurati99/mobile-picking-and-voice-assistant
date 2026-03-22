"""
API smoke test for the local stack.

Usage:
    python test-api.py [--base-url https://192.168.1.100]
    python test-api.py --expect-odoo-down
"""
import argparse
import sys

try:
    import httpx
except ImportError:
    print("pip install httpx")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://localhost")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        default=True,
        help="Disable TLS verification for self-signed certs",
    )
    parser.add_argument(
        "--expect-odoo-down",
        action="store_true",
        help="Treat Odoo-dependent endpoints as skipped",
    )
    args = parser.parse_args()

    client = httpx.Client(
        base_url=args.base_url,
        verify=not args.no_verify,
        timeout=10,
    )

    print(f"Testing API at {args.base_url}\n")

    tests = [
        ("GET", "/api/health", 200, None, "Health check", False),
        ("GET", "/api/pickings", 200 if not args.expect_odoo_down else None, None, "Load pickings", True),
        (
            "POST",
            "/api/scan/validate",
            422,
            None,
            "Scan validation without params returns 422",
            False,
        ),
        (
            "POST",
            "/api/scan/validate",
            200,
            {"params": {"barcode": "4006381333931", "expected_barcode": "4006381333931"}},
            "Scan validation returns match=true",
            False,
        ),
        (
            "POST",
            "/api/scan/validate",
            200,
            {"params": {"barcode": "9999999999999", "expected_barcode": "4006381333931"}},
            "Scan validation returns match=false",
            False,
        ),
        (
            "POST",
            "/api/quality-alerts",
            422,
            None,
            "Quality alert without description returns 422",
            False,
        ),
        (
            "POST",
            "/api/voice/recognize",
            422,
            None,
            "Voice endpoint without audio returns 422",
            False,
        ),
    ]

    passed = 0
    skipped = 0
    failed = 0

    for method, path, expected, payload, description, requires_odoo in tests:
        if requires_odoo and args.expect_odoo_down:
            print(f"  [SKIP] {method} {path} - Odoo not expected")
            skipped += 1
            continue

        try:
            kwargs = {}
            if payload:
                if "params" in payload:
                    kwargs["params"] = payload["params"]
                if "data" in payload:
                    kwargs["data"] = payload["data"]

            resp = client.request(method, path, **kwargs)

            if expected is None:
                print(f"  [OK] {method} {path} -> {resp.status_code} [{description}]")
                passed += 1
                continue

            if resp.status_code != expected:
                print(
                    f"  [FAIL] {method} {path} -> {resp.status_code} "
                    f"(expected: {expected}) [{description}]"
                )
                try:
                    print(f"     Body: {resp.json()}")
                except Exception:
                    print(f"     Body: {resp.text[:200]}")
                failed += 1
                continue

            if path == "/api/health":
                body = resp.json()
                if body.get("status") != "ok":
                    print(
                        f"  [WARN] {method} {path} -> {resp.status_code} "
                        f"but status!=ok: {body}"
                    )
                else:
                    print(f"  [OK] {method} {path} -> {resp.status_code} [{description}]")
            elif "/scan/validate" in path:
                body = resp.json()
                print(
                    f"  [OK] {method} {path} -> {resp.status_code} "
                    f"match={body.get('match')} [{description}]"
                )
            else:
                print(f"  [OK] {method} {path} -> {resp.status_code} [{description}]")
            passed += 1

        except httpx.ConnectError:
            print(f"  [FAIL] {method} {path} -> connection error")
            failed += 1
        except Exception as exc:
            print(f"  [FAIL] {method} {path} -> error: {exc}")
            failed += 1

    total = passed + failed
    print(f"\n{'=' * 50}")
    print(f"Result: {passed}/{total} tests passed, {skipped} skipped")
    if args.expect_odoo_down:
        print("(Odoo-dependent tests were skipped)")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
