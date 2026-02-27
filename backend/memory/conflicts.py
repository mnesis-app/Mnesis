from __future__ import annotations

import re
from typing import Iterable

_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "to",
    "for",
    "and",
    "of",
    "in",
    "on",
    "at",
    "with",
    "my",
    "your",
    "their",
    "his",
    "her",
    "this",
    "that",
    "it",
    "be",
    "as",
    "by",
    "from",
}

_NEGATIONS = (" not ", " never ", " no ", "n't ")
_POSITIVE_PREFS = ("prefer", "like", "love", "enjoy", "use")
_NEGATIVE_PREFS = ("dislike", "hate", "avoid", "refuse", "never use", "don't like")


def _normalize_text(value: str) -> str:
    clean = re.sub(r"\s+", " ", value.strip().lower())
    return f" {clean} "


def _keywords(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9][a-z0-9_\-]+", value.lower())
    return {t for t in tokens if len(t) > 2 and t not in _STOPWORDS}


def _overlap_ratio(a: Iterable[str], b: Iterable[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    inter = sa.intersection(sb)
    return len(inter) / float(min(len(sa), len(sb)))


def _polarity_score(text: str) -> int:
    lowered = text.lower()
    score = 0
    if any(k in lowered for k in _POSITIVE_PREFS):
        score += 1
    if any(k in lowered for k in _NEGATIVE_PREFS):
        score -= 1
    if any(k in f" {lowered} " for k in _NEGATIONS):
        score -= 1
    return score


def is_semantic_contradiction(existing: str, candidate: str) -> bool:
    if not existing or not candidate:
        return False

    norm_existing = _normalize_text(existing)
    norm_candidate = _normalize_text(candidate)
    if norm_existing == norm_candidate:
        return False

    kw_existing = _keywords(existing)
    kw_candidate = _keywords(candidate)
    overlap = _overlap_ratio(kw_existing, kw_candidate)

    if overlap < 0.30:
        return False

    has_negation_existing = any(n in norm_existing for n in _NEGATIONS)
    has_negation_candidate = any(n in norm_candidate for n in _NEGATIONS)
    if has_negation_existing != has_negation_candidate:
        return True

    polarity_existing = _polarity_score(existing)
    polarity_candidate = _polarity_score(candidate)
    if polarity_existing * polarity_candidate < 0:
        return True

    return False
