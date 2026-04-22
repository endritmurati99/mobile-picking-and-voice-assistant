"""Research-only shadow evaluation helpers for quality alerts."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


RESEARCH_CATEGORIES = ("damage", "shortage", "wrong_item", "unclear")
_NEGATION_RE = re.compile(r"\b(nicht|kein|keine|ohne|kaum|weder)\s+\S+", re.IGNORECASE)

_KEYWORDS: dict[str, tuple[tuple[str, int], ...]] = {
    "damage": (
        ("totalschaden", 8),
        ("zerstoert", 7),
        ("zerbrochen", 7),
        ("bruch", 6),
        ("gebrochen", 6),
        ("kaputt", 5),
        ("beschaedigt", 5),
        ("beschadigt", 5),
        ("defekt", 5),
        ("eingedrueckt", 5),
        ("gerissen", 5),
        ("riss", 4),
        ("kratzer", 3),
        ("delle", 3),
        ("feucht", 4),
        ("nass", 4),
        ("schimmel", 6),
        ("undicht", 4),
    ),
    "shortage": (
        ("fehlmenge", 8),
        ("fehlt", 6),
        ("fehlend", 6),
        ("zu wenig", 6),
        ("mindermenge", 7),
        ("untermenge", 7),
        ("nicht vorhanden", 5),
        ("nicht komplett", 4),
        ("unvollstaendig", 5),
        ("missing", 6),
    ),
    "wrong_item": (
        ("falscher artikel", 8),
        ("falsches produkt", 8),
        ("falsch geliefert", 7),
        ("falsche ware", 7),
        ("wrong item", 8),
        ("vertauscht", 6),
        ("anderer artikel", 6),
        ("anderes produkt", 6),
        ("nicht bestellt", 5),
        ("passt nicht", 4),
    ),
}

_UMLAUT_TRANSLATION = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
)


@dataclass(frozen=True)
class ShadowHeuristicResult:
    category: str
    confidence: float
    reason: str
    scores: dict[str, int]


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.translate(_UMLAUT_TRANSLATION)
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_photo_count(alert: dict[str, Any]) -> int:
    raw_value = alert.get("photo_count") or 0
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        return 0


def classify_quality_alert_shadow(alert: dict[str, Any]) -> ShadowHeuristicResult:
    description = _normalize_text(alert.get("description"))
    cleaned = _NEGATION_RE.sub("", description)
    scores = {category: 0 for category in RESEARCH_CATEGORIES if category != "unclear"}
    hits: dict[str, list[str]] = {category: [] for category in scores}

    for category, keywords in _KEYWORDS.items():
        for keyword, weight in keywords:
            if keyword in cleaned:
                scores[category] += weight
                hits[category].append(keyword)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_category, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    photo_count = _extract_photo_count(alert)
    desc_length = len(description)

    if top_score <= 0:
        confidence = 0.42 if desc_length else 0.35
        reason = "Keine eindeutigen Textsignale fuer damage, shortage oder wrong_item gefunden."
        return ShadowHeuristicResult(
            category="unclear",
            confidence=round(confidence, 2),
            reason=reason,
            scores=scores,
        )

    if second_score > 0 and top_score - second_score <= 1:
        reason = (
            "Mehrdeutige Textsignale gefunden: "
            + ", ".join(
                f"{category}={scores[category]}"
                for category in ("damage", "shortage", "wrong_item")
                if scores[category] > 0
            )
        )
        return ShadowHeuristicResult(
            category="unclear",
            confidence=0.51,
            reason=reason,
            scores=scores,
        )

    confidence = min(0.92, 0.52 + (top_score * 0.035))
    if desc_length >= 30:
        confidence += 0.05
    elif desc_length < 12:
        confidence -= 0.08
    if photo_count > 0 and top_category != "unclear":
        confidence += 0.03
    confidence = max(0.35, min(0.95, confidence))

    matched_terms = ", ".join(hits[top_category][:3]) or "keine"
    reason = f"Shadow-Heuristik ordnet als {top_category} ein auf Basis von: {matched_terms}."
    return ShadowHeuristicResult(
        category=top_category,
        confidence=round(confidence, 2),
        reason=reason,
        scores=scores,
    )
