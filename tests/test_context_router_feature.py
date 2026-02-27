from backend.memory.context_router import categories_for_domain, classify_query_domain


def test_classifies_code_domain():
    domain, scores = classify_query_domain("Can you debug this Python stacktrace from my API test suite?")
    assert domain == "code"
    assert scores["code"] > scores["casual"]


def test_classifies_business_domain():
    domain, _ = classify_query_domain("Prepare a roadmap update for this quarter's client revenue review")
    assert domain == "business"


def test_classifies_personal_domain():
    domain, _ = classify_query_domain("Track my workout routine and family schedule")
    assert domain == "personal"


def test_categories_mapping_casual_minimal():
    categories = categories_for_domain("casual")
    assert categories == ["identity", "working"]
