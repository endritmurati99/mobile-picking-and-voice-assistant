"""Eine einzige, sichere Settings-Fabrik fuer die App-Factory-Tests (Task 16).

Jeder Test, der eine *produktive* App bauen will, geht durch diese Funktion --
so gibt es genau eine Stelle, an der die "sichere Haltung" definiert ist, und
kein Test kann versehentlich eine halb-konfigurierte Produktions-App bauen.
"""
from app.config import Settings


def make_secure_settings(**overrides) -> Settings:
    values = {
        "runtime_profile": "production",
        "pwa_origins": "https://picking.warehouse.test",
        "mobile_header_grace_mode": False,
        "odoo_api_key": "service-key",
        "odoo_instances_json": "",
        "session_throttle_hmac_secret_b64": (
            "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
        ),
        "session_throttle_hmac_secret_file": "",
        "pwr_backend_to_n8n_active_key_id": "b2n-route-test",
        "pwr_backend_to_n8n_active_secret_b64": (
            "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
        ),
        "pwr_backend_to_n8n_active_secret_file": "",
        "pwr_backend_to_n8n_previous_key_id": "",
        "pwr_backend_to_n8n_previous_secret_b64": "",
        "pwr_backend_to_n8n_previous_secret_file": "",
        "pwr_n8n_to_backend_active_key_id": "n2b-route-test",
        "pwr_n8n_to_backend_active_secret_b64": (
            "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI="
        ),
        "pwr_n8n_to_backend_active_secret_file": "",
        "pwr_n8n_to_backend_previous_key_id": "",
        "pwr_n8n_to_backend_previous_secret_b64": "",
        "pwr_n8n_to_backend_previous_secret_file": "",
        "n8n_webhook_secret": "3" * 32,
        "n8n_webhook_secret_file": "",
        "n8n_callback_secret": "4" * 32,
        "n8n_callback_secret_file": "",
        "dispatcher_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)
