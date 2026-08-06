"""Bildbefund gegen Texturteil -- die Entscheidung, ohne Modell.

Das Bild PRUEFT das Texturteil, es ersetzt es nicht. Der Text liefert
weiterhin die Einstufung; das Bild kann sie bestaetigen, ihr widersprechen
oder eine Abweichung vermerken.

Hier entscheidet Python und kein drittes Modell. Ein Modell, das beide
Quellen sieht, kann einen Widerspruch wegerklaeren -- eine Tabelle kann das
nicht. Dieselbe Ueberlegung, aus der die Bewertungsroute selbst nichts
entscheidet: ueber Wirkung entscheidet ausschliesslich der Callback.

**Warum ein Widerspruch nicht immer blockiert.** Der Kommissionierer hatte den
Artikel in der Hand, das Modell hat ein 512-px-Foto -- und es hat einen
sichtbaren Riss uebersehen (QA/0011, gemessen). Meldet der Mensch Schaden und
sieht das Modell keinen, bleibt das Texturteil stehen und die Abweichung wird
sichtbar vermerkt. Umgekehrt gilt das NICHT: sieht das Modell Schaden, wo die
Meldung "verkaufsfaehig" sagt, geht die Meldung an einen Menschen. Die
Asymmetrie ist Absicht -- das Bild darf eskalieren, aber die Aussage eines
Menschen, der die Ware angefasst hat, nicht abschwaechen.

**Modellkonfidenz kommt hier bewusst nicht vor.** Beim uebersehenen Riss war
das Modell zu 95 Prozent sicher. Eine Schwelle darauf waere Scheinsicherheit.
"""
from __future__ import annotations

from dataclasses import dataclass

# Dispositionen, die eine Aussage ueber den ARTIKEL treffen. `quarantine`
# fehlt mit Absicht: es sagt "sperren und pruefen" und damit nichts, dem ein
# Bild widersprechen koennte.
_CLAIMS_DAMAGE = frozenset({"scrap", "rework"})
_CLAIMS_SOUND = frozenset({"sellable"})

_SELLABLE_BUT_DAMAGED = (
    "Das Foto zeigt einen Schaden, die Meldung stuft die Ware als "
    "verkaufsfaehig ein."
)
_REPORTED_BUT_UNSEEN = (
    "Das Foto zeigt keinen sichtbaren Schaden, die Meldung nennt einen. "
    "Bitte stichprobenartig pruefen."
)


@dataclass(frozen=True)
class PhotoFinding:
    """Was die Bilder ergeben haben.

    `article`: "match" | "mismatch" | "unavailable"
    `damage`:  "damaged" | "intact" | "unavailable"
    `note`: Klartext fuer den Menschen, bereits fertig formuliert. Er ist das
        Einzige, was spaeter im Odoo-Formular steht, und darf auf keinem Pfad
        verloren gehen.
    """

    article: str
    damage: str
    note: str


@dataclass(frozen=True)
class Reconciled:
    """`contradiction` steuert ALLEIN die Verzweigung in n8n.

    Es steht nur dort auf True, wo die Meldung wirklich an einen Menschen
    gehen soll -- der vermerkte Widerspruch setzt es ausdruecklich nicht,
    sonst liefe er ueber denselben Zweig und wuerde doch blockieren.
    """

    contradiction: bool
    photo_analysis: str


def reconcile(*, disposition: str | None, finding: PhotoFinding) -> Reconciled:
    # Falscher Artikel schlaegt alles andere: ein Schaden am falschen Teil
    # sagt nichts ueber die gemeldete Ware, und ein Urteil ueber ein Foto, das
    # den Artikel nicht zeigt, ist wertlos.
    if finding.article == "mismatch":
        return Reconciled(contradiction=True, photo_analysis=finding.note)

    if disposition in _CLAIMS_SOUND and finding.damage == "damaged":
        return Reconciled(
            contradiction=True,
            photo_analysis=f"{finding.note}\n{_SELLABLE_BUT_DAMAGED}",
        )

    if disposition in _CLAIMS_DAMAGE and finding.damage == "intact":
        return Reconciled(
            contradiction=False,
            photo_analysis=f"{finding.note}\n{_REPORTED_BUT_UNSEEN}",
        )

    return Reconciled(contradiction=False, photo_analysis=finding.note)
