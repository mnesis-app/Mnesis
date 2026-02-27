from __future__ import annotations

from collections import defaultdict
import re
from typing import Dict, Tuple

DOMAIN_CATEGORIES: Dict[str, list[str]] = {
    "code": ["skills", "projects", "working"],
    "business": ["preferences", "relationships", "history", "working"],
    "personal": ["identity", "preferences", "working"],
    "casual": ["identity", "working"],
}

_DOMAIN_HINTS: Dict[str, tuple[str, ...]] = {
    "code": (
        "python",
        "javascript",
        "typescript",
        "api",
        "bug",
        "debug",
        "stacktrace",
        "repo",
        "pull request",
        "test",
        "build",
        "deploy",
        "function",
        "class",
    ),
    "business": (
        "client",
        "customer",
        "revenue",
        "roadmap",
        "market",
        "sales",
        "meeting",
        "quarter",
        "okr",
        "strategy",
        "pricing",
    ),
    "personal": (
        "family",
        "partner",
        "health",
        "habit",
        "goal",
        "birthday",
        "travel",
        "home",
        "preference",
        "routine",
    ),
    "casual": (
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank you",
        "lol",
        "how are you",
        "what's up",
        "weather",
    ),
}


def classify_query_domain(query: str) -> Tuple[str, Dict[str, float]]:
    lowered = query.strip().lower()
    scores: Dict[str, float] = defaultdict(float)

    for domain, hints in _DOMAIN_HINTS.items():
        for hint in hints:
            if hint in lowered:
                scores[domain] += 1.0

    tokens = re.findall(r"[a-z0-9][a-z0-9_\-]+", lowered)
    token_count = len(tokens)
    if token_count <= 5:
        scores["casual"] += 0.3

    if lowered.endswith("?") and token_count <= 8:
        scores["casual"] += 0.25

    if "my " in lowered:
        scores["personal"] += 0.2

    if "error" in lowered or "exception" in lowered:
        scores["code"] += 0.5

    if not scores:
        return "casual", {k: 0.0 for k in DOMAIN_CATEGORIES}

    # Ensure all domains are represented.
    for domain in DOMAIN_CATEGORIES:
        scores.setdefault(domain, 0.0)

    detected = max(scores.items(), key=lambda kv: kv[1])[0]
    return detected, dict(scores)


def categories_for_domain(domain: str) -> list[str]:
    return DOMAIN_CATEGORIES.get(domain, DOMAIN_CATEGORIES["casual"])
