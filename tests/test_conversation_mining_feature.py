import asyncio

from backend.memory import conversation_mining


def _sample_context() -> dict:
    return {
        "conversation_id": "conv-1",
        "title": "Profile discussion",
        "source_llm": "chatgpt",
        "started_at": "2026-02-20T10:00:00+00:00",
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "content": "I prefer concise technical answers with direct action items.",
                "timestamp": "2026-02-20T10:00:01+00:00",
            },
            {
                "id": "m2",
                "role": "user",
                "content": "I am working on a distributed systems project for my final year.",
                "timestamp": "2026-02-20T10:00:10+00:00",
            },
        ],
        "signal_score": 6,
    }


def test_heuristic_candidates_extract_memories():
    candidates = conversation_mining._heuristic_candidates_for_conversation(
        context=_sample_context(),
        max_candidates_per_conversation=6,
        min_confidence=0.7,
    )

    assert candidates
    contents = [c["content"].lower() for c in candidates]
    assert any("prefers concise technical answers" in c for c in contents)
    assert any("working on a distributed systems project" in c for c in contents)
    assert all(c["method"] == "heuristic" for c in candidates)


def test_normalize_llm_candidates_filters_invalid_items():
    parsed = {
        "memories": [
            {
                "content": "The user prefers concise replies.",
                "category": "preferences",
                "level": "semantic",
                "confidence": 0.9,
                "source_message_id": "m1",
            },
            {
                # Too short
                "content": "Short",
                "category": "preferences",
                "level": "semantic",
                "confidence": 0.95,
                "source_message_id": "m1",
            },
            {
                # First person should be filtered after normalization path.
                "content": "I prefer long answers.",
                "category": "preferences",
                "level": "semantic",
                "confidence": 0.95,
                "source_message_id": "m1",
            },
            {
                # Generic knowledge, not a user memory.
                "content": "The Model Context Protocol is an open standard protocol for AI tool integration.",
                "category": "skills",
                "level": "semantic",
                "confidence": 0.98,
                "source_message_id": "m1",
            },
        ]
    }

    out = conversation_mining._normalize_llm_candidates(
        parsed=parsed,
        context=_sample_context(),
        min_confidence=0.75,
        max_candidates_per_conversation=6,
    )

    assert len(out) == 2
    contents = [item["content"].lower() for item in out]
    assert any(content.startswith("the user prefers concise replies") for content in contents)
    assert any("the user prefer long answers" in content for content in contents)


def test_mine_memories_dry_run_uses_llm_candidates(monkeypatch):
    monkeypatch.setattr(
        conversation_mining,
        "_load_conversation_contexts",
        lambda **kwargs: {
            "contexts": [_sample_context()],
            "conversations_scanned": 1,
            "skipped_already_analyzed": 0,
        },
    )
    monkeypatch.setattr(
        conversation_mining,
        "_resolve_runtime",
        lambda **kwargs: {
            "provider": "ollama",
            "model": "llama3.2:3b",
            "api_base_url": "http://127.0.0.1:11434",
            "api_key": "",
        },
    )
    monkeypatch.setattr(conversation_mining, "_runtime_can_use_llm", lambda runtime: True)
    async def _fake_gate(**_kwargs):
        return {
            "required": True,
            "analysis_allowed": True,
            "llm_enabled": True,
            "configured": True,
            "reason": None,
            "runtime": {
                "provider": "ollama",
                "model": "llama3.2:3b",
                "api_base_url": "http://127.0.0.1:11434",
                "api_key": "",
            },
            "runtime_public": {
                "provider": "ollama",
                "model": "llama3.2:3b",
                "api_base_url": "http://127.0.0.1:11434",
            },
        }

    monkeypatch.setattr(conversation_mining, "get_analysis_llm_gate_status", _fake_gate)

    async def _fake_extract_candidates_with_llm(**kwargs):
        return [
            {
                "content": "The user prefers concise technical answers with direct action items.",
                "category": "preferences",
                "level": "semantic",
                "confidence": 0.9,
                "source_message_id": "m1",
                "conversation_id": "conv-1",
                "conversation_title": "Profile discussion",
                "method": "llm",
            }
        ]

    monkeypatch.setattr(conversation_mining, "_extract_candidates_with_llm", _fake_extract_candidates_with_llm)

    result = asyncio.run(
        conversation_mining.mine_memories_from_conversations(
            dry_run=True,
            max_conversations=20,
            max_messages_per_conversation=20,
            max_candidates_per_conversation=6,
        )
    )

    assert result["mode"] == "dry_run"
    assert result["candidates_total"] == 1
    assert result["candidate_sources"]["llm"] == 1
    assert result["candidate_sources"]["heuristic"] == 0


def test_mine_memories_import_tracks_write_stats(monkeypatch):
    monkeypatch.setattr(
        conversation_mining,
        "_load_conversation_contexts",
        lambda **kwargs: {
            "contexts": [_sample_context()],
            "conversations_scanned": 1,
            "skipped_already_analyzed": 0,
        },
    )
    monkeypatch.setattr(
        conversation_mining,
        "_resolve_runtime",
        lambda **kwargs: {"provider": "heuristic", "model": "", "api_base_url": "", "api_key": ""},
    )
    monkeypatch.setattr(conversation_mining, "_runtime_can_use_llm", lambda runtime: False)

    async def _fake_create_memory(**kwargs):
        return {"id": "mem-1", "action": "created"}

    async def _fake_link(_created_by_conversation):
        return 1

    async def _fake_upsert(candidates, **kwargs):
        touched = []
        for idx, c in enumerate(candidates):
            touched.append(
                {
                    "id": f"cand-{idx}",
                    "content": c["content"],
                    "category": c["category"],
                    "level": c["level"],
                    "confidence_score": c["confidence"],
                    "conversation_ids": [c["conversation_id"]],
                    "source_message_ids": [c["source_message_id"]],
                    "methods": [c["method"]],
                    "status": "pending",
                    "last_seen_at": c.get("source_message_timestamp"),
                    "evidence_count": 1,
                    "promotion_score": 0.95,
                }
            )
        return {"inserted": len(touched), "updated": 0, "semantic_merged": 0, "touched": touched}

    async def _fake_update_results(_items):
        return 1

    async def _fake_mark(*_args, **_kwargs):
        return 1

    async def _fake_index(*_args, **_kwargs):
        return 1

    monkeypatch.setattr(conversation_mining, "create_memory", _fake_create_memory)
    monkeypatch.setattr(conversation_mining, "_link_created_memories", _fake_link)
    monkeypatch.setattr(conversation_mining, "_upsert_conversation_candidates", _fake_upsert)
    monkeypatch.setattr(conversation_mining, "_update_candidate_results", _fake_update_results)
    monkeypatch.setattr(conversation_mining, "_mark_conversations_analyzed", _fake_mark)
    monkeypatch.setattr(conversation_mining, "_upsert_analysis_index", _fake_index)

    result = asyncio.run(
        conversation_mining.mine_memories_from_conversations(
            dry_run=False,
            max_conversations=20,
            max_messages_per_conversation=20,
            max_candidates_per_conversation=6,
            max_new_memories=20,
            require_llm_configured=False,
        )
    )

    assert result["mode"] == "import"
    assert result["write_stats"]["created"] >= 1
    assert result["linked_conversations"] == 1


def test_analysis_tags_store_provider_and_message_count():
    tags = conversation_mining._build_analysis_tags(
        existing_tags=[
            "foo",
            "auto:conversation-analysis:msgcount:4",
            "auto:conversation-analysis:provider:openai",
        ],
        provider="ollama",
        message_count=17,
    )

    lowered = {t.lower() for t in tags}
    assert "foo" in lowered
    assert "auto:conversation-analysis" in lowered
    assert "auto:conversation-analysis:provider:ollama" in lowered
    assert "auto:conversation-analysis:msgcount:17" in lowered
    assert conversation_mining._read_analyzed_msgcount(tags) == 17


def test_consolidate_candidates_merges_related_topic():
    candidates = [
        {
            "content": "A modern SaaS application called HomeBoard is to be created.",
            "category": "projects",
            "level": "semantic",
            "confidence": 0.9,
            "source_message_id": "m1",
            "conversation_id": "conv-homeboard",
            "conversation_title": "HomeBoard planning",
            "method": "llm",
        },
        {
            "content": "HomeBoard will utilize Next.js 16 with App Router, TypeScript, shadcn/ui, Tailwind CSS, and Aceternity UI components.",
            "category": "skills",
            "level": "semantic",
            "confidence": 0.86,
            "source_message_id": "m1",
            "conversation_id": "conv-homeboard",
            "conversation_title": "HomeBoard planning",
            "method": "llm",
        },
        {
            "content": "The application will be mobile-first and support collaborative workspaces with user invitations.",
            "category": "projects",
            "level": "semantic",
            "confidence": 0.84,
            "source_message_id": "m1",
            "conversation_id": "conv-homeboard",
            "conversation_title": "HomeBoard planning",
            "method": "llm",
        },
    ]

    out = conversation_mining._consolidate_candidates(candidates)

    assert len(out) == 1
    assert "homeboard" in out[0]["content"].lower()
    assert ";" in out[0]["content"]
    assert out[0]["method"].endswith(":condensed")


def test_consolidate_candidates_keeps_distinct_topics_separate():
    candidates = [
        {
            "content": "The user prefers concise technical responses.",
            "category": "preferences",
            "level": "semantic",
            "confidence": 0.9,
            "source_message_id": "m1",
            "conversation_id": "conv-mixed",
            "conversation_title": "Mixed notes",
            "method": "llm",
        },
        {
            "content": "The user has two cats and adopted one in 2024.",
            "category": "relationships",
            "level": "semantic",
            "confidence": 0.88,
            "source_message_id": "m2",
            "conversation_id": "conv-mixed",
            "conversation_title": "Mixed notes",
            "method": "llm",
        },
    ]

    out = conversation_mining._consolidate_candidates(candidates)

    assert len(out) == 2


def test_truncated_detection_rejects_ellipsis_candidates():
    assert conversation_mining._looks_truncated_memory_text("The user prefers concise answers...")
    assert conversation_mining._looks_truncated_memory_text("The user uses AI for three pillars…")
    assert not conversation_mining._looks_truncated_memory_text("The user prefers concise technical answers with direct action items.")
