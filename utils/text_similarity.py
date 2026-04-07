"""
Lightweight text similarity helpers for OCR benchmarking.
"""
import re
from difflib import SequenceMatcher


def normalize_text_for_similarity(text: str) -> str:
    """Normalize text to reduce formatting noise before comparison."""
    if not text:
        return ""

    normalized = text.lower()
    normalized = re.sub(r"[`*_>#\-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def calculate_similarity_score(reference_text: str, candidate_text: str) -> float:
    """Return a ratio in [0, 1] using difflib SequenceMatcher."""
    reference = normalize_text_for_similarity(reference_text)
    candidate = normalize_text_for_similarity(candidate_text)

    if not reference and not candidate:
        return 1.0
    if not reference or not candidate:
        return 0.0

    return SequenceMatcher(None, reference, candidate).ratio()
