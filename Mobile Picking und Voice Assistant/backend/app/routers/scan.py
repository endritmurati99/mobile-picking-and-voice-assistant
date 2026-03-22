"""
Barcode-Validierungs-Endpoint.
Schnell-Validierung eines gescannten Barcodes gegen einen erwarteten Wert.
Wird vom PWA-Frontend nach HID-Scan aufgerufen, bevor confirm-line ausgelöst wird.
"""
from fastapi import APIRouter

router = APIRouter()


@router.post("/scan/validate")
async def validate_barcode(barcode: str, expected_barcode: str = ""):
    """
    Gescannten Barcode gegen erwarteten Barcode validieren.

    Wenn expected_barcode leer ist, gilt der Scan immer als gültig
    (Freitextmodus — keine Vorauswahl).
    """
    if not expected_barcode:
        return {
            "match": True,
            "barcode": barcode,
            "expected": expected_barcode,
            "message": "Kein Erwartungswert — Scan akzeptiert",
        }

    match = barcode.strip() == expected_barcode.strip()
    return {
        "match": match,
        "barcode": barcode,
        "expected": expected_barcode,
        "message": "Barcode korrekt." if match else f"Falscher Barcode. Erwartet: {expected_barcode}",
    }
