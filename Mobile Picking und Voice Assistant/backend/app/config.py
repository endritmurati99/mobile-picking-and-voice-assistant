import base64
import binascii
import json
import logging
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Kept in one place so the dotenv path `reject_removed_env_vars` inspects can
# never drift from the one `Settings.model_config` actually reads.
_ENV_FILE = ".env"

# Odoo retains request nonces for 900 seconds (see the addon's nonce model).
# The backend must never be configured to expect a longer memory than Odoo has,
# and its signature acceptance window must close well inside that retention.
ODOO_NONCE_RETENTION_SECONDS = 900

# Settings that were removed rather than renamed. `extra="ignore"` would let a
# stale value sit in .env looking effective while doing nothing, so refuse to
# start instead of silently ignoring it.
_REMOVED_ENV_VARS = ("CORS_ORIGINS",)


def reject_removed_env_vars(environ: Mapping[str, str], *, env_file: str | None = _ENV_FILE) -> None:
    """Fail closed on a removed setting in either source `Settings` reads.

    `pydantic-settings`' dotenv source parses `env_file` directly -- it never
    populates `os.environ` -- so checking only `environ` misses a stale
    `CORS_ORIGINS=` line left behind in `.env`. `env_file` is read the same
    way `Settings.model_config` reads it, so a removed key sitting quietly in
    the dotenv file fails closed exactly like one exported in the real
    process environment.

    The comparison is casefolded on both sides: pydantic-settings' dotenv
    source is case-insensitive by default, so a lowercase `cors_origins=` in
    `.env` is read by `Settings`, silently dropped by `extra=\"ignore\"`, and
    would otherwise slip past an exact-case check -- the same silent-stale
    failure this guard exists to prevent, just spelled in lowercase.
    """
    combined: dict[str, str | None] = dict(environ)
    if env_file:
        dotenv_path = Path(env_file)
        if dotenv_path.is_file():
            combined.update(dotenv_values(dotenv_path))
    folded_keys = {key.casefold() for key in combined}
    for name in _REMOVED_ENV_VARS:
        if name.casefold() in folded_keys:
            raise ValueError(
                f"{name} was removed. Configure PWA_ORIGINS instead; it is the "
                "single origin list and it is validated in production."
            )


def reject_wildcard_origins_with_credentials(
    origins: tuple[str, ...], *, allow_credentials: bool
) -> None:
    """Refuse a wildcard origin combined with credentialed CORS, in every
    runtime profile -- not only production.

    Starlette's `CORSMiddleware` (as of 0.46.2) does NOT fall back to a safe
    wildcard when `allow_credentials=True`: it echoes back the request's
    `Origin` header and still sends `Access-Control-Allow-Credentials: true`.
    `PWA_ORIGINS=\"*\"` with credentialed CORS therefore lets any origin read
    authenticated responses (e.g. the `pwr_session` cookie) from a victim's
    browser. This must hold regardless of `runtime_profile`, since an
    operator can set the wildcard on a `development` or `test` box that is
    still reachable on the LAN.
    """
    if allow_credentials and "*" in origins:
        raise ValueError(
            "Wildcard PWA origin ('*') is forbidden while allow_credentials=True, "
            "in every runtime profile: Starlette does not apply a safe-wildcard "
            "fallback for credentialed CORS, so '*' would let any origin read "
            "authenticated responses."
        )


@dataclass(frozen=True)
class OdooProfile:
    name: str
    display_name: str
    url: str
    db: str
    user: str
    api_key: str = ""
    password: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    odoo_url: str = "http://odoo:8069"
    odoo_db: str = "picking"
    odoo_user: str = "admin"
    odoo_api_key: str = ""
    odoo_password: str = ""
    odoo_instances_json: str = ""

    whisper_url: str = "http://whisper:9000"
    piper_url: str = "http://piper:5500"

    # Lokales LLM (Ollama) fuer die KI-Qualitaetsbewertung. Laeuft offline auf dem
    # Lab-PC; kein Cloud-Zugriff noetig. Faellt bei Ausfall auf die n8n-Heuristik zurueck.
    llm_provider: str = "ollama"
    llm_endpoint: str = "http://ollama:11434"
    llm_model: str = "qwen2.5:7b"
    llm_timeout_ms: int = 30000
    # Kleines, schnelles Modell nur fuer den Voice-Intent-Fallback (nicht Qualitaet).
    llm_voice_model: str = "qwen2.5:1.5b"
    llm_voice_timeout_ms: int = 4000
    # Eigenes Modell fuer die Bildpruefung. EIN Modell fuer Text und Bild
    # scheidet gemessen aus: qwen2.5vl:7b stufte "Verpackung defekt" als scrap
    # ein ("Verpackungsdefekt deutet auf Totalschaden hin"), wo qwen2.5:7b
    # korrekt sellable sagt -- und qwen2.5vl:3b antwortete auf alle vier
    # Pruefbilder "smooth and continuous everywhere", auch auf den
    # offensichtlichen Bruch.
    #
    # Beide 7B-Modelle gleichzeitig resident zu halten braucht rund 11 GB. Auf
    # 12 GB WSL-Speicher passt das nicht neben den uebrigen Diensten; der
    # Rechner hat 33 GB, die .wslconfig muss auf 20 GB stehen.
    # Schadenspruefung. Am 2026-08-14 gewechselt, gemessen an acht von Hand
    # beschrifteten Bildern (vier beschaedigt, vier heil) ueber den PRODUKTIVEN
    # Aufruf `inspect_damage` bei `DAMAGE_MAX_EDGE`:
    #
    #   qwen2.5vl:7b      2/4 Schaeden, 0/4 Fehlalarme, Median 82 s
    #   gemma4:12b        4/4 Schaeden, 0/4 Fehlalarme, Median 58 s
    #   minicpm-v4.5:8b   4/4 Schaeden, 0/4 Fehlalarme, Median 49 s
    #
    # `qwen2.5vl:7b` uebersah die ausgerissene Kerbe am gelben Bogenstein
    # (foto_10, foto_11) und nannte die Oberflaeche glatt -- auf einem Foto, auf
    # dem der Schaden rund ein Fuenftel der Flaeche einnimmt. Live derselbe
    # Fehler in QA/0322 und QA/0327. Es meldet nicht falsch, es sieht zu wenig.
    #
    # gemma4 und minicpm sind bei n=8 nicht auseinanderzuhalten. Den Ausschlag
    # gibt der Betrieb: gemma4 traegt bereits den Rueckfall des
    # Artikelabgleichs, also braucht die Kette mit ihm EIN Bildmodell statt
    # zwei -- und `OLLAMA_MAX_LOADED_MODELS=2` geht mit Text- und Bildmodell
    # genau auf, ohne dass waehrend einer Bewertung ein Modell verdraengt und
    # neu geladen wird (gemessen 80-145 s je Ladevorgang).
    vision_model: str = "gemma4:12b"
    # Der ARTIKELABGLEICH laeuft ueber ein eigenes Bildmodell, die
    # Schadenspruefung bleibt auf `vision_model`. Beides getrennt, weil die
    # zwei Achsen getrennt gemessen sind und in verschiedene Richtungen
    # zeigen:
    #
    # * Artikelachse, 12 handgeprueften Faelle vom 2026-08-13
    #   (`docs/superpowers/specs/2026-08-13-artikelabgleich-modellvergleich.md`):
    #   `gemma4:12b` 10/12 bei 49 s je Fall, `qwen2.5vl:7b` 6/12 bei 149 s.
    #   Entscheidend ist die Schadenstoleranz -- 5/6 gegen 2/6. `qwen2.5vl:7b`
    #   haelt einen Riss fuer ein Artikelmerkmal ("The right part is visibly
    #   damaged and not the same") und weist damit die echte Schadensmeldung
    #   als Falschlieferung ab. Das ist der teuerste Fehler der Kette.
    # * Schadensachse: dort ist `qwen2.5vl:7b` bei 1024 px eingemessen
    #   (Commit `2532e3a`: bei 768 px "a leaf-like DESIGN", bei 1024 px "a
    #   leaf-shaped INDENTATION"). Fuer `gemma4:12b` gibt es auf dieser Achse
    #   KEINE Messung. Wer hier denselben Namen eintraegt, dreht eine
    #   gemessene Verbesserung ungeprueft zurueck.
    #
    # Beide Modelle gleichzeitig resident sind rund 9 GB + 6 GB; die
    # `.wslconfig` steht seit dem 2026-08-13 auf 26 GB.
    #
    # WICHTIG, damit niemand mehr erwartet, als hier steht: die 10/12 wurden
    # ueber eine MONTAGE gemessen (beide Teile in EIN Bild, ein Aufruf urteilt
    # `same_part`). Der Produktivpfad beschreibt beide Bilder einzeln und
    # laesst das Textmodell vergleichen (`_check_article`). Der Modellwechsel
    # traegt also die bessere Beschreibung in den Vergleich hinein, nicht das
    # gemessene Urteil selbst.
    vision_article_model: str = "gemma4:12b"
    # Notausgang: auf false verhaelt sich die Kette wie vor dem Bild-Umbau,
    # ohne dass jemand Code zurueckdrehen muss.
    vision_enabled: bool = True
    # Gilt je Bildaufruf. Gemessen am echten Meldefoto (QA/0204, 512 px):
    # Artikelabgleich 169 s, Schadenspruefung 9 s. Der Zwei-Bild-Aufruf ist der
    # teure. 200 s lassen ihm Luft; die Grenze liegt bewusst hier und nicht
    # erst im n8n-Knoten -- laeuft sie hier ab, traegt die Antwort den Grund im
    # Klartext, bricht der Knoten ab, geht der Befund ersatzlos verloren.
    vision_timeout_ms: int = 200000
    # Gesamtbudget fuer alle Bildaufrufe EINER Bewertung. Drei Fotos ergaeben
    # vier Aufrufe und damit ein Vielfaches der Lease. Der Artikelabgleich
    # laeuft immer, die Schadenspruefung nur solange davon Zeit uebrig ist;
    # was liegen bleibt, wird gezaehlt und genannt.
    vision_budget_ms: int = 240000
    # Artikelabgleich ueber Bildabstand (Dienst `embed`) statt ueber zwei
    # Beschreibungen und ein Textmodell.
    #
    # `off`     wie bisher: das Textmodell vergleicht zwei Beschreibungen.
    # `schatten` der Einbettungsdienst laeuft mit und protokolliert, entscheidet
    #           aber nichts. Fuer eine Messreihe im Betrieb, ohne Risiko.
    # `primaer` der Einbettungsdienst entscheidet; faellt er aus, ist die
    #           Kennung unbekannt oder lautet das Urteil `unsicher`, uebernimmt
    #           der bisherige Weg unveraendert.
    #
    # Warum `primaer` der Standard ist: am 2026-08-14 wurden zehn Meldungen
    # durch die echte Kette geschickt. Der Textvergleich wies drei richtige
    # Teile ab -- einmal auf "blue" gegen "light blue" (QA/0323), einmal auf
    # "studs" gegen "four cylindrical studs" bei zweimal woertlich "light blue"
    # (QA/0331), einmal auf "arch-shaped" gegen "rounded top" (QA/0329) -- und
    # liess denselben Wortunterschied an anderer Stelle durch (QA/0333). Der
    # Einbettungsdienst traf auf denselben echten Meldefotos 7/7 in 0,36-1,78 s
    # gegen 45-165 s. Belege in
    # `docs/superpowers/specs/2026-08-13-artikelabgleich-modellvergleich.md`.
    embed_mode: str = "primaer"
    embed_url: str = "http://embed:8000"
    # Gemessen 0,36-1,78 s je Abgleich. 15 s sind rund zehnfache Luft und
    # bleiben weit unter `vision_budget_ms` -- der Rueckfallweg muss noch
    # hineinpassen, wenn der Dienst haengt.
    embed_timeout_ms: int = 15000
    # Der Katalogaufbau ist der teure Aufruf: 26,5 s fuer 47 Bilder, beim
    # allerersten Mal zusaetzlich das Laden des Modells.
    embed_katalog_timeout_ms: int = 180000
    # Wie lange ein eingebetteter Katalog gilt. Neue Artikel und getauschte
    # Katalogbilder kommen im Lagerbetrieb selten; ein Tag ist reichlich eng
    # genug, und ein Neustart des Dienstes erzwingt den Aufbau ohnehin.
    embed_katalog_ttl_s: int = 86400
    # Wie lange eine Bewertung darauf wartet, dass die vorige fertig ist.
    # Gemessen am 2026-08-07: zwei Meldungen 20 s auseinander (QA/0214 aus dem
    # Skript, QA/0215 aus der PWA) liefen gleichzeitig in Ollama. Aufrufe, die
    # sonst 8 s brauchen, dauerten 1m30 bis 3m20, zwei endeten in HTTP 500 --
    # BEIDE Bewertungen fielen aus. Der Rechner haelt ein 7B-Textmodell und ein
    # 7B-Bildmodell gleichzeitig nicht auf der CPU aus.
    #
    # Der Wert liegt unter dem Knotendeckel (270 s) minus einer typischen
    # Bewertung (~100 s): wer laenger warten muesste, kaeme ohnehin nicht mehr
    # rechtzeitig durch und bekommt lieber sofort eine ehrliche Absage.
    assessment_wait_ms: int = 150000
    # Beim Start das Voice-Modell in Ollama vorwaermen, damit die erste unsichere
    # Sprachaeusserung nicht den Kaltstart (bis ~13s) bezahlt. Default False, damit
    # Tests kein erreichbares Ollama brauchen; im Compose auf true gesetzt.
    voice_llm_warmup: bool = False
    openai_api_key: str = ""

    n8n_webhook_base: str = "http://n8n:5678/webhook"
    n8n_webhook_path_quality_alert_created: str = "quality-alert-created"
    n8n_webhook_path_voice_exception_query: str = "voice-exception-query"
    n8n_webhook_path_shortage_reported: str = "shortage-reported"
    n8n_webhook_path_pick_confirmed: str = "pick-confirmed"
    n8n_webhook_secret: str = ""
    n8n_sync_timeout_ms: int = 7000
    n8n_callback_secret: str = ""
    n8n_connect_timeout_ms: int = 1000
    n8n_circuit_breaker_failures: int = 3
    n8n_circuit_breaker_open_seconds: int = 60

    log_level: str = "info"
    mobile_claim_ttl_seconds: int = 120
    mobile_claim_heartbeat_seconds: int = 30
    mobile_idempotency_ttl_seconds: int = 86400
    mobile_header_grace_mode: bool = False
    demo_traceability_enabled: bool = False
    demo_traceability_allowed_dbs: str = "masterfischer_o19_trial"

    # Secure runtime / session / auth configuration (Task 1: Platform Security and
    # Event Contracts Foundation). See docs/superpowers/plans/
    # 2026-07-23-platform-security-event-contracts-foundation.md for rationale.
    runtime_profile: Literal["development", "test", "production"] = "development"
    pwa_origins: str = "https://localhost"
    trusted_caddy_peers: str = "127.0.0.1"
    session_cookie_name: str = "pwr_session"
    session_max_age_seconds: int = 28800
    session_role_revalidate_seconds: int = Field(default=300, ge=1, le=300)
    session_throttle_hmac_secret_b64: str = ""
    login_failure_limit: int = 5
    login_window_seconds: int = 900
    login_throttle_retention_seconds: int = 86400
    pwr_hmac_max_skew_seconds: int = Field(default=300, ge=1, le=300)
    pwr_nonce_ttl_seconds: int = 900
    pwr_backend_to_n8n_active_key_id: str = ""
    pwr_backend_to_n8n_active_secret_b64: str = ""
    pwr_backend_to_n8n_previous_key_id: str = ""
    pwr_backend_to_n8n_previous_secret_b64: str = ""
    pwr_n8n_to_backend_active_key_id: str = ""
    pwr_n8n_to_backend_active_secret_b64: str = ""
    pwr_n8n_to_backend_previous_key_id: str = ""
    pwr_n8n_to_backend_previous_secret_b64: str = ""
    # Docker-secret counterparts of the secrets above. A production deployment
    # mounts them below /run/secrets instead of exporting them into the
    # process environment; see `read_secret` for the resolution rules.
    session_throttle_hmac_secret_file: str = ""
    pwr_backend_to_n8n_active_secret_file: str = ""
    pwr_backend_to_n8n_previous_secret_file: str = ""
    pwr_n8n_to_backend_active_secret_file: str = ""
    pwr_n8n_to_backend_previous_secret_file: str = ""
    n8n_webhook_secret_file: str = ""
    n8n_callback_secret_file: str = ""

    # Second layer of the request body limit (program register §3.8). The edge
    # half lives in the Caddyfile (`request_body { max_size 16MB }`), but a
    # direct n8n -> backend call on the private network never passes through
    # Caddy, so the ASGI stack enforces the same bound itself. The default
    # matches both the edge and n8n's N8N_PAYLOAD_SIZE_MAX=16 (MB).
    max_request_body_bytes: int = Field(default=16 * 1024 * 1024, ge=1)

    workflow_registry_path: str = "../n8n/workflow-registry.json"

    # Wie lange der Startlauf auf eine noch nicht antwortende Odoo-Instanz
    # wartet. Deckt AUSSCHLIESSLICH den Kaltstart: Odoo braucht nach einem
    # Neustart rund eine Minute, bis es zuhoert. Ein Instanzname, der
    # tatsaechlich falsch ist, bricht weiterhin sofort ab -- gewartet wird nur
    # auf eine Antwort, nie auf eine bessere.
    startup_odoo_wait_seconds: float = Field(default=120.0, ge=0.0)

    dispatcher_enabled: bool = False
    dispatcher_poll_seconds: float = 2.0
    dispatcher_lease_seconds: int = 60
    dispatcher_batch_size: int = 50

    @model_validator(mode="after")
    def _check_replay_window(self) -> "Settings":
        window = 2 * self.pwr_hmac_max_skew_seconds
        if self.pwr_nonce_ttl_seconds <= window:
            raise ValueError(
                "PWR_NONCE_TTL_SECONDS must exceed the signature acceptance "
                f"window of {window}s (2 x PWR_HMAC_MAX_SKEW_SECONDS)"
            )
        if self.pwr_nonce_ttl_seconds > ODOO_NONCE_RETENTION_SECONDS:
            raise ValueError(
                "PWR_NONCE_TTL_SECONDS must not exceed the Odoo nonce retention "
                f"of {ODOO_NONCE_RETENTION_SECONDS}s"
            )
        return self


def warn_non_production_runtime_profile(candidate: Settings) -> None:
    """Log one WARNING line whenever the active profile is not `production`.

    Finding #2 (round 1 fix): the deployed stack never set RUNTIME_PROFILE at
    all, so the Literal-typed field silently kept its `development` default
    with nothing surfacing that fact. A missing/wrong profile must never fail
    a running container's startup (operators depend on it), but it must not
    be silent either -- this makes the effective posture visible in the logs
    every time the process starts.
    """
    if candidate.runtime_profile != "production":
        logger.warning(
            "RUNTIME_PROFILE is %r, not 'production' (mobile_header_grace_mode=%s). "
            "If this is meant to be a production deployment, RUNTIME_PROFILE was "
            "not set correctly -- set it explicitly to 'production'.",
            candidate.runtime_profile,
            candidate.mobile_header_grace_mode,
        )


reject_removed_env_vars(os.environ)
settings = Settings()
ODOO19_TRIAL_PROFILE_NAMES = {"o19", "odoo19", "o19-trial", "odoo19-trial"}
ODOO19_TRIAL_DB = "masterfischer_o19_trial"


def get_instance_registry(candidate: Settings = settings) -> dict[str, OdooProfile]:
    """Register aller bekannten Odoo-Instanzen fuer die uebergebene `candidate`
    Settings-Instanz (niemals ein anderes globales Settings-Objekt).

    `local` kommt kanonisch aus den odoo_*-Settings; weitere Profile aus
    ODOO_INSTANCES_JSON (Secrets .env-only). Ausnahme: in production ist ein
    nicht-leeres ODOO_INSTANCES_JSON autoritativ — das Register startet leer und
    ein explizit gelistetes `local`-Profil wird wie jedes andere behandelt statt
    des impliziten Legacy-`local`-Profils.
    """
    raw = (candidate.odoo_instances_json or "").strip()
    production_authoritative = candidate.runtime_profile == "production" and bool(raw)

    registry: dict[str, OdooProfile] = {}
    if not production_authoritative:
        registry["local"] = OdooProfile(
            name="local",
            display_name="Lager 1",
            url=candidate.odoo_url,
            db=candidate.odoo_db,
            user=candidate.odoo_user,
            api_key=candidate.odoo_api_key,
            password=candidate.odoo_password,
        )

    if not raw:
        return registry
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ODOO_INSTANCES_JSON ist kein gueltiges JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("ODOO_INSTANCES_JSON muss ein JSON-Objekt sein.")
    for name, cfg in parsed.items():
        key = str(name).strip().lower()
        if key == "local" and not production_authoritative:
            continue  # local ist kanonisch aus odoo_* — JSON-local wird ignoriert
        if not isinstance(cfg, dict):
            raise ValueError(f"ODOO_INSTANCES_JSON['{name}'] muss ein Objekt sein.")
        if "url" not in cfg or "db" not in cfg:
            raise ValueError(f"ODOO_INSTANCES_JSON['{name}'] braucht 'url' und 'db'.")
        db_name = str(cfg["db"])
        if key in ODOO19_TRIAL_PROFILE_NAMES and db_name != ODOO19_TRIAL_DB:
            raise ValueError(
                f"ODOO_INSTANCES_JSON['{name}'] muss fuer Odoo-19-Trial die DB "
                f"'{ODOO19_TRIAL_DB}' nutzen, nicht '{db_name}'."
            )
        registry[key] = OdooProfile(
            name=key,
            display_name=str(cfg.get("display_name") or key),
            url=str(cfg["url"]),
            db=db_name,
            user=str(cfg.get("user") or "admin"),
            api_key=str(cfg.get("api_key") or ""),
            password=str(cfg.get("password") or ""),
        )
    return registry


def decode_secret_b64(name: str, value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{name} must be valid base64") from exc
    if len(decoded) < 32:
        raise ValueError(f"{name} must decode to at least 32 bytes")
    return decoded


def parse_origins(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def read_secret(direct: str, file_path: str) -> str:
    """Resolve one secret from either a direct value or a mounted file.

    There is deliberately NO precedence rule. Configuring both forms of the
    same secret raises instead of silently picking one: a precedence rule is
    how two deployments end up disagreeing about which secret is actually
    live, and the disagreement only surfaces as an authentication failure long
    after the rotation.

    A secret file readable by group or other is refused outright. `0o077`
    covers every group and other bit, so `0600`/`0400` pass and `0640`/`0644`
    do not.
    """
    if direct and file_path:
        raise ValueError("Configure a secret value or a secret file, not both")
    if file_path:
        path = Path(file_path)
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ValueError(
                f"Secret file permissions are too broad ({mode:04o}); "
                f"group and other must have no access: {path}"
            )
        return path.read_text(encoding="utf-8").strip()
    return direct


# (env var name, direct field, secret-file field). The env var name is what
# `decode_secret_b64` and the validation errors quote, so a file-provided
# secret reports the same identity as a directly configured one.
SECRET_SOURCES: tuple[tuple[str, str, str], ...] = (
    (
        "SESSION_THROTTLE_HMAC_SECRET_B64",
        "session_throttle_hmac_secret_b64",
        "session_throttle_hmac_secret_file",
    ),
    (
        "PWR_BACKEND_TO_N8N_ACTIVE_SECRET_B64",
        "pwr_backend_to_n8n_active_secret_b64",
        "pwr_backend_to_n8n_active_secret_file",
    ),
    (
        "PWR_BACKEND_TO_N8N_PREVIOUS_SECRET_B64",
        "pwr_backend_to_n8n_previous_secret_b64",
        "pwr_backend_to_n8n_previous_secret_file",
    ),
    (
        "PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64",
        "pwr_n8n_to_backend_active_secret_b64",
        "pwr_n8n_to_backend_active_secret_file",
    ),
    (
        "PWR_N8N_TO_BACKEND_PREVIOUS_SECRET_B64",
        "pwr_n8n_to_backend_previous_secret_b64",
        "pwr_n8n_to_backend_previous_secret_file",
    ),
    ("N8N_WEBHOOK_SECRET", "n8n_webhook_secret", "n8n_webhook_secret_file"),
    ("N8N_CALLBACK_SECRET", "n8n_callback_secret", "n8n_callback_secret_file"),
)


def resolve_secrets(candidate: Settings) -> dict[str, str]:
    """Resolve every direct/file secret pair exactly once.

    Callers that need more than one secret must use this rather than calling
    `read_secret` per site, so a file is opened once per resolution and every
    downstream consumer sees the same resolved string.
    """
    resolved: dict[str, str] = {}
    for name, direct_field, file_field in SECRET_SOURCES:
        try:
            resolved[name] = read_secret(
                getattr(candidate, direct_field), getattr(candidate, file_field)
            )
        except (ValueError, OSError) as exc:
            raise ValueError(f"{name}: {exc}") from exc
    return resolved


def validate_runtime_security(candidate: Settings) -> None:
    # Resolve BEFORE the profile gate: configuring both forms of one secret,
    # or mounting a group-readable secret file, is a configuration defect in
    # every runtime profile and must fail startup rather than wait until the
    # first request reaches a downstream factory.
    resolved = resolve_secrets(candidate)

    if candidate.runtime_profile != "production":
        return

    origins = parse_origins(candidate.pwa_origins)
    if not origins or "*" in origins:
        raise ValueError("Wildcard or empty PWA origins are forbidden in production")
    if any(urlparse(origin).scheme != "https" for origin in origins):
        raise ValueError("Production PWA origins must use HTTPS")
    if candidate.mobile_header_grace_mode:
        raise ValueError("mobile header grace mode is forbidden in production")
    profiles = get_instance_registry(candidate)
    if not profiles or any(
        not (profile.api_key or profile.password) for profile in profiles.values()
    ):
        raise ValueError(
            "Every production Odoo profile requires an Odoo service credential"
        )
    # Every check below reads the RESOLVED value, never the direct field, so a
    # file-only production configuration passes exactly the same checks as a
    # direct-value test configuration.
    if len(resolved["N8N_WEBHOOK_SECRET"].encode("utf-8")) < 32:
        raise ValueError("native n8n webhook credential must be at least 32 bytes")
    if len(resolved["N8N_CALLBACK_SECRET"].encode("utf-8")) < 32:
        raise ValueError("legacy callback credential must be at least 32 bytes")

    for name in (
        "SESSION_THROTTLE_HMAC_SECRET_B64",
        "PWR_BACKEND_TO_N8N_ACTIVE_SECRET_B64",
        "PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64",
    ):
        decode_secret_b64(name, resolved[name])

    if not candidate.pwr_backend_to_n8n_active_key_id:
        raise ValueError("backend-to-n8n active key ID is required")
    if not candidate.pwr_n8n_to_backend_active_key_id:
        raise ValueError("n8n-to-backend active key ID is required")

    previous_pairs = (
        (
            candidate.pwr_backend_to_n8n_previous_key_id,
            resolved["PWR_BACKEND_TO_N8N_PREVIOUS_SECRET_B64"],
            "PWR_BACKEND_TO_N8N_PREVIOUS_SECRET_B64",
        ),
        (
            candidate.pwr_n8n_to_backend_previous_key_id,
            resolved["PWR_N8N_TO_BACKEND_PREVIOUS_SECRET_B64"],
            "PWR_N8N_TO_BACKEND_PREVIOUS_SECRET_B64",
        ),
    )
    for key_id, secret, name in previous_pairs:
        if bool(key_id) != bool(secret):
            raise ValueError(f"{name} and its key ID must be configured together")
        if secret:
            decode_secret_b64(name, secret)


validate_runtime_security(settings)
warn_non_production_runtime_profile(settings)
