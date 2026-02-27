from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Optional

DECAY_PROFILES = {
    "permanent",
    "stable",
    "semi-stable",
    "volatile",
    "event-based",
}

_PERMANENT_HINTS = (
    "name is",
    "born",
    "citizen",
    "identity",
    "email",
    "phone",
)

_VOLATILE_HINTS = (
    "today",
    "tomorrow",
    "asap",
    "urgent",
    "for now",
    "temporary",
    "remind",
    "todo",
    "to do",
    "this afternoon",
    "this evening",
    "tonight",
)

_SEMI_STABLE_HINTS = (
    "framework",
    "library",
    "stack",
    "tooling",
    "sdk",
    "api",
    "language",
    "database",
)

_SEMI_STABLE_CATEGORIES = {"skills", "projects"}

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _with_tz(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _at_default_time(value: datetime) -> datetime:
    return value.replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


def parse_event_date(content: str, now: Optional[datetime] = None) -> Optional[datetime]:
    now = _with_tz(now or datetime.now(timezone.utc))
    text = content.strip()
    lowered = text.lower()

    if "tomorrow" in lowered:
        return _at_default_time(now + timedelta(days=1))
    if "today" in lowered:
        return _at_default_time(now)
    if "next week" in lowered:
        return _at_default_time(now + timedelta(days=7))

    # ISO: 2026-03-15
    iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        try:
            return _at_default_time(datetime(year, month, day, tzinfo=timezone.utc))
        except ValueError:
            pass

    # US-style: 03/15/2026
    us_match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if us_match:
        month, day, year = map(int, us_match.groups())
        try:
            return _at_default_time(datetime(year, month, day, tzinfo=timezone.utc))
        except ValueError:
            pass

    # Month name: March 15, 2026 | Mar 15
    month_match = re.search(
        r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:,?\s+(\d{4}))?\b",
        text,
    )
    if month_match:
        month_txt, day_txt, year_txt = month_match.groups()
        month = _MONTHS.get(month_txt.lower())
        if month:
            day = int(day_txt)
            year = int(year_txt) if year_txt else now.year
            try:
                dt = datetime(year, month, day, tzinfo=timezone.utc)
                if dt < now and year_txt is None:
                    dt = datetime(year + 1, month, day, tzinfo=timezone.utc)
                return _at_default_time(dt)
            except ValueError:
                pass

    return None


def infer_decay_profile(
    *,
    content: str,
    category: str,
    level: str,
    now: Optional[datetime] = None,
) -> dict:
    now = _with_tz(now or datetime.now(timezone.utc))
    lowered = content.lower()

    event_date = parse_event_date(content, now=now)
    if event_date:
        return {
            "decay_profile": "event-based",
            "expires_at": event_date + timedelta(days=1),
            "needs_review": False,
            "review_due_at": None,
            "event_date": event_date,
        }

    if any(hint in lowered for hint in _PERMANENT_HINTS):
        return {
            "decay_profile": "permanent",
            "expires_at": None,
            "needs_review": False,
            "review_due_at": None,
            "event_date": None,
        }

    if level == "working" or any(hint in lowered for hint in _VOLATILE_HINTS):
        return {
            "decay_profile": "volatile",
            "expires_at": now + timedelta(hours=24),
            "needs_review": False,
            "review_due_at": None,
            "event_date": None,
        }

    if category in _SEMI_STABLE_CATEGORIES or any(hint in lowered for hint in _SEMI_STABLE_HINTS):
        return {
            "decay_profile": "semi-stable",
            "expires_at": None,
            "needs_review": False,
            "review_due_at": now + timedelta(days=60),
            "event_date": None,
        }

    profile = "stable"
    if level == "semantic":
        profile = "stable"
    elif level == "episodic":
        profile = "semi-stable"

    return {
        "decay_profile": profile,
        "expires_at": None,
        "needs_review": False,
        "review_due_at": now + timedelta(days=60) if profile == "semi-stable" else None,
        "event_date": None,
    }


def normalize_decay_profile(value: Optional[str]) -> str:
    if value in DECAY_PROFILES:
        return value
    return "stable"
