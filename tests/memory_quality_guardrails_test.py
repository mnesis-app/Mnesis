from backend.memory import conversation_mining, core


def _sample_context() -> dict:
    return {
        "conversation_id": "conv-generic-1",
        "title": "Technical explanation",
        "source_llm": "chatgpt",
        "started_at": "2026-02-20T10:00:00+00:00",
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "content": "Explain what C++ is.",
                "timestamp": "2026-02-20T10:00:01+00:00",
            },
        ],
        "signal_score": 3,
    }


def test_guardrail_blocks_definition_style_generic_fact():
    generic = (
        "The user says C++ is a high-performance, compiled language that provides direct access "
        "to hardware resources such as memory and I/O operations."
    )
    assert conversation_mining._looks_generic_non_memory(generic) is True
    assert core._looks_generic_non_memory(generic) is True


def test_guardrail_keeps_personal_skill_memory():
    personal = "The user uses C++ daily for embedded systems at work."
    assert conversation_mining._looks_generic_non_memory(personal) is False
    assert core._looks_generic_non_memory(personal) is False


def test_llm_normalization_rejects_generic_definition_candidate():
    parsed = {
        "memories": [
            {
                "content": (
                    "The user says C++ is a high-performance, compiled language that provides direct "
                    "access to hardware resources such as memory and I/O operations."
                ),
                "category": "skills",
                "level": "semantic",
                "confidence": 0.98,
                "source_message_id": "m1",
            }
        ]
    }

    out = conversation_mining._normalize_llm_candidates(
        parsed=parsed,
        context=_sample_context(),
        min_confidence=0.75,
        max_candidates_per_conversation=6,
    )
    assert out == []

