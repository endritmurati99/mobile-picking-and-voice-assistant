"""Per-App-Laufzeitdienste (Foundation Task 16).

`create_app(candidate)` nahm eine Settings-Instanz entgegen, band sie aber an
nichts: der Odoo-Client-Cache war ein Modul-Dictionary in `app.dependencies`,
SessionService und LLM-Client hingen an `functools.lru_cache`, und der
HMAC-Keyring wurde pro Request aus `app.config.settings` gebaut. Zwei Apps in
einem Prozess teilten damit alles unterhalb der Routentabelle, und `candidate`
war fuer jede Dependency dekorativ.

`RuntimeServices` ist der Besitzer dieses Zustands. Genau eine Instanz pro App,
gebunden an `app.state.runtime`, aufgeloest ueber `request.app.state.runtime`.

Zwei Regeln, die diese Datei durchhaelt:

* **Lazy, nicht beim App-Bau.** Ein fehlendes Secret darf den Prozess nicht am
  Starten hindern -- sonst antwortet auch `/health/live` nicht mehr, und der
  Betreiber verliert die einzige Probe, die ihm sagen wuerde, welches Secret
  fehlt. Fehler fallen am Ort der Benutzung an, wo die Dependency sie in ein
  503 uebersetzt.
* **Der Keyring wird NICHT gecacht.** Eine Schluesselrotation soll keinen
  Prozess-Neustart brauchen. Alles andere haelt einen Cache, weil es einen Pool
  oder einen uid-Cache besitzt.
"""
from __future__ import annotations

import threading

from app.config import (
    Settings,
    decode_secret_b64,
    get_instance_registry,
    parse_origins,
    read_secret,
)
from app.models.webhook_security import HmacKeyring
from app.services.auth_sessions import SessionService
from app.services.hmac_keyrings import build_n8n_to_backend_keyring
from app.services.llm_client import LlmClient
from app.services.vision_client import VisionClient
from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooClient


class RuntimeServices:
    """Alle langlebigen Dienste einer App-Instanz."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._instances = get_instance_registry(settings)
        self._clients: dict[str, OdooClient] = {}
        # Synchrone Dependencies laufen im FastAPI-Threadpool, also koennen zwei
        # First-Requests gleichzeitig hier ankommen. Double-checked locking
        # verhindert, dass beide einen Client anlegen und einer davon samt
        # httpx-Pool verwaist zurueckbleibt.
        self._lock = threading.Lock()
        self._session_service: SessionService | None = None
        self._n8n_client: N8NWebhookClient | None = None
        self._llm_client: LlmClient | None = None
        self._vision_client: VisionClient | None = None

    @property
    def instances(self):
        """Das Instanzregister DIESER App. Einmal beim Bau aufgeloest, damit ein
        Request nicht gegen ein Register entscheidet, das sich zwischen zwei
        Aufrufen unterscheidet."""
        return self._instances

    def odoo_client(self, name: str) -> OdooClient:
        """Je Odoo-Instanz EIN langlebiger Client -- er besitzt seinen eigenen
        uid-/secret-Cache und den httpx-Verbindungspool."""
        client = self._clients.get(name)
        if client is None:
            with self._lock:
                client = self._clients.get(name)
                if client is None:
                    client = OdooClient(self._instances[name])
                    self._clients[name] = client
        return client

    def session_service(self) -> SessionService:
        """Ein SessionService fuer alle Instanzen dieser App.

        Wirft `ValueError`/`OSError`, wenn das Throttle-Secret fehlt oder
        unlesbar ist. Der Aufrufer uebersetzt das in ein 503; hier wird nichts
        abgefangen, damit es keinen Pfad zu einem Service ohne Throttle-Key gibt.
        """
        service = self._session_service
        if service is None:
            with self._lock:
                service = self._session_service
                if service is None:
                    service = SessionService(
                        client_factory=self.odoo_client,
                        instance_names=set(self._instances.keys()),
                        throttle_secret=decode_secret_b64(
                            "SESSION_THROTTLE_HMAC_SECRET_B64",
                            read_secret(
                                self.settings.session_throttle_hmac_secret_b64,
                                self.settings.session_throttle_hmac_secret_file,
                            ),
                        ),
                        allowed_origins=set(parse_origins(self.settings.pwa_origins)),
                        session_seconds=self.settings.session_max_age_seconds,
                        revalidate_seconds=(
                            self.settings.session_role_revalidate_seconds
                        ),
                    )
                    self._session_service = service
        return service

    def n8n_client(self) -> N8NWebhookClient:
        client = self._n8n_client
        if client is None:
            with self._lock:
                client = self._n8n_client
                if client is None:
                    client = N8NWebhookClient(self.settings)
                    self._n8n_client = client
        return client

    def llm_client(self) -> LlmClient:
        client = self._llm_client
        if client is None:
            with self._lock:
                client = self._llm_client
                if client is None:
                    client = LlmClient(
                        endpoint=self.settings.llm_endpoint,
                        model=self.settings.llm_model,
                        timeout_ms=self.settings.llm_timeout_ms,
                    )
                    self._llm_client = client
        return client

    def vision_client(self) -> VisionClient | None:
        """`None`, wenn die Bildpruefung abgeschaltet ist.

        Der Schalter sitzt hier und nicht in der Route: die Route kennt damit
        nur "Client da oder nicht", und `None` laeuft ueber denselben Pfad wie
        ein Ausfall des Bildmodells. Ein Sonderfall weniger.

        Gecacht wie der Textclient, aus demselben Grund: sonst legt jeder
        Request einen eigenen httpx-Pool an.
        """
        if not self.settings.vision_enabled:
            return None
        client = self._vision_client
        if client is None:
            with self._lock:
                client = self._vision_client
                if client is None:
                    client = VisionClient(
                        endpoint=self.settings.llm_endpoint,
                        model=self.settings.vision_model,
                        timeout_ms=self.settings.vision_timeout_ms,
                    )
                    self._vision_client = client
        return client

    def n8n_to_backend_keyring(self) -> HmacKeyring:
        """Absichtlich ohne Cache: eine Schluesselrotation soll ohne
        Prozess-Neustart wirksam werden."""
        return build_n8n_to_backend_keyring(self.settings)
