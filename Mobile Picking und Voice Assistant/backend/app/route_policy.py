"""Task 16 -- die Klassifikation der Browser-Mutationen, an EINER Stelle.

Warum eine Ausnahmeliste und keine Liste der geschuetzten Pfade: eine
Positivliste driftet still, sobald jemand eine neue Route hinzufuegt (der
klassische Fehlerfall -- die Route ist da, die Liste nicht). Die Ausnahmeliste
ist fail-closed: eine neue POST-Route auf einem Browser-Router verlangt ab dem
ersten Request einen Idempotency-Key, ohne dass jemand hier etwas eintraegt.

Damit die Ausnahmeliste ihrerseits nicht driftet, prueft
`assert_exemptions_are_real_routes()` beim App-Bau, dass jeder Eintrag
tatsaechlich auf eine registrierte Route zeigt -- ein Tippfehler oder eine
umbenannte Route laesst die App beim Start fallen, statt still eine Mutation
ungeschuetzt zu lassen.
"""

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# (Methode, Routen-Template) der Browser-Mutationen OHNE Idempotenz-Pflicht.
#
# heartbeat:        haelt nur den Lease am Leben, reserviert nie persistent.
# voice/recognize:  reine Transkription, kein Business-Write.
# voice/tts:        reine Synthese, kein Business-Write.
# voice/assist:     ausgenommen NUR solange dieser Endpunkt keinen fachlichen
#                   Write ausloest. Sobald der Voice-Track dort eine Mutation
#                   anhaengt, gehoert der Eintrag hier ersatzlos geloescht.
# scan/validate:    reiner Barcode-Vergleich, beruehrt Odoo nicht.
IDEMPOTENCY_EXEMPT_ROUTES = frozenset(
    {
        ("POST", "/api/pickings/{picking_id}/heartbeat"),
        ("POST", "/api/voice/recognize"),
        ("POST", "/api/voice/assist"),
        ("POST", "/api/voice/tts"),
        ("POST", "/api/scan/validate"),
    }
)


def collect_routes(router, prefix: str = "") -> frozenset[tuple[str, str]]:
    """(Methode, Pfad) aller Routen eines Routers -- so, wie sie eingeschlossen
    werden. Wird beim App-Bau benutzt, damit die Menge der geschuetzten Pfade
    aus dem Router selbst stammt und nicht aus einer zweiten, driftenden Liste.
    """
    collected: set[tuple[str, str]] = set()
    for route in getattr(router, "routes", ()):
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        for method in methods:
            collected.add((method, prefix + route.path))
    return frozenset(collected)


def assert_exemptions_are_real_routes(gated_routes: frozenset[tuple[str, str]]) -> None:
    """Faellt beim App-Bau, wenn ein Ausnahme-Eintrag ins Leere zeigt."""
    stale = sorted(IDEMPOTENCY_EXEMPT_ROUTES - gated_routes)
    if stale:
        raise RuntimeError(
            "Idempotency exemption list points at routes that do not exist: "
            f"{stale}. Remove the entry or fix the path -- a stale exemption "
            "silently un-protects nothing, but it hides that the real route "
            "moved."
        )


def requires_idempotency_key(method: str, route_path: str) -> bool:
    if method not in MUTATING_METHODS:
        return False
    return (method, route_path) not in IDEMPOTENCY_EXEMPT_ROUTES
