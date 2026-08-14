"""The production surface: what the host and the LAN can reach (Task 15).

Every assertion here is about ATTACK SURFACE, not about configuration tidiness.
A published port is reachable from the whole LAN; a Caddy path that reaches an
internal route is reachable from every browser that can resolve the host. The
tests read the committed files rather than a running stack on purpose -- the
surface must be reviewable in a diff, before anything is deployed.

Development convenience lives in `docker-compose.dev.yml` and is loopback-only,
so a developer keeps direct access to Odoo and n8n while the LAN does not.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1].parent

# Services that must never publish a port in the production file. `caddy` is
# deliberately absent: it is the only edge.
PRIVATE_SERVICES = (
    "backend",
    "db",
    "odoo",
    "odoo-lager-2",
    "n8n",
    "whisper",
    "piper",
    "ollama",
    "embed",
    "pwa",
)


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def service_block(compose, service):
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|^volumes:|^networks:|^secrets:)",
        compose,
    )
    assert match, "service %s not found in compose" % service
    return match.group(1)


def test_production_publishes_only_caddy_ports():
    compose = read("docker-compose.yml")
    caddy = service_block(compose, "caddy")
    assert '"443:443"' in caddy
    assert '"80:80"' in caddy
    for service in PRIVATE_SERVICES:
        block = service_block(compose, service)
        assert "\n    ports:" not in block, (
            "%s publishes a port in the production compose file; a published "
            "port is reachable from the whole LAN" % service
        )


def test_dev_admin_ports_bind_only_loopback():
    override = read("docker-compose.dev.yml")
    for binding in (
        "127.0.0.1:${BACKEND_HOST_PORT:-8000}:8000",
        "127.0.0.1:${POSTGRES_HOST_PORT:-5433}:5432",
        "127.0.0.1:${ODOO_HOST_PORT:-8069}:8069",
        "127.0.0.1:${ODOO_LAGER2_HOST_PORT:-8070}:8069",
        "127.0.0.1:${N8N_HOST_PORT:-5678}:5678",
    ):
        assert binding in override, "missing loopback binding: %s" % binding
    # Any binding that does NOT start with 127.0.0.1 is published to the LAN.
    assert (
        re.search(r'(?m)^\s*-\s*"(?!127\.0\.0\.1:)[0-9]+:[0-9]+"', override) is None
    ), "the development override publishes a port beyond loopback"


def caddy_directives():
    """The Caddyfile with comment lines removed.

    Ordering and absence are both asserted below, and a comment that merely
    *names* a directive would satisfy either one. Reading the directives alone
    means the guard measures the configuration, not the prose around it.
    """
    lines = read("infrastructure/caddy/Caddyfile").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_caddy_blocks_internal_before_public_api_and_has_no_admin_proxy():
    caddy = caddy_directives()
    blocked = caddy.index("@blocked")
    public_api = caddy.index("@public_api")
    assert blocked < public_api, (
        "the deny-list must be evaluated before the API handler, or an "
        "internal path is proxied before it is refused"
    )
    # ORDER ALONE IS NOT ENOUGH, and the plan's own snippet got this wrong.
    # Caddy does not evaluate directives in file order; it sorts them by its
    # directive order, in which `handle` outranks `respond`. A bare
    # `respond @blocked 404` above `handle @public_api` never fires -- measured
    # live: /api/docs returned Swagger UI from uvicorn and
    # /api/internal/... reached the backend. Only `handle` blocks are mutually
    # exclusive and evaluated among themselves in file order.
    assert re.search(r"handle\s+@blocked\s*\{", caddy), (
        "the deny-list must be a `handle @blocked { ... }` block; a bare "
        "`respond @blocked` is outranked by the `handle` directives below it "
        "and silently blocks nothing"
    )
    for forbidden in ("reverse_proxy n8n:", "localhost:8069", "@n8n_host", "/nn"):
        assert forbidden not in caddy, "Caddy still exposes %s" % forbidden
    for path in (
        "/api/internal/*",
        "/api/integration/*",
        "/api/obsidian/*",
        "/api/demo/*",
        "/api/docs*",
        "/api/redoc*",
        "/api/openapi.json",
    ):
        assert path in caddy, "path not denied at the edge: %s" % path


def test_caddy_pins_its_image_and_bounds_the_request_body():
    """Frozen decision §3.8: the body limit needs Caddy >= 2.10, so the image
    cannot float. This is the edge half; the ASGI half is a separate guard."""
    compose = read("docker-compose.yml")
    caddy_block = service_block(compose, "caddy")
    image = re.search(r"image:\s*(\S+)", caddy_block)
    assert image, "the caddy service has no image"
    tag = image.group(1)
    assert tag != "caddy:2-alpine", "caddy must not float on a moving tag"
    assert "@sha256:" in tag or re.search(r"caddy:2\.(1[0-9]|[2-9][0-9])", tag), (
        "caddy must be pinned to >= 2.10 (request_body max_size), got %s" % tag
    )
    caddy_file = caddy_directives()
    assert "request_body" in caddy_file, "no request body limit at the edge"


def test_caddy_declares_its_trusted_proxies_explicitly():
    """§3.5: relying on the default of an unpinned image is not a decision."""
    assert "trusted_proxies" in caddy_directives()


def test_n8n_is_private_and_code_nodes_cannot_read_environment():
    compose = read("docker-compose.yml")
    block = service_block(compose, "n8n")
    assert 'N8N_BLOCK_ENV_ACCESS_IN_NODE: "true"' in block
    assert 'N8N_PUBLIC_API_DISABLED: "true"' in block
    assert 'N8N_PUBLIC_API_SWAGGERUI_DISABLED: "true"' in block
    assert "NODE_FUNCTION_ALLOW_BUILTIN" not in block, (
        "a Code node that can require() builtins can read the filesystem"
    )
    assert "automation-net" in block
    assert "edge-net" not in block, "n8n must not sit on the edge network"


def test_n8n_builds_the_private_image_with_the_custom_nodes():
    compose = read("docker-compose.yml")
    block = service_block(compose, "n8n")
    assert "build:" in block, "n8n must build the image carrying the PWR nodes"
    assert "context: ./n8n" in block
    dockerfile = read("n8n/Dockerfile")
    assert "N8N_CUSTOM_EXTENSIONS=/opt/n8n-custom" in dockerfile, (
        "the extension path must live outside /home/node/.n8n, which the "
        "persistent n8n_data volume masks"
    )


def test_the_three_networks_exist_and_two_are_internal():
    compose = read("docker-compose.yml")
    networks = compose[compose.index("\nnetworks:") :]
    for name in ("edge-net", "core-net", "automation-net"):
        assert "\n  %s:" % name in networks, "missing network %s" % name
    for internal in ("core-net", "automation-net"):
        block = re.search(
            r"(?ms)^  %s:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)" % internal, networks
        )
        assert block and "internal: true" in block.group(1), (
            "%s must be internal, or a container on it can reach the internet"
            % internal
        )


def test_backend_mounts_the_reviewed_workflow_registry_read_only():
    compose = read("docker-compose.yml")
    block = service_block(compose, "backend")
    assert (
        "./n8n/workflow-registry.json:/run/pwr/workflow-registry.json:ro" in block
    )
    assert "WORKFLOW_REGISTRY_PATH: /run/pwr/workflow-registry.json" in block


def test_compose_secrets_are_owned_and_mode_restricted():
    """R3 made this mandatory: Docker's default 0444 root-owned mount is
    REJECTED by the credential check, so provisioning refuses to start.

    `uid`/`gid`/`mode` are properties of the SERVICE's reference to a secret,
    not of the top-level declaration -- so both halves are required here.
    """
    compose = read("docker-compose.yml")
    assert "\nsecrets:" in compose, "no top-level secrets block at all"
    for name in (
        "pwr_n8n_native_header",
        "pwr_backend_to_n8n_active_hmac",
        "pwr_n8n_to_backend_active_hmac",
    ):
        assert name in compose, "secret %s is not declared" % name
    for key in ("uid:", "gid:", "mode:"):
        assert key in compose, (
            "no service sets %s on its secret reference; Docker's default is "
            "root-owned 0444, which the credential check rejects" % key
        )
