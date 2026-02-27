from backend.memory.conflicts import is_semantic_contradiction


def test_detects_preference_contradiction_with_negation():
    existing = "Julien prefers writing Python services for backend APIs."
    candidate = "Julien does not prefer writing Python services for backend APIs."
    assert is_semantic_contradiction(existing, candidate) is True


def test_no_contradiction_when_unrelated_topics():
    existing = "Julien prefers backend work with FastAPI and SQL databases."
    candidate = "The user plans a family trip to Lisbon next summer."
    assert is_semantic_contradiction(existing, candidate) is False
