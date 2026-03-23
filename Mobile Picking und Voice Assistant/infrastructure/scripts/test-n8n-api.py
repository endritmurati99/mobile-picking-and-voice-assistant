import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_ssl_context(base_url: str) -> ssl.SSLContext | None:
    parsed = urllib.parse.urlparse(base_url)
    insecure = truthy(os.environ.get("N8N_API_INSECURE"))
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        insecure = True
    if not insecure:
        return None

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def main() -> int:
    api_key = os.environ.get("N8N_API_KEY")
    if not api_key:
        sys.stderr.write(
            "N8N_API_KEY fehlt. Bitte einen frischen Key aus Settings > n8n API "
            "als Umgebungsvariable setzen.\n"
        )
        return 1

    base_url = os.environ.get("N8N_API_BASE", "https://localhost/n8n/api/v1").rstrip("/")
    url = f"{base_url}/workflows?active=true&limit=50"
    headers = {
        "Accept": "application/json",
        "X-N8N-API-KEY": api_key,
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    ssl_context = build_ssl_context(base_url)

    try:
        with urllib.request.urlopen(request, context=ssl_context, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"n8n API antwortete mit HTTP {exc.code}.\n{body[:600]}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"n8n API Test fehlgeschlagen: {exc}\n")
        return 1

    workflows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(workflows, list):
        sys.stderr.write("Unerwartetes Antwortformat von n8n API.\n")
        sys.stderr.write(json.dumps(payload, indent=2, ensure_ascii=False)[:1000] + "\n")
        return 1

    print(f"n8n API erreichbar. {len(workflows)} aktive Workflows gefunden.")
    for workflow in workflows[:10]:
        workflow_id = workflow.get("id")
        name = workflow.get("name", "<ohne Namen>")
        print(f"- {workflow_id}: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
