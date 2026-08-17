FROM python:3.12-slim

WORKDIR /app

# wget fuer Modell-Download; espeak-ng fuer Phonemisierung
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# piper-tts enthaelt onnxruntime + piper-phonemize als Wheels — kein Binary noetig
RUN pip install --no-cache-dir piper-tts fastapi uvicorn pydantic

# Deutsches Sprachmodell (thorsten-MEDIUM, ~63 MB)
#
# Vorher lief hier thorsten-HIGH. Piper bietet vier Qualitaetsstufen
# (x_low/low/medium/high); high ist die langsamste. Im Container gemessen,
# gleicher Satz, je 5 Laeufe nach Warmup:
#   thorsten-high    1857 ms   22050 Hz   <- war eingestellt
#   thorsten-medium   280 ms   22050 Hz   <- jetzt
#   thorsten-low      215 ms   16000 Hz
#   kerstin-low       220 ms   16000 Hz
# Medium ist 6,6x schneller bei identischer Samplerate und demselben Sprecher.
# Damit bleibt die natuerliche Stimme erhalten, ohne dass kurze Ansagen die
# Sprachrunde blockieren -- die Alternative waere die Browser-Stimme gewesen
# (80 ms, aber deutlich robotischer).
# HuggingFace liefert stabilen Download ohne GitHub-Redirect-Probleme
RUN mkdir -p /models && \
    wget -q --show-progress \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx" \
      -O /models/de.onnx && \
    wget -q \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json" \
      -O /models/de.onnx.json

COPY server.py .

EXPOSE 5500
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5500", "--log-level", "info"]
