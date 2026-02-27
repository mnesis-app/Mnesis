from datetime import datetime, timezone

from backend.memory.decay import infer_decay_profile, parse_event_date


def test_parse_event_date_from_iso():
    now = datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc)
    parsed = parse_event_date("Project review on 2026-03-10", now=now)
    assert parsed is not None
    assert parsed.year == 2026 and parsed.month == 3 and parsed.day == 10


def test_infer_decay_volatile_for_working_level():
    now = datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc)
    decay = infer_decay_profile(
        content="Temporary context for today only, revisit quickly.",
        category="working",
        level="working",
        now=now,
    )
    # Date-specific working memories can be treated as event-based.
    assert decay["decay_profile"] in {"volatile", "event-based"}
    assert decay["expires_at"] is not None


def test_infer_decay_semi_stable_for_skills():
    now = datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc)
    decay = infer_decay_profile(
        content="Julien uses FastAPI and TypeScript for backend tooling.",
        category="skills",
        level="semantic",
        now=now,
    )
    assert decay["decay_profile"] == "semi-stable"
    assert decay["review_due_at"] is not None


def test_parse_event_date_invalid_returns_none():
    now = datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc)
    parsed = parse_event_date("No explicit date in this sentence.", now=now)
    assert parsed is None
