"""Barcode-Validierung und -Matching."""


def validate_ean13(barcode: str) -> bool:
    """Prüft ob ein Barcode ein gültiger EAN-13 ist."""
    if len(barcode) != 13 or not barcode.isdigit():
        return False
    
    digits = [int(d) for d in barcode]
    checksum = sum(digits[i] * (1 if i % 2 == 0 else 3) for i in range(12))
    expected = (10 - checksum % 10) % 10
    return digits[12] == expected


def normalize_barcode(barcode: str) -> str:
    """Entfernt Whitespace und führende Nullen-Padding."""
    return barcode.strip()


def match_barcode(scanned: str, expected: str) -> bool:
    """Vergleicht gescannten Barcode mit erwartetem."""
    return normalize_barcode(scanned) == normalize_barcode(expected)
