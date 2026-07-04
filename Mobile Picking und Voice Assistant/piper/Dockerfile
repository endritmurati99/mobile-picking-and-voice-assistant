FROM python:3.12-slim

WORKDIR /app

# wget fuer Modell-Download; espeak-ng fuer Phonemisierung
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# piper-tts enthaelt onnxruntime + piper-phonemize als Wheels — kein Binary noetig
RUN pip install --no-cache-dir piper-tts fastapi uvicorn pydantic

# Deutsches Sprachmodell (thorsten-high, ~65 MB)
# HuggingFace liefert stabilen Download ohne GitHub-Redirect-Probleme
RUN mkdir -p /models && \
    wget -q --show-progress \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx" \
      -O /models/de.onnx && \
    wget -q \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx.json" \
      -O /models/de.onnx.json

COPY server.py .

EXPOSE 5500
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5500", "--log-level", "info"]
