"""Ein Test je Zeile der Widerspruchstabelle aus dem Entwurf.

Kein Modellaufruf, kein Netz, keine Attrappe: die Regel muss ohne all das
pruefbar sein, sonst ist sie keine Regel. Genau darum entscheidet hier Python
und nicht ein drittes Modell -- ein Modell, das sich aus einem Widerspruch
herausreden kann, waere keine Pruefung.
"""
from app.services.assessment_reconciliation import PhotoFinding, reconcile

ALLE_DISPOSITIONEN = ("scrap", "rework", "quarantine", "sellable")


def _finding(article="match", damage="intact", note="Bildbefund."):
    return PhotoFinding(article=article, damage=damage, note=note)


def test_wrong_article_always_goes_to_a_human():
    """QA/0014: Text 'Verpackung defekt' -> sellable, Foto ein Hund. Egal was
    der Text sagt -- wenn das Foto den Artikel nicht zeigt, ist die ganze
    Meldung fragwuerdig, nicht nur ihr Urteil."""
    for disposition in ALLE_DISPOSITIONEN:
        result = reconcile(
            disposition=disposition,
            finding=_finding(
                article="mismatch",
                note="Foto zeigt nicht den gemeldeten Artikel: ein Hund am Strand.",
            ),
        )
        assert result.contradiction is True, disposition
        assert "Hund" in result.photo_analysis


def test_damage_seen_and_damage_reported_confirms():
    for disposition in ("scrap", "rework"):
        result = reconcile(disposition=disposition, finding=_finding(damage="damaged"))
        assert result.contradiction is False, disposition
        assert result.photo_analysis == "Bildbefund."


def test_damage_seen_but_reported_sellable_goes_to_a_human():
    """Die einzige Richtung, in der das Bild eskalieren DARF: es sieht einen
    Schaden, den die Meldung nicht nennt."""
    result = reconcile(disposition="sellable", finding=_finding(damage="damaged"))
    assert result.contradiction is True
    assert "verkaufsfähig" in result.photo_analysis


def test_nothing_seen_and_nothing_reported_confirms():
    result = reconcile(disposition="sellable", finding=_finding(damage="intact"))
    assert result.contradiction is False


def test_damage_reported_but_nothing_seen_is_noted_not_blocked():
    """Die eine bewusst entschiedene Zeile. Der Kommissionierer hatte den
    Artikel in der Hand, das Modell nur ein 512-px-Foto -- und es hat einen
    sichtbaren Riss uebersehen. Das Texturteil bleibt, die Abweichung wird
    sichtbar."""
    for disposition in ("scrap", "rework"):
        result = reconcile(disposition=disposition, finding=_finding(damage="intact"))
        assert result.contradiction is False, disposition
        assert "keinen sichtbaren Schaden" in result.photo_analysis
        assert "stichprobenartig" in result.photo_analysis


def test_quarantine_is_never_contradicted():
    """quarantine trifft keine Aussage ueber den Artikel, sondern verlangt
    ohnehin einen Menschen. Es gibt nichts zu widersprechen."""
    for damage in ("damaged", "intact", "unavailable"):
        result = reconcile(disposition="quarantine", finding=_finding(damage=damage))
        assert result.contradiction is False, damage


def test_missing_reference_image_only_drops_the_article_check():
    """23 von 70 Produkten haben kein Katalogbild. Die Schadenspruefung laeuft
    trotzdem und zaehlt."""
    result = reconcile(
        disposition="sellable",
        finding=_finding(
            article="unavailable",
            damage="damaged",
            note="Artikelabgleich entfaellt: kein Katalogbild hinterlegt.",
        ),
    )
    assert result.contradiction is True
    assert "kein Katalogbild" in result.photo_analysis


def test_failed_photo_check_leaves_the_text_verdict_standing():
    """Ein Ausfall der Zweitmeinung darf die Erstmeinung nicht loeschen."""
    result = reconcile(
        disposition="scrap",
        finding=PhotoFinding(
            article="unavailable",
            damage="unavailable",
            note="Bildprüfung nicht möglich: Zeitueberschreitung.",
        ),
    )
    assert result.contradiction is False
    assert "nicht möglich" in result.photo_analysis


def test_no_text_verdict_never_contradicts():
    """Ohne Texturteil gibt es nichts zu widersprechen -- der Workflow meldet
    dann ohnehin review_required, weil llm_ok false ist."""
    for damage in ("damaged", "intact"):
        result = reconcile(disposition=None, finding=_finding(damage=damage))
        assert result.contradiction is False, damage


def test_wrong_article_beats_everything_else():
    """Wenn beides zutrifft -- falscher Artikel UND sichtbarer Schaden --,
    zaehlt der falsche Artikel. Ein Schaden am falschen Teil sagt nichts ueber
    die gemeldete Ware."""
    result = reconcile(
        disposition="sellable",
        finding=_finding(article="mismatch", damage="damaged", note="Falscher Artikel."),
    )
    assert result.contradiction is True
    assert result.photo_analysis.startswith("Falscher Artikel.")


# ---------------------------------------------------------------------------
# Das Texturteil ueberlebt den Widerspruch -- als Text, nicht als Einstufung
# ---------------------------------------------------------------------------


def test_a_contradicted_text_verdict_stays_readable():
    """Gemessen am 2026-08-09 (Ausfuehrung 46 zu QA/0227): das Textmodell hatte
    `sellable` mit Konfidenz 1.0 geurteilt, der Artikelabgleich meldete
    faelschlich `mismatch` -- und weil `quality_alert.api_apply_assessment` bei
    `review_required` Einstufung, Konfidenz, Begruendung, Provider und Modell
    leert, war das Urteil danach nirgends mehr nachlesbar.

    Es darf nicht in `ai_disposition` landen: dort saehe es aus wie eine
    geltende Einstufung neben "Manuelle Pruefung noetig". Es gehoert in den
    Klartext, den ein Mensch liest."""
    result = reconcile(
        disposition="sellable",
        confidence=1.0,
        summary="Verpackung leicht gedrueckt.",
        finding=_finding(article="mismatch", note="Foto zeigt nicht den Artikel."),
    )
    assert result.contradiction is True
    assert "Foto zeigt nicht den Artikel." in result.photo_analysis
    assert "sellable" in result.photo_analysis
    assert "1.0" in result.photo_analysis or "1,0" in result.photo_analysis
    assert "Verpackung leicht gedrueckt." in result.photo_analysis


def test_the_preserved_verdict_says_it_is_not_in_force():
    """Ohne diesen Zusatz liest sich die Zeile wie ein geltendes Urteil. Sie
    steht aber genau dort, wo die Kette dem Urteil NICHT gefolgt ist."""
    result = reconcile(
        disposition="sellable",
        confidence=0.9,
        summary="Nur Kratzer.",
        finding=_finding(damage="damaged", note="Schaden sichtbar."),
    )
    assert result.contradiction is True
    assert "nicht wirksam" in result.photo_analysis


def test_the_verdict_is_preserved_on_the_damage_contradiction_too():
    """Derselbe Datenverlust trifft den zweiten Widerspruchspfad: Meldung sagt
    verkaufsfähig, Foto zeigt Schaden."""
    result = reconcile(
        disposition="sellable",
        confidence=0.8,
        summary="Karton gedrueckt.",
        finding=_finding(damage="damaged", note="Schaden sichtbar."),
    )
    assert result.contradiction is True
    assert "Karton gedrueckt." in result.photo_analysis


def test_no_verdict_line_without_a_contradiction():
    """Wo die Kette dem Urteil folgt, steht es in `ai_disposition` -- dann
    waere dieselbe Angabe im Klartext nur Rauschen."""
    result = reconcile(
        disposition="scrap",
        confidence=0.95,
        summary="Ware unbrauchbar.",
        finding=_finding(damage="damaged", note="Schaden sichtbar."),
    )
    assert result.contradiction is False
    assert result.photo_analysis == "Schaden sichtbar."


def test_no_verdict_line_without_a_verdict():
    """Kein Texturteil, nichts zu erhalten -- und kein leerer Satzrumpf."""
    result = reconcile(
        disposition=None,
        finding=_finding(article="mismatch", note="Foto zeigt nicht den Artikel."),
    )
    assert result.photo_analysis == "Foto zeigt nicht den Artikel."


def test_the_vermerk_path_keeps_its_hint_and_adds_nothing():
    """Der vermerkte Widerspruch (Mensch meldet Schaden, Modell sieht keinen)
    setzt `contradiction` nicht -- das Urteil bleibt wirksam und gehoert
    deshalb nicht als "nicht wirksam" in den Klartext."""
    result = reconcile(
        disposition="scrap",
        confidence=0.9,
        summary="Ware unbrauchbar.",
        finding=_finding(damage="intact", note="Kein Schaden sichtbar."),
    )
    assert result.contradiction is False
    assert "nicht wirksam" not in result.photo_analysis
    assert "Bitte stichprobenartig prüfen." in result.photo_analysis


def test_the_note_always_survives():
    """Der Klartext des Bildbefunds darf nie verloren gehen -- er ist das
    Einzige, was ein Mensch spaeter zu sehen bekommt."""
    for article in ("match", "mismatch", "unavailable"):
        for damage in ("damaged", "intact", "unavailable"):
            for disposition in ALLE_DISPOSITIONEN + (None,):
                result = reconcile(
                    disposition=disposition,
                    finding=_finding(article=article, damage=damage, note="MERKMAL"),
                )
                assert "MERKMAL" in result.photo_analysis, (
                    article, damage, disposition
                )
