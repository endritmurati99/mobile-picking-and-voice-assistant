"""Helpers for searching and formatting Obsidian vault context."""
from __future__ import annotations

import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VAULT_PATH = PROJECT_ROOT.parent / "Notzien"


def get_obsidian_base_path() -> Path:
    configured = os.getenv("OBSIDIAN_PATH")
    base_path = Path(configured) if configured else DEFAULT_VAULT_PATH
    if not base_path.is_absolute():
        base_path = (PROJECT_ROOT / base_path).resolve()
    return base_path


def tokenize_search_text(text: str) -> list[str]:
    normalized = re.sub(r"[^\w\s-]+", " ", str(text or "").lower())
    tokens = []
    for token in normalized.split():
        if len(token) >= 3 and token not in tokens:
            tokens.append(token)
    return tokens


def _iter_markdown_files(base_path: Path):
    if not base_path.exists():
        return
    for file_path in base_path.rglob("*.md"):
        if ".obsidian" in file_path.parts:
            continue
        yield file_path


def _extract_title(file_path: Path, content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return file_path.stem


def _extract_excerpt(content: str, tokens: list[str], max_chars: int = 240) -> str:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    lowered_lines = [line.lower() for line in lines]
    for index, line in enumerate(lowered_lines):
        if any(token in line for token in tokens):
            excerpt = lines[index]
            if len(excerpt) > max_chars:
                return excerpt[: max_chars - 1].rstrip() + "..."
            return excerpt
    excerpt = " ".join(lines[:2]).strip()
    if len(excerpt) > max_chars:
        return excerpt[: max_chars - 1].rstrip() + "..."
    return excerpt


def search_obsidian_notes(search_terms: list[str], limit: int = 3) -> list[dict]:
    tokens = []
    for term in search_terms:
        for token in tokenize_search_text(term):
            if token not in tokens:
                tokens.append(token)
    if not tokens:
        return []

    base_path = get_obsidian_base_path()
    hits: list[dict] = []
    for file_path in _iter_markdown_files(base_path):
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="utf-8", errors="ignore")

        lowered_content = content.lower()
        lowered_path = str(file_path.relative_to(base_path)).lower()
        score = 0
        for token in tokens:
            score += lowered_content.count(token)
            if token in lowered_path:
                score += 3
        if score <= 0:
            continue

        hits.append(
            {
                "title": _extract_title(file_path, content),
                "path": str(file_path.relative_to(base_path)).replace("\\", "/"),
                "excerpt": _extract_excerpt(content, tokens),
                "score": score,
            }
        )

    hits.sort(key=lambda item: (-item["score"], item["path"]))
    return hits[:limit]


def format_obsidian_hits(hits: list[dict], max_chars: int = 320) -> str:
    if not hits:
        return ""

    parts: list[str] = []
    total_chars = 0
    for hit in hits:
        fragment = f"{hit['title']}: {hit['excerpt']}"
        if parts:
            fragment = f" | {fragment}"
        if total_chars + len(fragment) > max_chars:
            break
        parts.append(fragment.strip(" |"))
        total_chars += len(fragment)
    return " | ".join(parts)
