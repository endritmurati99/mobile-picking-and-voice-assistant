"""Laufzeit-Patch fuer den gepinnten openai-whisper-asr-webservice-Container.

Warum ueberhaupt ein Patch und kein eigenes Image: der Digest in docker-compose.yml
ist bewusst festgenagelt, und das Modell liegt in einem Volume-Cache hinter einem
`internal`-Netz. Ein Rebuild wuerde beides anfassen. Dieser Patch wird stattdessen
per PYTHONPATH=/patch eingehaengt -- CPython importiert `sitecustomize` beim Start
automatisch, bevor irgendein Anwendungscode laeuft.

Er behebt den groessten gemessenen Latenzposten der Sprachsteuerung:

  faster-whisper padded JEDE Eingabe auf ein 30-Sekunden-Mel-Fenster. `transcribe.py`
  ruft `pad_or_trim(segment)` ohne Laengenargument auf, Default `length=3000` Frames
  (audio.py). Instrumentierung von `WhisperModel.encode` zeigt fuer 0,9 s, 1,8 s und
  6,1 s Audio immer dieselbe Form (80, 3000). Der Encoder-Pass allein kostete auf
  4 vCPU 1171 ms und damit rund 80 % der gesamten Transkriptionszeit -- ein
  0,3-Sekunden-Stilleclip brauchte bereits 1245 ms, ohne ein einziges Wort zu
  dekodieren. Da Self-Attention quadratisch in der Sequenzlaenge ist, ist der Effekt
  einer Fensterverkleinerung ueberlinear: 30 s -> 1171 ms, 10 s -> 180 ms, 5 s -> 72 ms.

Zwei Eingriffe, die NUR GEMEINSAM sinnvoll sind:

  1. Adaptives Fenster: Audiolaenge + 2 s Rand, Mindestens 5 s, hoechstens die
     unveraenderten 30 s.
  2. Dekodier-Parameter erzwingen (beam_size=1, without_timestamps, feste Temperatur,
     kein Kontextuebertrag, n-Gram-Sperre).

Ohne (2) erzeugt (1) Wiederholungsschleifen: im Test lieferte das verkleinerte Fenster
bei 1,2 s Vorlaufstille "Bestaetigen, bestaetigen, bestaetigen." und war mit 1528 ms
sogar langsamer als der Ausgangszustand. Der Grund ist der Temperatur-Fallback von
Whisper, der bei schlechter Kompressionsrate die Dekodierung mehrfach wiederholt.
Wer nur die Haelfte uebernimmt, tauscht Latenz gegen Halluzinationen.

`beam_size` muss hier erzwungen werden, weil der Webservice den Wert in
`app/asr_models/faster_whisper_engine.py` hart verdrahtet und keinen Parameter
dafuer anbietet.

Gemessen (small/int8, 4 vCPU): 1418 -> 257 ms bei 0,9 s Audio, Transkript unveraendert.

Fail-open: jeder Fehler hier laesst den Dienst unveraendert weiterlaufen. Ein
kaputter Patch darf die Spracherkennung nicht abschalten.
"""

import logging
import math
import os

_log = logging.getLogger("whisper-window-patch")

# Nur der Encoder-Anteil profitiert; darunter dominiert der Decoder und das
# Fenster zu schrumpfen bringt nichts mehr, schneidet aber Wortanfaenge ab.
_MIN_FRAMES = 500      # 5 s -- Untergrenze, schuetzt kurze Befehle vor Abschnitt
_MAX_FRAMES = 3000     # 30 s -- unveraenderte Obergrenze von faster-whisper
_TAIL_FRAMES = 200     # 2 s Rand hinter dem Sprachende

_ENABLED = os.environ.get("WHISPER_ADAPTIVE_WINDOW", "1") not in ("0", "false", "False")


def _install() -> None:
    from faster_whisper import transcribe as _transcribe_module
    from faster_whisper.transcribe import WhisperModel

    _original_pad_or_trim = _transcribe_module.pad_or_trim
    _original_transcribe = WhisperModel.transcribe

    def _adaptive_pad_or_trim(array, length=None, *args, **kwargs):
        # `length=None` heisst: der Aufrufer hat keine Laenge vorgegeben -- genau
        # der Fall in transcribe.py, der das 30-s-Fenster erzwingt. Gibt ein
        # Aufrufer eine Laenge an, wird sie respektiert.
        if length is None:
            try:
                frames = array.shape[-1]
            except Exception:
                frames = _MAX_FRAMES
            wanted = math.ceil((frames + _TAIL_FRAMES) / 100) * 100
            length = max(_MIN_FRAMES, min(_MAX_FRAMES, wanted))
        return _original_pad_or_trim(array, length, *args, **kwargs)

    # WICHTIG: das Attribut im Modul `transcribe` ersetzen, nicht in `audio`.
    # transcribe.py bindet den Namen per `from ... import pad_or_trim`, eine
    # Ersetzung in audio.py wuerde deshalb ins Leere laufen.
    _transcribe_module.pad_or_trim = _adaptive_pad_or_trim

    def _fast_transcribe(self, audio, **kwargs):
        kwargs["beam_size"] = 1
        kwargs["best_of"] = 1
        kwargs["without_timestamps"] = True
        kwargs["temperature"] = [0.0]
        kwargs["condition_on_previous_text"] = False
        kwargs["no_repeat_ngram_size"] = 3
        return _original_transcribe(self, audio, **kwargs)

    WhisperModel.transcribe = _fast_transcribe
    _log.warning(
        "whisper-window-patch aktiv: adaptives Mel-Fenster %d-%d Frames, beam_size=1",
        _MIN_FRAMES,
        _MAX_FRAMES,
    )


if _ENABLED:
    try:
        _install()
    except Exception as exc:  # noqa: BLE001 - fail-open, siehe Modul-Docstring
        _log.warning("whisper-window-patch NICHT aktiv (%s) - Dienst laeuft unveraendert", exc)
