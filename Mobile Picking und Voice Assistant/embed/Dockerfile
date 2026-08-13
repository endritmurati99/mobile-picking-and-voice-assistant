# Bildeinbettung fuer den Artikelabgleich.
#
# Warum ein eigener Dienst und nicht ein paar Zeilen im Backend: das Backend
# haengt an `core-net`, und beide Netze sind `internal: true` -- kein Weg nach
# draussen. Modellgewichte muessen also beim BAUEN hineinkommen, und der Bau
# ist der einzige Moment mit Netz. Derselbe Grund, aus dem `whisper` seinen
# Cache in einem Volume haelt und mit HF_HUB_OFFLINE=1 laeuft.
FROM python:3.12-slim

# Torch ohne CUDA: das Bild waere sonst rund 2,5 GB groesser, und diese
# Maschine hat ohnehin keinen nutzbaren Grafikbeschleuniger (Ollama laeuft
# gemessen zu 100 % auf der CPU).
RUN pip install --no-cache-dir \
      torch torchvision --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir \
      "transformers>=4.44" pillow numpy "fastapi>=0.110" "uvicorn[standard]>=0.29"

# Gewichte ins Bild backen. Ohne das startet der Dienst im internen Netz nicht:
# `from_pretrained` fragt sonst die Revision online ab und scheitert, auch wenn
# ein Cache vorhanden waere.
ENV HF_HOME=/modelle
RUN python -c "\
from transformers import AutoImageProcessor, AutoModel; \
AutoImageProcessor.from_pretrained('facebook/dinov2-base'); \
AutoModel.from_pretrained('facebook/dinov2-base')"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    EINBETT_MODELL=facebook/dinov2-base \
    OMP_NUM_THREADS=4

COPY server.py /app/server.py
WORKDIR /app

# Ein Arbeiter. Der Dienst ist rechengebunden; ein zweiter wuerde sich mit dem
# ersten um dieselben Kerne pruegeln und beide langsamer machen -- derselbe
# Effekt, der am 2026-08-07 zwei gleichzeitige Bewertungen von 8 s auf 3 min
# getrieben hat.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
