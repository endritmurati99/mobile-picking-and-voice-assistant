"""Pydantic Models für Voice I/O."""
from pydantic import BaseModel


class TTSRequest(BaseModel):
    text: str
    lang: str = "de-DE"
