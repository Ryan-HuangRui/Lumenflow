"""Deterministic local search over Lumenflow style cards."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


STYLE_ID_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")
MAX_STYLE_CARD_BYTES = 2 * 1024 * 1024


class StyleLibraryError(RuntimeError):
    """Raised when a style catalog is ambiguous or unsafe to read."""


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_text_values(item))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            if key not in {"raw_profiles", "recipe_sources", "source", "provenance"}:
                result.extend(_text_values(item))
        return result
    return []


def _terms(value: str) -> set[str]:
    return {
        term.lower()
        for term in re.findall(r"[\w\-]+", value, flags=re.UNICODE)
        if term.strip()
    }


class StyleLibrary:
    """Load immutable JSON cards and return compact semantic matches."""

    def __init__(self, roots: list[Path]) -> None:
        self._cards: dict[str, dict[str, Any]] = {}
        self._paths: dict[str, Path] = {}
        for root_value in roots:
            root = Path(root_value)
            if not root.exists():
                continue
            if root.is_symlink() or not root.is_dir():
                raise StyleLibraryError(f"Style root must be a regular directory: {root}")
            for path in sorted(root.rglob("*.json")):
                if path.is_symlink() or not path.is_file():
                    continue
                if path.stat().st_size > MAX_STYLE_CARD_BYTES:
                    raise StyleLibraryError(f"Style card is too large: {path}")
                try:
                    card = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as error:
                    raise StyleLibraryError(f"Invalid style card: {path}: {error}") from error
                if not isinstance(card, dict) or "style_id" not in card:
                    continue
                style_id = card["style_id"]
                if not isinstance(style_id, str) or not STYLE_ID_PATTERN.fullmatch(style_id):
                    raise StyleLibraryError(f"Invalid style_id in {path}")
                if style_id in self._cards:
                    raise StyleLibraryError(
                        f"Duplicate style_id {style_id!r}: {self._paths[style_id]} and {path}"
                    )
                self._cards[style_id] = card
                self._paths[style_id] = path

    def get(self, style_id: str) -> dict[str, Any]:
        if not isinstance(style_id, str) or not STYLE_ID_PATTERN.fullmatch(style_id):
            raise StyleLibraryError("style_id is invalid")
        try:
            return copy.deepcopy(self._cards[style_id])
        except KeyError:
            raise StyleLibraryError(f"Unknown style_id: {style_id}") from None

    def search(self, *, query: str, purpose: str = "", limit: int = 5) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise StyleLibraryError("limit must be between 1 and 20")
        query_terms = _terms(f"{query} {purpose}")
        if not query_terms:
            raise StyleLibraryError("query or purpose must contain searchable text")
        matches: list[dict[str, Any]] = []
        for style_id, card in self._cards.items():
            searchable = " ".join(_text_values(card))
            card_terms = _terms(searchable)
            matched = sorted(query_terms & card_terms)
            phrase_bonus = 1.0 if query.strip().lower() in searchable.lower() else 0.0
            score = len(matched) / len(query_terms) + phrase_bonus
            if score <= 0:
                continue
            matches.append(
                {
                    "style_id": style_id,
                    "style_name": card.get("style_name", style_id),
                    "intent": card.get("intent", ""),
                    "suitable_scenes": copy.deepcopy(card.get("suitable_scenes", [])),
                    "matched_terms": matched,
                    "retrieval_score": round(score, 4),
                    "resource_uri": f"lumenflow://styles/{style_id}",
                }
            )
        matches.sort(key=lambda item: (-item["retrieval_score"], item["style_id"]))
        return matches[:limit]
