import json
import os
import tempfile
from datetime import datetime, timezone

from backend.memory.importers.chatgpt import ChatGPTImporter
from backend.routers import import_export


def test_normalize_chatgpt_memories_filters_irrelevant_entries():
    raw = [
        {"content": "The user prefers concise answers when discussing architecture.", "original_category": "preferences"},
        {"content": "short", "original_category": "preferences"},
        {"content": "12345 67890", "original_category": "preferences"},
    ]

    normalized, ignored = import_export._normalize_chatgpt_memories(raw)

    assert len(normalized) == 1
    assert ignored == 2
    assert normalized[0]["category"] == "preferences"
    assert normalized[0]["level"] == "semantic"


def test_chatgpt_memory_relevance_rejects_generic_facts():
    assert import_export._is_relevant_chatgpt_memory(
        "Model Context Protocol is an open standard for connecting AI models."
    ) is False
    assert import_export._is_relevant_chatgpt_memory(
        "The user prefers concise answers and direct technical explanations."
    ) is True


def test_chatgpt_import_report_counts(monkeypatch):
    actions = ["created", "merged", "skipped", "conflict_pending", "error"]

    async def _fake_create_memory(**kwargs):
        return {"action": actions.pop(0)}

    monkeypatch.setattr(import_export, "create_memory", _fake_create_memory)

    memories = [
        {"content": f"Memory {i} with enough content for import handling.", "category": "preferences", "level": "semantic"}
        for i in range(5)
    ]

    import asyncio

    report = asyncio.run(import_export._import_chatgpt_memories(memories))

    assert report == {"imported": 1, "deduplicated": 2, "ignored": 2}


def test_chatgpt_conversation_parser_extracts_messages_from_mapping():
    payload = [
        {
            "title": "Conversation sample",
            "create_time": 1769540933.99166,
            "update_time": 1771323559.254737,
            "mapping": {
                "root": {"id": "root", "message": None, "parent": None, "children": ["u1"]},
                "u1": {
                    "id": "u1",
                    "message": {
                        "id": "u1",
                        "author": {"role": "user"},
                        "create_time": 1769540933.5,
                        "content": {"content_type": "text", "parts": ["Hello from user"]},
                        "metadata": {},
                    },
                    "parent": "root",
                    "children": ["a1"],
                },
                "a1": {
                    "id": "a1",
                    "message": {
                        "id": "a1",
                        "author": {"role": "assistant"},
                        "create_time": 1769540934.0,
                        "content": {"content_type": "text", "parts": ["Hello from assistant"]},
                        "metadata": {},
                    },
                    "parent": "u1",
                    "children": [],
                },
            },
        }
    ]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payload, fh)
        tmp_path = fh.name

    importer = ChatGPTImporter()
    conversations = list(importer.parse_conversations(tmp_path))
    os.unlink(tmp_path)

    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation["title"] == "Conversation sample"
    assert conversation["message_count"] == 2
    assert len(conversation["chat_messages"]) == 2
    assert conversation["chat_messages"][0]["role"] == "user"
    assert conversation["chat_messages"][0]["content"] == "Hello from user"
    assert conversation["chat_messages"][1]["role"] == "assistant"
    assert conversation["chat_messages"][1]["content"] == "Hello from assistant"


def test_chatgpt_memory_parser_ignores_conversation_rows():
    payload = [
        {
            "title": "Conversation sample",
            "create_time": 1769540933.99166,
            "mapping": {"root": {"id": "root", "message": None, "parent": None, "children": []}},
        },
        {"memory": "Julien préfère des réponses concises pour les revues techniques."},
    ]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payload, fh)
        tmp_path = fh.name

    importer = ChatGPTImporter()
    memories = importer.parse_memories(tmp_path)
    conversations = list(importer.parse_conversations(tmp_path))
    os.unlink(tmp_path)

    assert len(memories) == 1
    assert memories[0].content.startswith("Julien préfère")
    assert len(conversations) == 1


def test_chatgpt_parser_generates_stable_id_when_missing():
    payload = [
        {
            "title": "No explicit id",
            "create_time": 1769540933.99166,
            "update_time": 1771323559.254737,
            "mapping": {
                "root": {"id": "root", "message": None, "parent": None, "children": ["u1"]},
                "u1": {
                    "id": "u1",
                    "message": {
                        "id": "u1",
                        "author": {"role": "user"},
                        "create_time": 1769540933.5,
                        "content": {"content_type": "text", "parts": ["Message"]},
                        "metadata": {},
                    },
                    "parent": "root",
                    "children": [],
                },
            },
        }
    ]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payload, fh)
        tmp_path = fh.name

    importer = ChatGPTImporter()
    first = list(importer.parse_conversations(tmp_path))[0]["id"]
    second = list(importer.parse_conversations(tmp_path))[0]["id"]
    os.unlink(tmp_path)

    assert first == second
    assert first.startswith("chatgpt-")


def test_parse_datetime_accepts_unix_epoch_number():
    dt = import_export._parse_datetime(1769540933.5)
    assert isinstance(dt, datetime)
    assert dt.tzinfo == timezone.utc


def test_import_conversations_messages_deduplicates_existing_rows(monkeypatch):
    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def limit(self, _n):
            return self

        def to_list(self):
            return list(self._rows)

    class FakeTable:
        def __init__(self, existing_rows):
            self._existing_rows = list(existing_rows)
            self.added = []

        def search(self):
            return FakeQuery(self._existing_rows)

        def add(self, rows):
            self.added.extend(rows)

    class FakeDb:
        def __init__(self):
            self.tables = {
                "conversations": FakeTable([{"id": "c1"}]),
                "messages": FakeTable([{"id": "m1"}]),
            }

        def table_names(self):
            return list(self.tables.keys())

        def open_table(self, name):
            return self.tables[name]

    fake_db = FakeDb()
    monkeypatch.setattr(import_export, "get_db", lambda: fake_db)

    async def _run_inline(write_op):
        return await write_op()

    monkeypatch.setattr(import_export, "enqueue_write", _run_inline)

    import asyncio

    result = asyncio.run(
        import_export._import_conversations_messages(
            raw_conversations=[
                {"id": "c1", "title": "already there"},
                {"id": "c2", "title": "new"},
            ],
            raw_messages=[
                {"id": "m1", "conversation_id": "c1", "content": "dup"},
                {"id": "m2", "conversation_id": "c2", "content": "new message"},
            ],
        )
    )

    assert result["conversations"] == 1
    assert result["messages"] == 1
    assert result["deduplicated_conversations"] == 1
    assert result["deduplicated_messages"] == 1


def test_import_conversations_messages_deduplicates_by_fingerprint(monkeypatch):
    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def limit(self, _n):
            return self

        def to_list(self):
            return list(self._rows)

    class FakeTable:
        def __init__(self, existing_rows):
            self._existing_rows = list(existing_rows)
            self.added = []

        def search(self):
            return FakeQuery(self._existing_rows)

        def add(self, rows):
            self.added.extend(rows)

    class FakeDb:
        def __init__(self):
            self.tables = {
                "conversations": FakeTable(
                    [
                        {
                            "id": "conv-existing",
                            "title": "Budget plan",
                            "source_llm": "chatgpt",
                            "started_at": "2026-01-15T10:00:00+00:00",
                            "message_count": 2,
                        }
                    ]
                ),
                "messages": FakeTable(
                    [
                        {
                            "id": "msg-existing",
                            "conversation_id": "conv-existing",
                            "role": "assistant",
                            "content": "Sure, here is the budget plan.",
                            "timestamp": "2026-01-15T10:01:00+00:00",
                        }
                    ]
                ),
            }

        def table_names(self):
            return list(self.tables.keys())

        def open_table(self, name):
            return self.tables[name]

    fake_db = FakeDb()
    monkeypatch.setattr(import_export, "get_db", lambda: fake_db)

    async def _run_inline(write_op):
        return await write_op()

    monkeypatch.setattr(import_export, "enqueue_write", _run_inline)

    import asyncio

    result = asyncio.run(
        import_export._import_conversations_messages(
            raw_conversations=[
                {
                    "id": "conv-new-id",
                    "title": "Budget plan",
                    "source_llm": "chatgpt",
                    "started_at": "2026-01-15T10:00:00+00:00",
                    "message_count": 2,
                }
            ],
            raw_messages=[
                {
                    "id": "msg-new-id",
                    "conversation_id": "conv-new-id",
                    "role": "assistant",
                    "content": "Sure, here is the budget plan.",
                    "timestamp": "2026-01-15T10:01:00+00:00",
                }
            ],
        )
    )

    assert result["conversations"] == 0
    assert result["messages"] == 0
    assert result["deduplicated_conversations"] == 1
    assert result["deduplicated_messages"] == 1
